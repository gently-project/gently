"""The Sessions view's Hardware tab, driven in a real browser.

"just start building and do proper testing. use playwright." CI drives no
browser, so this skips there (no Chromium to launch); on a machine with one
(`uv run playwright install chromium`) it launches the real app offline on a
storage root of its own, seeded with two sessions — one recorded the way the
instrument now records, one from before — and works the timeline the way a
person would: open a session, open the tab, hover, click, scroll, step with
the keys, hide an embryo, read the table, switch the theme.
"""

from __future__ import annotations

import json
import math
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from gently.core.file_store import FileStore, utc_of_epoch

sync_api = pytest.importorskip("playwright.sync_api")

REPO = Path(__file__).resolve().parents[1]
# 2026-11-19T09:00:00Z, by hand: 1795424400 s since 1970.
T0 = 1795424400.0
ROUNDS, EVERY_S = 6, 120.0
EMBRYOS = [
    ("embryo_1", "A", {"488": 2.5, "561": 8.0}, "A"),
    ("embryo_2", "B", {"488": 4.0}, "A"),
    ("embryo_3", "C", {"488": 4.0}, "AB"),
]
SLICES, EXPOSURE_MS, PERIOD_S = 20, 20.0, 0.041


def _local(epoch: float) -> str:
    return datetime.fromtimestamp(epoch).isoformat()


def seed_recorded(store: FileStore, sid: str = "hw_recorded") -> dict:
    """A session the way the instrument records now. Returns the moments the
    checks aim at: each volume's scan and each brightfield light window."""
    store.create_session(sid, name="Recorded hardware")
    for eid, nick, _, _ in EMBRYOS:
        store.register_embryo(sid, eid, nickname=nick)
    vol = np.zeros((SLICES, 16, 16), np.uint16)
    frame = np.full((32, 32), 900, np.uint16)
    marks: dict = {"volumes": [], "bf": []}
    for r in range(ROUNDS):
        t = T0 + r * EVERY_S
        for field in range(3):
            t += 0.8  # the stage moves to the field
            on = t
            t += 0.5  # the LED settles
            exposed = t + 0.012
            t += 0.06
            off = t
            store.put_snapshot(
                sid,
                "bf",
                frame,
                metadata={
                    "channel": "bf",
                    "frame": r + 1,
                    "field": field,
                    "fields": 3,
                    "round": r + 1,
                    "exposure_ms": 10.0,
                    "light": "led",
                    "led_intensity_pct": 30,
                    "captured_at": _local(off + 0.01),
                    "light_on_utc": utc_of_epoch(on),
                    "light_off_utc": utc_of_epoch(off),
                    "exposed_utc": utc_of_epoch(exposed),
                },
            )
            marks["bf"].append({"round": r + 1, "field": field, "on": on, "off": off})
        for eid, _, lasers, sides in EMBRYOS:
            t += 1.2  # the stage moves to the embryo
            for side in sides:
                lasers_on = t
                scan = t + 0.25
                first = scan + 0.045
                last = first + (SLICES - 1) * PERIOD_S
                lasers_off = last + 0.12
                hw = {
                    "laser_config": "488 and 561" if "561" in lasers else "488 only",
                    "lines": sorted(int(k) for k in lasers),
                    "powers_pct": lasers,
                    "num_slices": SLICES,
                    "exposure_ms": EXPOSURE_MS,
                    "lasers_on_utc": utc_of_epoch(lasers_on),
                    "scan_started_utc": utc_of_epoch(scan),
                    "first_frame_utc": utc_of_epoch(first),
                    "last_frame_utc": utc_of_epoch(last),
                    "lasers_off_utc": utc_of_epoch(lasers_off),
                }
                store.put_volume(
                    sid,
                    eid,
                    r + 1,
                    vol,
                    side=side,
                    metadata={
                        "num_slices": SLICES,
                        "exposure_ms": EXPOSURE_MS,
                        "laser_power_488_pct": lasers["488"],
                        "laser_power_561_pct": lasers.get("561"),
                        "side": side,
                        "hardware": hw,
                    },
                    acquired_at=_local(scan),
                    acquired_at_utc=utc_of_epoch(scan),
                )
                marks["volumes"].append(
                    {"embryo": eid, "t": r + 1, "side": side, "scan": scan, "last": last}
                )
                t = lasers_off + 0.3
    # The bath at 1 Hz: 20 C, then a step to 21 C half way, followed with a lag.
    end = T0 + ROUNDS * EVERY_S
    sd = store._session_dir(sid)
    assert sd is not None
    path = sd / "temperature.jsonl"
    with path.open("w") as fh:
        water = 20.0
        for i in range(int(end - T0) + 60):
            ts = T0 - 30 + i
            sp = 20.0 if ts < T0 + 3 * EVERY_S else 21.0
            water += (sp - water) / 60.0
            noise = 0.02 * math.sin(i * 1.7)
            fh.write(
                json.dumps(
                    {
                        "t": utc_of_epoch(ts).replace("Z", "+00:00"),
                        "water_c": round(water + noise, 3),
                        "setpoint_c": sp,
                    }
                )
                + "\n"
            )
    return marks


