"""
Tests for ContextStore — campaigns, plan items, observations, learnings.
"""

from datetime import datetime

import pytest

from gently.harness.memory.model import (
    Confidence,
    Learning,
    Observation,
    PlanContext,
    PlanItemStatus,
    Significance,
)


class TestSchema:
    def test_tables_exist(self, context_store):
        """All expected tables should exist after init."""
        tables = context_store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {row["name"] for row in tables}
        expected = {
            "campaigns", "projects", "session_intents", "session_campaigns",
            "planned_sessions", "planned_session_campaigns",
            "learnings", "embryo_understanding", "observations",
            "expectations", "watchpoints", "questions",
            "plan_items", "plan_item_dependencies",
            "plan_templates", "plan_snapshots", "agent_state",
            "campaign_participants",
        }
        for t in expected:
            assert t in table_names, f"Missing table: {t}"

    def test_fresh_db_is_empty(self, context_store):
        rows = context_store._conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()
        assert rows[0] == 0


class TestCampaigns:
    def test_create_campaign(self, context_store):
        cid = context_store.create_campaign(description="Test campaign")
        assert cid is not None
        campaign = context_store.get_campaign(cid)
        assert campaign is not None
        assert campaign.description == "Test campaign"

    def test_create_campaign_with_shorthand(self, context_store):
        cid = context_store.create_campaign(
            description="Nerve ring formation study",
            shorthand="nrf-2026",
        )
        campaign = context_store.get_campaign(cid)
        assert campaign.shorthand == "nrf-2026"

    def test_get_active_campaigns(self, context_store):
        context_store.create_campaign(description="Campaign A")
        context_store.create_campaign(description="Campaign B")
        active = context_store.get_active_campaigns()
        assert len(active) == 2

    def test_get_root_campaigns(self, context_store):
        root = context_store.create_campaign(description="Root")
        context_store.create_campaign(description="Child", parent_id=root)
        roots = context_store.get_root_campaigns()
        assert len(roots) == 1
        assert roots[0].id == root

    def test_subcampaigns(self, context_store):
        root = context_store.create_campaign(description="Root")
        child1 = context_store.create_campaign(description="Phase 1", parent_id=root)
        child2 = context_store.create_campaign(description="Phase 2", parent_id=root)
        children = context_store.get_subcampaigns(root)
        assert len(children) == 2

    def test_update_campaign(self, context_store):
        cid = context_store.create_campaign(description="Original")
        context_store.update_campaign(cid, description="Updated", shorthand="upd")
        campaign = context_store.get_campaign(cid)
        assert campaign.description == "Updated"
        assert campaign.shorthand == "upd"

    def test_update_campaign_progress(self, context_store):
        cid = context_store.create_campaign(description="C1")
        context_store.update_campaign_progress(cid, "50% done")
        campaign = context_store.get_campaign(cid)
        assert campaign.progress == "50% done"

    def test_delete_campaign_cascade(self, context_store):
        root = context_store.create_campaign(description="Root")
        child = context_store.create_campaign(description="Child", parent_id=root)
        context_store.create_plan_item(campaign_id=child, type="imaging", title="Item 1")
        counts = context_store.delete_campaign(root, cascade=True)
        assert counts["campaigns"] == 2
        assert context_store.get_campaign(root) is None
        assert context_store.get_campaign(child) is None

    def test_share_and_unshare_campaign(self, context_store):
        cid = context_store.create_campaign(description="Shared campaign")
        assert len(context_store.get_shared_campaigns()) == 0
        context_store.share_campaign(cid)
        shared = context_store.get_shared_campaigns()
        assert len(shared) == 1
        context_store.unshare_campaign(cid)
        assert len(context_store.get_shared_campaigns()) == 0

    def test_campaign_participants(self, context_store):
        cid = context_store.create_campaign(description="Collab")
        context_store.add_campaign_participant(cid, "peer-1", "workstation-1")
        context_store.add_campaign_participant(cid, "peer-2", "microscope-1")
        participants = context_store.get_campaign_participants(cid)
        assert len(participants) == 2


