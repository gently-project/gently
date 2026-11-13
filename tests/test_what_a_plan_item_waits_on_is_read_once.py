"""Which planned items are free to run is worked out from one read of the plans.

Each dependency of each planned item was looked up on its own, and a lookup
reads every campaign's plan until it finds the item. On the rig, with six
projects, listing them was a thousand YAML reads and 240 ms, and the Sessions
tab waited for that list before it drew a row ("made super efficient in
loading times").

The answers are the same: an item waits on the ones it depends on until each
is completed or skipped, wherever in the project tree they are, and is not
held up by one nobody can find.
"""

from __future__ import annotations

from gently.harness.memory.model import PlanItemStatus


def _project(cs):
    root = cs.create_campaign(description="Hatching timing", shorthand="hatching")
    phase = cs.create_campaign(description="Baseline at 20 °C", parent_id=root)
    return root, phase


def _free(cs, campaign_id) -> set[str]:
    return {i.id for i in cs.get_unblocked_plan_items(campaign_id)}


def test_an_item_waits_until_what_it_depends_on_is_done(file_context_store):
    cs = file_context_store
    root, _ = _project(cs)
    first = cs.create_plan_item(campaign_id=root, type="imaging", title="first")
    second = cs.create_plan_item(
        campaign_id=root, type="imaging", title="second", depends_on=[first]
    )
    assert _free(cs, root) == {first}
    cs.update_plan_item(first, status=PlanItemStatus.IN_PROGRESS)
    assert _free(cs, root) == set()
    cs.update_plan_item(first, status=PlanItemStatus.COMPLETED)
    assert _free(cs, root) == {second}


def test_a_skipped_dependency_no_longer_holds_an_item_up(file_context_store):
    cs = file_context_store
    root, _ = _project(cs)
    first = cs.create_plan_item(campaign_id=root, type="imaging", title="first")
    second = cs.create_plan_item(
        campaign_id=root, type="imaging", title="second", depends_on=[first]
    )
    cs.update_plan_item(first, status=PlanItemStatus.SKIPPED)
    assert _free(cs, root) == {second}


def test_every_dependency_has_to_be_done(file_context_store):
    cs = file_context_store
    root, _ = _project(cs)
    a = cs.create_plan_item(campaign_id=root, type="imaging", title="a")
    b = cs.create_plan_item(campaign_id=root, type="imaging", title="b")
    c = cs.create_plan_item(campaign_id=root, type="imaging", title="c", depends_on=[a, b])
    cs.update_plan_item(a, status=PlanItemStatus.COMPLETED)
    assert c not in _free(cs, root)
    cs.update_plan_item(b, status=PlanItemStatus.COMPLETED)
    assert c in _free(cs, root)


def test_a_dependency_in_another_part_of_the_project_counts(file_context_store):
    cs = file_context_store
    root, phase = _project(cs)
    in_phase = cs.create_plan_item(campaign_id=phase, type="imaging", title="baseline")
    on_root = cs.create_plan_item(
        campaign_id=root, type="analysis", title="compare", depends_on=[in_phase]
    )
    assert on_root not in _free(cs, root)
    cs.update_plan_item(in_phase, status=PlanItemStatus.COMPLETED)
    assert on_root in _free(cs, root)


def test_an_item_is_not_held_up_by_one_nobody_can_find(file_context_store):
    cs = file_context_store
    root, _ = _project(cs)
    orphan = cs.create_plan_item(
        campaign_id=root, type="imaging", title="orphan", depends_on=["no-such-item"]
    )
    assert orphan in _free(cs, root)


def test_the_plans_are_read_once_however_many_items_wait(file_context_store, monkeypatch):
    cs = file_context_store
    root, phase = _project(cs)
    first = cs.create_plan_item(campaign_id=phase, type="imaging", title="first")
    for n in range(12):
        cs.create_plan_item(
            campaign_id=root, type="imaging", title=f"waits {n}", depends_on=[first]
        )
    reads = []
    real = cs._read_plan_items_raw

    def counted(campaign_id):
        reads.append(campaign_id)
        return real(campaign_id)

    monkeypatch.setattr(cs, "_read_plan_items_raw", counted)
    assert _free(cs, root) == {first}
    # Twelve items each waiting on one: it was a read of every plan for each.
    # Now it is the two campaigns' plans to list the items, and each once
    # more for what they wait on.
    assert len(reads) <= 2 * len(cs._campaign_index) + 2, reads