def seed_from_before(store: FileStore, sid: str = "hw_before") -> None:
    """A session from before the hardware was recorded: settings and times only."""
    store.create_session(sid, name="From before")
    store.register_embryo(sid, "embryo_1", nickname="A")
    vol = np.zeros((SLICES, 16, 16), np.uint16)
    for r in range(3):
        t = T0 - 86400 + r * 300
        store.put_snapshot(
            sid,
            "bf",
            np.full((32, 32), 900, np.uint16),
            metadata={
                "channel": "bf",
                "frame": r + 1,
                "field": 0,
                "fields": 1,
                "exposure_ms": 10.0,
                "light": "led",
                "led_intensity_pct": 30,
                "captured_at": _local(t),
            },
        )
        store.put_volume(
            sid,
            "embryo_1",
            r + 1,
            vol,
            metadata={"num_slices": SLICES, "exposure_ms": 10.0, "laser_power_488_pct": 3.0},
            acquired_at=_local(t + 2),
            acquired_at_utc=utc_of_epoch(t + 2),
        )


def seed_night(store: FileStore, sid: str = "hw_night", rounds: int = 150) -> None:
    """A night of rounds, far more than the plot has pixels for. Sidecars
    only: the timeline reads nothing else."""
    import yaml

    store.create_session(sid, name="A long night")
    for eid, nick, _, _ in EMBRYOS:
        store.register_embryo(sid, eid, nickname=nick)
    sd = store._session_dir(sid)
    assert sd is not None
    for r in range(rounds):
        t = T0 + r * EVERY_S
        for eid, _, lasers, _ in EMBRYOS:
            t += 2.0
            scan, last = t + 0.2, t + 0.2 + 0.045 + (SLICES - 1) * PERIOD_S
            hw = {
                "laser_config": "488 only",
                "lines": [488],
                "powers_pct": {"488": lasers["488"]},
                "num_slices": SLICES,
                "exposure_ms": EXPOSURE_MS,
                "lasers_on_utc": utc_of_epoch(t),
                "scan_started_utc": utc_of_epoch(scan),
                "first_frame_utc": utc_of_epoch(scan + 0.045),
                "last_frame_utc": utc_of_epoch(last),
                "lasers_off_utc": utc_of_epoch(last + 0.12),
            }
            vd = sd / "embryos" / eid / "volumes"
            vd.mkdir(parents=True, exist_ok=True)
            (vd / f"t{r + 1:04d}.meta.yaml").write_text(
                yaml.safe_dump(
                    {
                        "embryo_id": eid,
                        "timepoint": r + 1,
                        "side": "A",
                        "acquired_at_utc": utc_of_epoch(scan),
                        "metadata": {
                            "num_slices": SLICES,
                            "exposure_ms": EXPOSURE_MS,
                            "hardware": hw,
                        },
                    }
                )
            )


# ---- the app, and a browser -------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except sync_api.Error as exc:
            pytest.skip(f"no browser to drive here ({str(exc).splitlines()[0]})")
        yield b
        b.close()