class TestPlanItems:
    def test_create_and_get(self, context_store):
        cid = context_store.create_campaign(description="C1")
        item_id = context_store.create_plan_item(
            campaign_id=cid, type="imaging", title="Image embryos",
            description="20C timelapse",
        )
        item = context_store.get_plan_item(item_id)
        assert item is not None
        assert item.title == "Image embryos"
        assert item.status == PlanItemStatus.PLANNED

    def test_auto_phase_order(self, context_store):
        cid = context_store.create_campaign(description="C1")
        id1 = context_store.create_plan_item(campaign_id=cid, type="imaging", title="T1")
        id2 = context_store.create_plan_item(campaign_id=cid, type="bench", title="T2")
        item1 = context_store.get_plan_item(id1)
        item2 = context_store.get_plan_item(id2)
        assert item1.phase_order == 1
        assert item2.phase_order == 2

    def test_update_status(self, context_store):
        cid = context_store.create_campaign(description="C1")
        item_id = context_store.create_plan_item(
            campaign_id=cid, type="imaging", title="T1",
        )
        context_store.complete_plan_item(item_id, "Successful — 12 embryos")
        item = context_store.get_plan_item(item_id)
        assert item.status == PlanItemStatus.COMPLETED
        assert "12 embryos" in item.outcome

    def test_dependencies(self, context_store):
        cid = context_store.create_campaign(description="C1")
        id1 = context_store.create_plan_item(campaign_id=cid, type="bench", title="Prepare worms")
        id2 = context_store.create_plan_item(
            campaign_id=cid, type="imaging", title="Image worms",
            depends_on=[id1],
        )
        deps = context_store.get_plan_item_dependencies(id2)
        assert id1 in deps
        dependents = context_store.get_plan_item_dependents(id1)
        assert id2 in dependents

    def test_add_remove_dependency(self, context_store):
        cid = context_store.create_campaign(description="C1")
        id1 = context_store.create_plan_item(campaign_id=cid, type="bench", title="T1")
        id2 = context_store.create_plan_item(campaign_id=cid, type="imaging", title="T2")
        context_store.add_plan_item_dependency(id2, id1)
        assert id1 in context_store.get_plan_item_dependencies(id2)
        context_store.remove_plan_item_dependency(id2, id1)
        assert id1 not in context_store.get_plan_item_dependencies(id2)

    def test_get_plan_status(self, context_store):
        cid = context_store.create_campaign(description="C1")
        id1 = context_store.create_plan_item(campaign_id=cid, type="imaging", title="T1")
        context_store.create_plan_item(campaign_id=cid, type="bench", title="T2")
        context_store.complete_plan_item(id1, "done")
        status = context_store.get_plan_status(cid)
        assert status["total"] == 2
        assert status["completed"] == 1
        assert status["planned"] == 1

    def test_claim_plan_item(self, context_store):
        cid = context_store.create_campaign(description="C1")
        item_id = context_store.create_plan_item(
            campaign_id=cid, type="imaging", title="T1",
        )
        success = context_store.claim_plan_item(item_id, "peer-1", "workstation")
        assert success is True
        item = context_store.get_plan_item(item_id)
        assert item.claimed_by == "peer-1"
        # Another peer should fail to claim
        success2 = context_store.claim_plan_item(item_id, "peer-2", "other")
        assert success2 is False

    def test_unclaim_plan_item(self, context_store):
        cid = context_store.create_campaign(description="C1")
        item_id = context_store.create_plan_item(
            campaign_id=cid, type="imaging", title="T1",
        )
        context_store.claim_plan_item(item_id, "peer-1", "ws")
        context_store.unclaim_plan_item(item_id)
        item = context_store.get_plan_item(item_id)
        assert item.claimed_by is None

    def test_delete_plan_item(self, context_store):
        cid = context_store.create_campaign(description="C1")
        item_id = context_store.create_plan_item(
            campaign_id=cid, type="imaging", title="T1",
        )
        deleted = context_store.delete_plan_item(item_id)
        assert deleted is True
        assert context_store.get_plan_item(item_id) is None

    def test_list_plan_items_by_type(self, context_store):
        cid = context_store.create_campaign(description="C1")
        context_store.create_plan_item(campaign_id=cid, type="imaging", title="T1")
        context_store.create_plan_item(campaign_id=cid, type="bench", title="T2")
        context_store.create_plan_item(campaign_id=cid, type="imaging", title="T3")
        imaging_items = context_store.get_plan_items(campaign_id=cid, type="imaging")
        assert len(imaging_items) == 2

    def test_plan_item_preserves_microscope_thought_context(self, context_store):
        cid = context_store.create_campaign(description="C1")
        item_id = context_store.create_plan_item(
            campaign_id=cid,
            type="imaging",
            title="Embryo timelapse",
            plan_context={
                "technical": "Bottom overview XY, F/head-axis alignment, calibration first.",
                "experimental": "Ryan/Brie locate embryos and approve timelapse.",
                "theoretical": "Developmental timing remains interpretable.",
                "conceptual": "Biologist plans at the embryo-development level.",
                "sample_entity": "C. elegans embryo",
                "operator_context": "Immediate DiSPIM users Ryan and Brie",
                "constraints": ["Avoid head-axis overtravel near glass"],
                "success_question": "Can focus and calibration stay explicit?",
            },
        )

        item = context_store.get_plan_item(item_id)
        assert isinstance(item.plan_context, PlanContext)
        assert item.plan_context.technical.startswith("Bottom overview")
        assert item.plan_context.constraints == ["Avoid head-axis overtravel near glass"]

        context_store.update_plan_item(
            item_id,
            plan_context={
                "technical": "Calibration confirmed before timelapse.",
                "experimental": "Operator approves first acquisition.",
                "theoretical": "Reporter dynamics remain measurable.",
                "conceptual": "Planning layer governs microscope interaction.",
            },
        )
        updated = context_store.get_plan_item(item_id)
        assert updated.plan_context.technical == "Calibration confirmed before timelapse."
        assert updated.plan_context.conceptual == "Planning layer governs microscope interaction."

        template_id = context_store.save_plan_template(
            "context-template",
            "Plan context template",
            cid,
        )
        new_cid = context_store.apply_plan_template(template_id)
        cloned = context_store.get_plan_items(campaign_id=new_cid)[0]
        assert cloned.plan_context.theoretical == "Reporter dynamics remain measurable."


