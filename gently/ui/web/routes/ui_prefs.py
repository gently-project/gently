"""Choices about the surface that belong to the rig, not to one browser.

    GET /api/ui/rail-cards           {cards: {camera: true, ...}}
    PUT /api/ui/rail-cards           {cards: {led: false}} — merged, kept, told

The Bottom cam rail's cards fold (operate.js wireDisclosures), and which
are open used to live in each browser's localStorage. Ryan, 2026-10-09:
"rig wide please, and dynamic - that when i show or hide, it persists." So
the states live here, in ``<storage>/config/rail_cards.json`` beside the
settings history, every press writes through, every change is one line in
the history, and every browser looking at the rig hears UI_RAIL_CARDS and
follows.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from gently.ui.web.auth import require_control

logger = logging.getLogger(__name__)

FILENAME = "rail_cards.json"
CARDS = ("camera", "stage", "led", "focus", "overview", "advanced")


def _root() -> Path:
    """The live storage root, read at call time so a redirected root is honoured."""
    from gently.settings import settings

    return Path(settings.storage.base_path)


def path(root: Path | str | None = None) -> Path:
    """Beside the settings history, under the storage root."""
    from gently.core import settings_history

    return settings_history.path(root if root is not None else _root()).parent / FILENAME


def read(root: Path | str | None = None) -> dict[str, bool]:
    p = path(root)
    try:
        doc = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        logger.warning("rail cards unreadable at %s", p, exc_info=True)
        doc = {}
    cards = doc.get("cards") if isinstance(doc, dict) else None
    return {k: bool(v) for k, v in (cards or {}).items() if k in CARDS}


def write(cards: dict[str, bool], root: Path | str | None = None) -> Path:
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"cards": cards}, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def create_router(server) -> APIRouter:
    router = APIRouter()

    def _who(request: Request) -> dict[str, Any]:
        from gently.ui.web.routes.data import _who as who

        return who(request)

    def _tell(cards: dict[str, bool]) -> None:
        """Every browser on the rig hears the new state."""
        bridge = getattr(server, "agent_bridge", None)
        agent = bridge.agent if bridge is not None else None
        bus = getattr(agent, "_event_bus", None)
        if bus is None:
            return
        from gently.core.event_bus import EventType

        try:
            bus.publish(
                event_type=EventType.UI_RAIL_CARDS,
                data={"cards": cards},
                source="web:bottom-cam",
            )
        except Exception:
            logger.debug("rail cards not broadcast", exc_info=True)

    @router.get("/api/ui/rail-cards")
    async def get_rail_cards():
        return {"cards": await asyncio.to_thread(read, _root())}

    @router.put("/api/ui/rail-cards", dependencies=[Depends(require_control)])
    async def put_rail_cards(request: Request, body: dict = Body(default={})):  # noqa: B008
        """Merge what is sent into what is kept. A card not sent is left as
        it was, so one press writes one card."""
        from gently.core import settings_history

        raw = (body or {}).get("cards")
        if not isinstance(raw, dict) or not raw:
            raise HTTPException(status_code=400, detail="cards must be a non-empty object")
        for k, v in raw.items():
            if k not in CARDS:
                raise HTTPException(status_code=400, detail=f"no such card: {k}")
            if not isinstance(v, bool):
                raise HTTPException(status_code=400, detail=f"{k} must be true or false")
        root = _root()
        old = await asyncio.to_thread(read, root)
        new = dict(old)
        new.update({k: bool(v) for k, v in raw.items()})
        if new != old:
            await asyncio.to_thread(write, new, root)
            who = _who(request)
            for k in raw:
                if old.get(k) != new[k]:
                    settings_history.record(
                        f"views.railCards.{k}",
                        old.get(k),
                        new[k],
                        reach="rig",
                        via="Bottom cam",
                        label=f"Bottom cam · {k} card",
                        root=root,
                        **who,
                    )
            _tell(new)
        return {"cards": new}

    return router
