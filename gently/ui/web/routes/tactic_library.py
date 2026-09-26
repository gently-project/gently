"""Tactic Library route.

Returns the saved tactic library from FileContextStore (``server.context_store``).
Never raises a 500 — returns an empty list when the store is absent or has no
saved tactics.
"""

from fastapi import APIRouter, Body, Depends, HTTPException

from gently.ui.web.auth import require_control


def create_router(server) -> APIRouter:
    router = APIRouter()

    @router.get("/api/tactic_library")
    async def get_tactic_library():
        cs = getattr(server, "context_store", None)
        if cs is None:
            return {"tactics": []}
        try:
            tactics = cs.list_tactics()
        except Exception:
            tactics = []
        if not tactics:
            return {"tactics": []}
        return {"tactics": tactics}

    @router.post("/api/tactic_library", dependencies=[Depends(require_control)])
    async def save_tactic_template(payload: dict = Body(...)):  # noqa: B008
        """Save a plan as a reusable template.

        Body: {name, kind, structure, scope?, rationale?}. The same document
        the agent's save_tactic tool writes, so a plan saved from the pane
        and one the agent saved are one kind of thing, listed together.
        """
        cs = getattr(server, "context_store", None)
        if cs is None:
            raise HTTPException(status_code=503, detail="No context store")
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name required")
        structure = payload.get("structure")
        if not isinstance(structure, dict) or not structure:
            raise HTTPException(status_code=400, detail="structure required")
        tactic = {
            "name": name,
            "kind": str(payload.get("kind") or "standing_timelapse"),
            "structure": structure,
            "scope": payload.get("scope") or {"mode": "global"},
            "rationale": payload.get("rationale") or "",
            "created_by": "operate",
        }
        try:
            tid = cs.save_tactic(tactic, name=name)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"save failed: {exc}") from exc
        return {"success": True, "id": tid, "name": name}

    return router