@pytest.fixture(scope="module")
def app(tmp_path_factory, browser):
    root = tmp_path_factory.mktemp("gently-hardware")
    store = FileStore(root=root)
    marks = seed_recorded(store)
    seed_from_before(store)
    seed_night(store)
    port = _free_port()
    log = (root / "launch.log").open("w")
    env = {
        **os.environ,
        "GENTLY_STORAGE_PATH": str(root),
        "GENTLY_VIZ_PORT": str(port),
        "ANTHROPIC_API_KEY": "",
        "GENTLY_NO_AUTH": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "launch_gently.py", "--offline", "--no-api", "--no-auth", "--no-browser"],
        cwd=REPO,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    url = f"http://localhost:{port}"

    def wait_for(what, call):
        deadline = time.time() + 90
        while True:
            try:
                return call()
            except Exception:
                if proc.poll() is not None or time.time() > deadline:
                    tail = (root / "launch.log").read_text()[-3000:]
                    pytest.fail(f"the app on {url} never {what}:\n{tail}")
                time.sleep(0.5)

    try:
        wait_for(
            "answered", lambda: urllib.request.urlopen(f"{url}/api/sessions", timeout=2).read()
        )
        # Past the launch gate the way "Make live" goes, so the gate's remembered
        # choices (config/launch.local.json, the repo's own) are never written;
        # the recorded session is the live one, the Operations tab's.
        # The list answers before the agent is up: until then this is a 503.
        wait_for(
            "let a session open",
            lambda: urllib.request.urlopen(
                urllib.request.Request(
                    f"{url}/api/sessions/hw_recorded/resume", data=b"", method="POST"
                ),
                timeout=30,
            ).read(),
        )
        yield {"url": url, "root": root, "marks": marks}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


@pytest.fixture
def page(browser, app):
    ctx = browser.new_context(viewport={"width": 1500, "height": 950})
    pg = ctx.new_page()
    errors: list[str] = []

    def console(m):
        # Offline, the device layer's routes answer 502/503: that is the rig
        # being away, not this page failing.
        if m.type == "error" and "Failed to load resource" not in m.text:
            errors.append(m.text)

    def response(r):
        if "/hardware-sequence" in r.url and r.status != 200:
            errors.append(f"{r.status} {r.url}")

    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", console)
    pg.on("response", response)
    pg.errors = errors  # type: ignore[attr-defined]
    yield pg
    ctx.close()


def _open(page, app, sid="hw_recorded"):
    page.goto(f"{app['url']}/#sessions:{sid}", wait_until="domcontentloaded")
    page.locator('.session-tabs .tab[data-tab="hardware"]').click(timeout=20_000)
    page.wait_for_selector('.hwt[data-state="ready"]', timeout=20_000)
    return page


def _state(page):
    return page.evaluate("HardwareTimeline.state()")


def _shot(page, name):
    out = os.environ.get("HWT_SHOTS")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(out) / f"{name}.png"), full_page=False)


# ---- the checks --------------------------------------------------------------


def _at(page, t, row):
    return page.evaluate("([t, row]) => HardwareTimeline.pointAt(t, row)", [t, row])


def _volume(app, embryo, t, side="A"):
    return next(
        v
        for v in app["marks"]["volumes"]
        if v["embryo"] == embryo and v["t"] == t and v["side"] == side
    )


def _inked(page):
    return page.evaluate(
        """() => { const c = document.querySelector('.hwt-canvas');
                   const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
                   let n = 0;
                   for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
                   return n; }"""
    )


def test_the_hardware_tab_draws_a_sessions_sequence(page, app):
    _open(page, app)
    st = _state(page)
    assert st["rows"] == ["bf", "488", "561", "exposure", "temp"]
    assert len(st["rounds"]) == ROUNDS
    assert st["where"].startswith("Whole session")
    # The legend names each embryo, and the dish's light.
    keys = page.locator(".hwt-legend .hwt-key:not([hidden])").all_inner_texts()
    assert keys == ["A", "B", "C", "Brightfield (the dish)"]
    assert _inked(page) > 5_000
    # Every word is HTML, drawn like the rest of the page: canvas text has
    # no subpixel smoothing and read as smudged beside it.
    rows = page.locator(".hwt-row-label strong").all_inner_texts()
    assert rows == ["BF light", "488 nm", "561 nm", "Exposure", "Temperature"]
    ticks = page.locator(".hwt-tick").all_inner_texts()
    assert "0:00" in ticks and "10:00" in ticks
    assert page.locator(".hwt-caption").inner_text() == "Time since the first acquisition"
    _shot(page, "01-whole-session")
    assert page.errors == []  # type: ignore[attr-defined]


def test_the_timepoint_slider_stays_with_the_embryos(page, app):
    """The Embryos tab's slider moves its pictures; on Hardware it would move nothing."""
    _open(page, app)
    assert not page.locator("#session-scrub").is_visible()


