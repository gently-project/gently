"""
DataAssessmentEngine — Local data inventory.

Local data: direct GentlyStore SQL queries (fast, full detail).
Aggregates into NetworkDataInventory.
"""

import logging

from .models import NetworkDataInventory, SessionSummary

logger = logging.getLogger(__name__)


class DataAssessmentEngine:
    """Builds an inventory of local datasets.

    Parameters
    ----------
    gently_store : optional
        Local GentlyStore for direct SQL queries.
    """

    def __init__(self, gently_store=None):
        self._store = gently_store

    def inventory_local(self) -> list:
        """Inventory datasets from the local GentlyStore."""
        if self._store is None:
            return []

        sessions = []
        try:
            for sess in self._store.list_sessions():
                sid = sess.session_id if hasattr(sess, "session_id") else sess.get("session_id", "")
                sname = sess.name if hasattr(sess, "name") else sess.get("name", "")

                embryos = self._store.list_embryos(sid)
                embryo_count = len(embryos)
                vol_count = 0
                annotated = 0
                gt_count = 0
                stages = set()

                for emb in embryos:
                    eid = emb.embryo_id if hasattr(emb, "embryo_id") else emb.get("embryo_id", "")
                    vols = self._store.list_volumes(sid, eid)
                    vol_count += len(vols)
                    try:
                        gts = self._store.get_ground_truth(sid, eid)
                        if gts:
                            annotated += 1
                            gt_count += len(gts)
                            for gt in gts:
                                stage = gt.stage if hasattr(gt, "stage") else gt.get("stage", "")
                                if stage:
                                    stages.add(stage)
                    except Exception:
                        pass

                sessions.append(
                    SessionSummary(
                        session_id=sid,
                        session_name=sname,
                        embryo_count=embryo_count,
                        volume_count=vol_count,
                        annotated_embryos=annotated,
                        ground_truth_count=gt_count,
                        stages_covered=sorted(stages),
                        is_remote=False,
                    )
                )
        except Exception as e:
            logger.error(f"Local inventory failed: {e}")

        return sessions

    async def build_inventory(self) -> NetworkDataInventory:
        """Build a complete data inventory from the local store."""
        local = self.inventory_local()

        inventory = NetworkDataInventory(
            local_sessions=local,
            total_embryos=sum(s.embryo_count for s in local),
            total_volumes=sum(s.volume_count for s in local),
            total_annotated=sum(s.annotated_embryos for s in local),
            total_ground_truth=sum(s.ground_truth_count for s in local),
        )
        return inventory
