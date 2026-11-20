"""Page routes - HTML template rendering."""

import functools
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from gently.settings import settings

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _this_computers_zone() -> str:
    """The zone of the computer Gently runs on, as an IANA name ("Europe/Copenhagen"),
    or "" when it cannot say. Windows names its zones its own way; tzlocal maps them."""
    try:
        from tzlocal import get_localzone_name

        return get_localzone_name() or ""
    except Exception:
        logger.warning(
            "Could not tell this computer's time zone; pages show times in each browser's",
            exc_info=True,
        )
        return ""


def time_zone() -> str:
    """The zone every page shows its times in: Settings › Time zone if set, else the
    zone of the computer Gently runs on, else nothing (each browser's own)."""
    return settings.ui.time_zone or _this_computers_zone()


def create_router(server) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        """Serve the main SPA page.

        Viewing is open to everyone — the dashboard loads in view mode with no
        login. Signing in is an *elevation* to control (handled in-app via the
        chat window's "Sign in" affordance), not a gate on the page itself.

        The launch gate is the entry point: until it's submitted this session,
        every visit to / bounces to /launch (RFC #78 defer-init boot).
        """
        if not getattr(server, "gate_passed", False):
            # Carry the query string through the gate. Without this, any flag
            # passed to / is silently lost on the bounce — which made
            # /?atrium=1 land on the tabbed UI and look like the flag was
            # broken. launch.html carries it back on the way in.
            q = request.url.query
            return RedirectResponse(f"/launch?{q}" if q else "/launch", status_code=302)
        # The gate leads into the workspace. There used to be a second page
        # between them ("what are we doing today?"), and the only thing anyone
        # ever pressed on it was Skip.
        return server.templates.TemplateResponse(
            request,
            "index.html",
            {
                "active_section": "embryos",
                "is_live": True,
                "ux_v2": settings.ui.ux_v2,
                # The zone every time on the page is shown in (gently-time.js).
                "time_zone": time_zone(),
            },
        )

    # Standalone URLs redirect to SPA with hash fragment for tab routing
    @router.get("/review")
    async def review_page():
        return RedirectResponse("/#sessions", status_code=302)

    @router.get("/campaigns")
    async def campaigns_page():
        return RedirectResponse("/#plans", status_code=302)

    @router.get("/campaigns/{campaign_id}/review")
    async def plan_review_page(campaign_id: str):
        return RedirectResponse(f"/#plans:{campaign_id}", status_code=302)

    @router.get("/settings")
    async def settings_page():
        """Settings is a tab of the app now, not a page beside it."""
        return RedirectResponse("/#settings", status_code=302)

    return router