def test_a_round_opens_from_the_whole_session_and_the_session_comes_back(page, app):
    _open(page, app)
    page.locator('.hwt-btn[data-act="next"]').click()
    assert _state(page)["where"].startswith("Round 1 of 6")
    page.locator('.hwt-btn[data-act="next"]').click()
    st = _state(page)
    assert st["where"].startswith("Round 2 of 6 · 2:00")
    r = st["rounds"][1]
    assert st["view"]["a"] <= r["a"] and st["view"]["b"] >= r["b"]
    page.locator('.hwt-btn[data-act="prev"]').click()
    assert _state(page)["where"].startswith("Round 1 of 6")
    page.locator(".hwt-plot").dblclick(position={"x": 300, "y": 20})
    assert _state(page)["where"].startswith("Whole session")


def test_clicking_a_mark_opens_its_round(page, app):
    _open(page, app)
    lit = next(m for m in app["marks"]["bf"] if m["round"] == 3 and m["field"] == 1)
    pt = _at(page, (lit["on"] + lit["off"]) / 2, "bf")
    page.mouse.click(pt["x"], pt["y"])
    assert _state(page)["where"].startswith("Round 3 of 6")


def test_hovering_a_volume_names_it_its_lasers_and_its_timing(page, app):
    _open(page, app)
    page.locator('.hwt-btn[data-act="next"]').click()
    v = _volume(app, "embryo_1", 1)
    pt = _at(page, (v["scan"] + v["last"]) / 2, "488")
    page.mouse.move(pt["x"], pt["y"])
    tip = page.locator(".hwt-tip")
    assert tip.is_visible()
    text = tip.inner_text()
    assert "A · volume t1" in text
    assert "2.5 %" in text and "488 nm" in text
    assert "8 %" in text and "561 nm" in text
    assert "20 × 20 ms" in text
    assert "41 ms" in text  # the slice period, measured from the frames
    assert "488 and 561" in text
    _shot(page, "02-round-1-hover-volume")


def test_brightfield_light_is_the_dishs_not_an_embryos(page, app):
    _open(page, app)
    page.locator('.hwt-btn[data-act="next"]').click()
    lit = next(m for m in app["marks"]["bf"] if m["round"] == 1 and m["field"] == 0)
    pt = _at(page, (lit["on"] + lit["off"]) / 2, "bf")
    page.mouse.move(pt["x"], pt["y"])
    text = page.locator(".hwt-tip").inner_text()
    assert "Brightfield · field 1 of 3 · frame 1" in text
    assert "30 %" in text and "LED" in text and "light on" in text
    # The legend lists the dish's light, but it is nobody's to hide.
    key = page.locator(".hwt-legend .hwt-key-static:not(.hwt-key-several)")
    assert key.inner_text() == "Brightfield (the dish)"
    assert key.evaluate("e => e.tagName") == "SPAN"


def test_the_wheel_zooms_about_the_pointer(page, app):
    _open(page, app)
    before = _state(page)
    t = before["rounds"][2]["a"]
    pt = _at(page, t, "488")
    page.mouse.move(pt["x"], pt["y"])
    page.mouse.wheel(0, -600)
    page.wait_for_timeout(150)
    after = _state(page)
    span0 = before["view"]["b"] - before["view"]["a"]
    span1 = after["view"]["b"] - after["view"]["a"]
    assert span1 < span0 / 2
    # The moment under the pointer stayed under it.
    assert abs(_at(page, t, "488")["x"] - pt["x"]) < 2


