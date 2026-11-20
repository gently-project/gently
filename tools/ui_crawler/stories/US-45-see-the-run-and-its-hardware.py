# ruff: noqa: E501
"""US-45 — See the live run and its hardware. As an operator, I open Run and read what the
live session's acquisition is set to do, in words, above its hardware timeline."""

from _harness import exists, goto, skip_landing, tab

META = {
    "id": "US-45",
    "title": "See the live run and its hardware",
    "cluster": "8 The run",
    "mode": "headless",
    "needs_account": False,
}


async def flow(page, url, rec):
    await goto(page, url)
    await skip_landing(page)
    await tab(page, "experiment")
    summary = await exists(page, "#run-root .run-summary")
    timeline = await exists(page, '#run-root .hwt[data-state="ready"]')
    await rec.shot("run")
    if summary and timeline:
        rec.ok(
            "the Run tab says the live acquisition in words above the session's hardware timeline"
        )
    elif await exists(page, "#run-root"):
        rec.partial(
            "the Run tab is there but the live session has acquired nothing yet: it shows its empty state until a run images something"
        )
    else:
        rec.gap("no Run tab")