class TestFileContextPlanItems:
    def test_file_context_store_preserves_microscope_thought_context(self, file_context_store):
        cid = file_context_store.create_campaign(description="C1")
        item_id = file_context_store.create_plan_item(
            campaign_id=cid,
            type="imaging",
            title="Embryo timelapse",
            plan_context={
                "technical": "F-drive focus finding and calibration before timelapse.",
                "experimental": "Ryan/Brie workflow.",
                "theoretical": "Developmental timing remains interpretable.",
                "conceptual": "Biologist plans at embryo level.",
                "constraints": ["Avoid overtravel toward glass"],
            },
        )

        item = file_context_store.get_plan_item(item_id)
        assert isinstance(item.plan_context, PlanContext)
        assert item.plan_context.technical.startswith("F-drive focus")
        assert item.plan_context.constraints == ["Avoid overtravel toward glass"]


class TestObservations:
    def test_add_and_retrieve(self, context_store):
        obs = Observation(
            id="obs-1",
            timestamp=datetime.now(),
            type="stage_transition",
            content="Embryo moved to comma stage",
            embryo_id="emb-1",
            significance=Significance.HIGH,
            session_id="sess-1",
        )
        context_store.add_observation(obs)
        recent = context_store.get_recent_observations(limit=10)
        assert len(recent) == 1
        assert recent[0].content == "Embryo moved to comma stage"

    def test_filter_by_embryo(self, context_store):
        for i in range(3):
            context_store.add_observation(Observation(
                id=f"obs-{i}",
                timestamp=datetime.now(),
                type="check",
                content=f"Check {i}",
                embryo_id="emb-1" if i < 2 else "emb-2",
            ))
        emb1_obs = context_store.get_observations_for_embryo("emb-1")
        assert len(emb1_obs) == 2


class TestLearnings:
    def test_add_and_retrieve(self, context_store):
        learning = Learning(
            id="learn-1",
            content="C. elegans embryos at 20C take ~14h from first division to hatch",
            confidence=Confidence.HIGH,
            basis="Literature + 3 observed timelapses",
            created_at=datetime.now(),
        )
        context_store.add_learning(learning)
        learnings = context_store.get_learnings()
        assert len(learnings) == 1
        assert "14h" in learnings[0].content

    def test_multiple_learnings(self, context_store):
        for i in range(5):
            context_store.add_learning(Learning(
                id=f"learn-{i}",
                content=f"Learning {i}",
                created_at=datetime.now(),
            ))
        learnings = context_store.get_learnings()
        assert len(learnings) == 5


class TestAgentState:
    def test_set_and_get(self, context_store):
        context_store.set_state("current_focus", "monitoring timelapse")
        assert context_store.get_state("current_focus") == "monitoring timelapse"

    def test_get_nonexistent(self, context_store):
        assert context_store.get_state("nonexistent") is None

    def test_overwrite(self, context_store):
        context_store.set_state("key", "value1")
        context_store.set_state("key", "value2")
        assert context_store.get_state("key") == "value2"


class TestReset:
    def test_reset_clears_data(self, context_store):
        context_store.create_campaign(description="C1")
        context_store.add_learning(Learning(
            id="l1", content="test", created_at=datetime.now(),
        ))
        counts = context_store.reset()
        assert sum(counts.values()) > 0
        assert len(context_store.get_active_campaigns()) == 0
        assert len(context_store.get_learnings()) == 0


class TestContextManager:
    def test_context_manager(self, tmp_path):
        from gently.harness.memory.store import ContextStore
        with ContextStore(tmp_path / "ctx.db") as cs:
            cs.create_campaign(description="Test")
            assert len(cs.get_active_campaigns()) == 1