def test_down_at_the_slices_each_exposure_is_drawn(page, app):
    """Zoomed onto one stack, its twenty exposures are twenty marks, at the
    period its frames came."""
    _open(page, app)
    page.locator('.hwt-btn[data-act="next"]').click()
    v = _volume(app, "embryo_1", 1)
    mid = (v["scan"] + v["last"]) / 2
    pt = _at(page, mid, "exposure")
    page.mouse.move(pt["x"], pt["y"])
    for _ in range(30):
        st = _state(page)
        if st["view"]["b"] - st["view"]["a"] < 1.2:
            break
        page.mouse.wheel(0, -200)
        page.wait_for_timeout(30)
    page.mouse.move(5, 5)  # off the plot: no crosshair, no ring
    page.wait_for_timeout(100)
    runs = page.evaluate(
        """([t0, t1]) => {
            const c = document.querySelector('.hwt-canvas');
            const a = HardwareTimeline.pointAt(t0, 'exposure');
            const b = HardwareTimeline.pointAt(t1, 'exposure');
            const r = c.getBoundingClientRect(), k = c.width / r.width;
            const y = Math.round((a.y - r.top - 4) * k);
            const x0 = Math.round((a.x - r.left - 2) * k), x1 = Math.round((b.x - r.left + 30) * k);
            const d = c.getContext('2d').getImageData(x0, y, x1 - x0, 1).data;
            let runs = 0, inside = false;
            for (let i = 3; i < d.length; i += 4) {
                const on = d[i] > 128;
                if (on && !inside) runs++;
                inside = on;
            }
            return runs;
        }""",
        [v["scan"], v["last"]],
    )
    assert runs == SLICES
    _shot(page, "03-slices")


def test_the_keys_walk_the_marks_in_time_order(page, app):
    _open(page, app)
    page.locator(".hwt-plot").focus()
    page.keyboard.press("ArrowRight")
    assert _state(page)["focus"] == "Brightfield · field 1 of 3 · frame 1"
    page.keyboard.press("ArrowRight")
    assert _state(page)["focus"] == "Brightfield · field 2 of 3 · frame 1"
    assert "field 2 of 3" in page.locator(".hwt-sr").inner_text()
    page.keyboard.press("Enter")
    assert _state(page)["where"].startswith("Round 1 of 6")
    page.keyboard.press("]")
    assert _state(page)["where"].startswith("Round 2 of 6")
    page.keyboard.press("0")
    assert _state(page)["where"].startswith("Whole session")


def test_a_focused_mark_keeps_its_ring_when_the_view_zooms(page, app):
    _open(page, app)
    page.locator(".hwt-plot").focus()
    page.keyboard.press("ArrowRight")
    first = app["marks"]["bf"][0]
    for _ in range(3):
        page.keyboard.press("+")
    box = _state(page)["focusBox"]
    at = page.evaluate(
        "t => HardwareTimeline.pointAt(t, 'bf').x"
        " - document.querySelector('.hwt-plot').getBoundingClientRect().left",
        first["on"],
    )
    assert abs(box["x"] - at) < 3


def test_the_keys_step_past_embryos_the_legend_hides(page, app):
    _open(page, app)
    for key in ("embryo_1", "embryo_2", "embryo_3"):
        page.locator(f'.hwt-legend .hwt-key[data-key="{key}"]').click()
    page.locator(".hwt-plot").focus()
    heads = []
    for _ in range(4):
        page.keyboard.press("ArrowRight")
        heads.append(_state(page)["focus"])
    # Only the dish's light is left to step through: round 1's three frames, then round 2's.
    assert heads == [
        "Brightfield · field 1 of 3 · frame 1",
        "Brightfield · field 2 of 3 · frame 1",
        "Brightfield · field 3 of 3 · frame 1",
        "Brightfield · field 1 of 3 · frame 2",
    ]


def test_hiding_an_embryo_takes_its_marks_away(page, app):
    _open(page, app)
    page.locator('.hwt-btn[data-act="next"]').click()
    key = page.locator('.hwt-legend .hwt-key[data-key="embryo_2"]')
    key.click()
    assert key.get_attribute("aria-pressed") == "false"
    assert _state(page)["hidden"] == ["embryo_2"]
    v = _volume(app, "embryo_2", 1)
    pt = _at(page, (v["scan"] + v["last"]) / 2, "488")
    page.mouse.move(pt["x"], pt["y"])
    assert not page.locator(".hwt-tip").is_visible()
    key.click()
    page.mouse.move(pt["x"] + 1, pt["y"])
    assert "B · volume t1" in page.locator(".hwt-tip").inner_text()


def test_the_table_lists_every_volume_and_frame(page, app):
    _open(page, app)
    page.locator('.hwt-btn[data-act="table"]').click()
    rows = page.locator(".hwt-table tbody tr")
    assert rows.count() == len(app["marks"]["volumes"]) + len(app["marks"]["bf"])
    first = rows.nth(0).inner_text()
    assert "0:00.00" in first and "Brightfield field 1" in first and "LED 30 %" in first
    assert "Volume t1" in page.locator(".hwt-table").inner_text()


