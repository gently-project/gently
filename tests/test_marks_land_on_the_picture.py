"""A mark on a frame stays on its embryo, and a frame's overlay closes on a
click anywhere off the picture.

"the label marker on the image seems to have moved a bit": the twitch→hatch
pins were fractions of a box around the viewer — picture, gap and contrast
bar — so they sat below and to the right of the click, by more the shorter
the window. The marks were right; the box was wrong. And "when i clicked on
the black space outside the image, as i would have expected it to work, it
didn't do anything": the overlay closed only on its own margin, not on the
dark around the frame, and its × was a bare glyph.
"""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
VIEW = (WEB / "static" / "js" / "u16view.js").read_text(encoding="utf-8")
TOOL = (WEB / "static" / "js" / "tools" / "twitch-hatch.js").read_text(encoding="utf-8")
MAIN_CSS = (WEB / "static" / "css" / "main.css").read_text(encoding="utf-8")
REVIEW_CSS = (WEB / "static" / "css" / "review.css").read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    """The one rule whose selector is exactly this, not a host's override of it."""
    m = re.search(r"^" + re.escape(selector) + r" \{([^}]*)\}", css, re.M)
    assert m, selector
    return m.group(1)


def test_the_viewer_has_a_layer_that_is_the_pictures_box():
    assert '<div class="u16-layer"></div>' in VIEW and "view.layer = $('.u16-layer')" in VIEW
    stage = _rule(MAIN_CSS, ".u16-stage")
    assert "justify-self: start" in stage, "the stage shrinks to the canvas, not to the host"
    layer = _rule(MAIN_CSS, ".u16-layer")
    assert "inset: 0" in layer and "pointer-events: none" in layer
    # The border stays on the canvas for every other host (the tiles take it
    # off there); the pane that marks the layer moves it onto the stage.
    assert "border: 1px solid var(--border)" in _rule(MAIN_CSS, ".u16-c")
    assert "border: 1px solid var(--border)" in _rule(REVIEW_CSS, ".th-img .u16-stage")
    assert "border: 0" in _rule(REVIEW_CSS, ".th-img .u16-c")


def test_the_pins_are_drawn_on_the_layer_in_fractions_of_the_frame():
    template = TOOL[TOOL.index("render() {") : TOOL.index("scrub() {")]
    assert "th-pin" not in template, "no pins beside the viewer"
    draw = TOOL[TOOL.index("drawPins() {") :][:700]
    assert "this.view.layer.innerHTML" in draw and "left:${r.x * 100}%;top:${r.y * 100}%" in draw
    wire = TOOL[TOOL.index("wire() {") :][:1600]
    assert "this.drawPins();" in wire
    # A click is a fraction of the canvas — the picture — and the bar is not it.
    assert "if (!c || ev.target !== c) return;" in wire
    assert "showFrame(" not in wire, "scrub() shows the frame; a second load per redraw was wasted"
    # The contrast a person set survives the redraw a saved mark causes.
    assert "this.range = [this.view.lo, this.view.hi, this.view.gamma]" in TOOL
    pane = _rule(REVIEW_CSS, ".th-img .u16-c")
    assert "width: 100%" not in pane and "object-fit" not in pane, "no letterbox under the cap"


def test_the_overlay_closes_on_a_click_anywhere_off_the_picture():
    overlay = VIEW[VIEW.index("overlay(url, title) {") :]
    assert "t.closest('.u16-c, .u16-bar, .u16-overlay-title, .u16-overlay-close')" in overlay
    assert "if (pressedOutside && !keeps(e.target)) close();" in overlay
    assert "if (e.target === o) close();" not in overlay, "the margin alone is not 'outside'"
    assert "u16-overlay-hint" in overlay and 'title="Close (Esc)"' in overlay
    close = _rule(MAIN_CSS, ".u16-overlay-close")
    assert "border-radius: 50%" in close and "background: rgba(255,255,255" in close
