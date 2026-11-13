"""A card that folds, folds to its head row, and the rig keeps the choice.

After the Overview frames block got a Show button, every other card on the
Bottom cam rail wanted one (2026-10-09), and got it: the rail was a 260 px
strip that scrolled, and folding was how it was made to fit. One rule for all
of them (operate.js wireDisclosures): `data-disclose` names the card, the head
row and `.op-disc-keep` stay, the other direct children fold, and the choice
is the rig's, kept as it is pressed.

In the workspace (2026-11-13) the instrument panels have fixed places and all
of them fit, so they no longer fold: a panel that can be folded away is a
panel that is somewhere else the next time. What still folds is what is set
once a night, the Overview frames box in the rail. The rule and the rig-wide
memory are unchanged. CI runs no browser, so the markup and the wiring are
pinned as source.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
HTML = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
CSS = (WEB / "static" / "css" / "operate.css").read_text(encoding="utf-8")

VIEW = HTML[HTML.index('id="devices-view-operate"') : HTML.index('id="devices-view-map"')]
SCOPE = HTML[HTML.index('id="op-pane-scope"') : HTML.index('id="op-pane-acquire"')]
RAIL = HTML[HTML.index('id="op-erail"') : HTML.index('class="op-panearea"')]


def test_what_folds_is_what_is_set_once_a_night():
    cards = re.findall(r'data-disclose="([a-z]+)"', VIEW)
    assert cards == ["overview"], cards
    block = RAIL[RAIL.index('data-disclose="overview"') :]
    head = block[: block.index("data-disclose-toggle")]
    assert 'class="op-disc-head"' in head


def test_the_instrument_panels_do_not_fold():
    """Light, Sheet, Head and Stage are always where they are."""
    assert "data-disclose" not in SCOPE
    for panel in ('id="op-light-host"', 'id="op-sheet"', 'id="op-gauge-fd"', 'id="op-stage-panel"'):
        assert panel in SCOPE, panel


def test_a_folded_card_still_says_what_is_set():
    assert 'class="op-cap op-disc-keep" id="op-ov-summary"' in RAIL


def test_one_rule_wired_once_and_kept_by_the_rig():
    wire = OPERATE[OPERATE.index("if (_wired) return;") :]
    wire = wire[: wire.index("\n    async function ")]
    assert "wireDisclosures();" in wire
    fn = OPERATE[OPERATE.index("function wireDisclosures()") :]
    fn = fn[: fn.index("\n    }")]
    # Any card in the Operate view, wherever it sits: the rail is not inside
    # a pane any more.
    assert "'#devices-view-operate [data-disclose]'" in fn
    every = OPERATE[OPERATE.index("function applyAllDisclosures()") :]
    assert "'#devices-view-operate [data-disclose]'" in every[: every.index("\n    }")]
    # The choice is the rig's (tests/test_rail_cards_rig_wide.py), not this browser's.
    assert "saveRailCard(key, open)" in fn and "localStorage" not in fn
    assert (
        "const DISCLOSE_DEFAULT = { camera: true, stage: true, led: true, focus: true, "
        "overview: false, advanced: false };"
    ) in OPERATE


def test_the_head_row_and_the_kept_children_stay():
    fn = OPERATE[OPERATE.index("function applyDisclosure(block, open)") :]
    fn = fn[: fn.index("\n    }")]
    assert "':scope > .op-disc-head, :scope > .op-gauge-head'" in fn
    assert "ch.classList.contains('op-disc-keep')" in fn


def test_hidden_actually_hides_the_folded_body():
    """`[hidden]` is specificity 0,1,0; a class rule that sets display beats it."""
    assert re.search(r"\.op-disc-body\s*\{[^}]*display:", CSS)
    assert ".op-disc-body[hidden] { display: none; }" in CSS
