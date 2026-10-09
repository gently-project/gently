"""Every card on the Bottom cam rail folds to its head row.

Ryan, 2026-10-09, after the Overview frames block got a Show button: "show
button also needed on bottom focus, led, stage etc." One rule for all of
them (operate.js wireDisclosures): `data-disclose` names the card, the head
row and `.op-disc-keep` stay, the other direct children fold, and the choice
is remembered per card. CI runs no browser, so the markup and the wiring are
pinned as source.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
HTML = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
LIGHT = (WEB / "static" / "js" / "panels" / "light.js").read_text(encoding="utf-8")
CSS = (WEB / "static" / "css" / "operate.css").read_text(encoding="utf-8")

RAIL = HTML[HTML.index('<aside class="op-inst">') : HTML.index('id="op-pane-spim"')]


def test_every_card_on_the_rail_folds():
    cards = re.findall(r'data-disclose="([a-z]+)"', RAIL)
    assert cards == ["camera", "stage", "led", "focus", "overview", "advanced"], cards
    # Each has its toggle in a head row that stays.
    for key in cards:
        block = RAIL[RAIL.index(f'data-disclose="{key}"') :]
        head = block[: block.index("data-disclose-toggle")]
        assert 'class="op-disc-head"' in head or 'class="op-gauge-head"' in head, key


def test_the_verb_this_pane_cannot_do_without_stays_out_when_folded():
    assert 'class="op-btn op-btn-toggle op-disc-keep" id="op-cam-toggle"' in RAIL
    assert 'class="op-cap op-disc-keep" id="op-ov-summary"' in RAIL


def test_one_rule_wired_once_and_remembered():
    wire = OPERATE[OPERATE.index("if (_wired) return;") :]
    wire = wire[: wire.index("\n    async function ")]
    assert "wireDisclosures();" in wire
    fn = OPERATE[OPERATE.index("function wireDisclosures()") :]
    fn = fn[: fn.index("\n    }")]
    assert "'#op-pane-bottom [data-disclose]'" in fn
    assert "localStorage.setItem(DISCLOSE_KEY + key" in fn
    assert (
        "const DISCLOSE_DEFAULT = { camera: true, stage: true, led: true, focus: true, "
        "overview: false, advanced: false };"
    ) in OPERATE


def test_the_head_row_and_the_kept_children_stay():
    fn = OPERATE[OPERATE.index("function applyDisclosure(block, open)") :]
    fn = fn[: fn.index("\n    }")]
    assert "':scope > .op-disc-head, :scope > .op-gauge-head'" in fn
    assert "ch.classList.contains('op-disc-keep')" in fn


def test_the_led_card_draws_the_heading_and_the_panel_is_mounted_untitled():
    assert "LightPanel.mount('op-led-host', { only: 'led', titled: false })" in OPERATE
    assert "function ledCard(s, titled)" in LIGHT
    assert "titled === false ? '<span></span>' : '<span class=\"lp-title\">LED</span>'" in LIGHT


def test_hidden_actually_hides_the_folded_body():
    """`[hidden]` is specificity 0,1,0; a class rule that sets display beats it."""
    assert re.search(r"\.op-disc-body\s*\{[^}]*display:", CSS)
    assert ".op-disc-body[hidden] { display: none; }" in CSS