def test_a_session_from_before_says_its_marks_were_not_recorded(page, app):
    _open(page, app, "hw_before")
    note = page.locator(".hwt-note")
    assert note.is_visible()
    assert "before the hardware was recorded" in note.inner_text()
    page.locator('.hwt-btn[data-act="next"]').click()
    assert _state(page)["where"].startswith("Round 1 of 3 · 0:00")
    page.locator('.hwt-btn[data-act="table"]').click()
    assert "settings only" in page.locator(".hwt-table").inner_text()
    _shot(page, "04-from-before")


def test_both_themes_draw(page, app):
    _open(page, app)
    for theme in ("dark", "light"):
        page.evaluate(
            "t => { document.documentElement.setAttribute('data-theme', t);"
            " document.body.setAttribute('data-theme', t); }",
            theme,
        )
        page.wait_for_timeout(150)
        assert _inked(page) > 5_000
        _shot(page, f"05-theme-{theme}")
    assert page.errors == []  # type: ignore[attr-defined]


def test_a_pixel_holding_several_embryos_says_so_and_takes_no_ones_colour(page, app):
    """A night is more rounds than the plot has pixels. Drawn mark by mark,
    the last embryo painted over the others: every row read as embryo C."""
    _open(page, app, "hw_night")
    several = page.locator(".hwt-key-several")
    assert several.is_visible()
    st = _state(page)
    mid = st["rounds"][75]
    pt = _at(page, (mid["a"] + mid["b"]) / 2, "488")
    page.mouse.move(pt["x"], pt["y"])
    text = page.locator(".hwt-tip").inner_text()
    assert "marks here" in text
    assert all(label in text for label in ("A", "B", "C"))
    _shot(page, "06-night")
    # Opened, a round's embryos stand apart again.
    page.mouse.click(pt["x"], pt["y"])
    assert _state(page)["where"].startswith("Round")
    page.mouse.move(5, 5)
    assert not several.is_visible()


def test_the_operations_tab_follows_the_live_session(page, app):
    """The live session's hardware, beside its plan, kept current as it runs."""
    page.goto(app["url"], wait_until="domcontentloaded")
    page.locator('nav button:has-text("Operations")').click()
    # The main view: what opens with the tab, no click on a view needed.
    page.wait_for_selector('#experiment-overview-root .hwt[data-state="ready"]', timeout=20_000)
    hardware = page.locator('[data-experiment-view="hardware"]')
    assert "active" in hardware.get_attribute("class").split()
    live = "ExperimentOverview._hw.state()"
    assert page.evaluate(live)["rows"] == ["bf", "488", "561", "exposure", "temp"]
    assert len(page.evaluate(live)["rounds"]) == ROUNDS
    # A seventh round lands, the way the run files it, and its event arrives.
    store = FileStore(root=app["root"])
    t = T0 + ROUNDS * EVERY_S + 2
    stamp = {
        k: utc_of_epoch(t + d)
        for k, d in (
            ("lasers_on", 0),
            ("scan_started", 0.25),
            ("first_frame", 0.3),
            ("last_frame", 1.1),
            ("lasers_off", 1.2),
        )
    }
    store.put_volume(
        "hw_recorded",
        "embryo_1",
        ROUNDS + 1,
        np.zeros((SLICES, 16, 16), np.uint16),
        metadata={
            "num_slices": SLICES,
            "exposure_ms": EXPOSURE_MS,
            "hardware": {
                "laser_config": "488 and 561",
                "lines": [488, 561],
                "powers_pct": {"488": 2.5, "561": 8.0},
                "num_slices": SLICES,
                "exposure_ms": EXPOSURE_MS,
                **{f"{k}_utc": v for k, v in stamp.items()},
            },
        },
        acquired_at_utc=stamp["scan_started"],
    )
    page.evaluate("ClientEventBus.emit('VOLUME_ACQUIRED', {embryo_id: 'embryo_1'})")
    page.wait_for_function(
        f"ExperimentOverview._hw.state().rounds.length === {ROUNDS + 1}", timeout=10_000
    )
    _shot(page, "07-operations")
    # The Sessions view's timeline is another one, and was not disturbed.
    assert page.evaluate("HardwareTimeline.state().state") in ("none", "ready")
    assert page.errors == []  # type: ignore[attr-defined]
