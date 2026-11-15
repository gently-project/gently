"""The embryo list can send the stage to the embryo, from any pane.

The SPIM head already knew when it was pointed at the wrong place — the
caption reads "Selected: embryo 3 — stage is elsewhere" and the frame is
blanked to "Not at this embryo" rather than showing the previous embryo's
pixels. What it did not have was a way to fix it. "Centre the stage on this
embryo" existed only on the Acquisition pane's roster and on the bottom-camera
image, so from the SPIM head the operator had to leave the pane, act
elsewhere, and come back.

The rail is the embryo list beside EVERY pane, so the verb belongs there. It
draws as a crosshair rather than the word: the rail is ~168px and a
word-width button wrapped "Embryo 1  −184, −585" onto three lines.

CI runs no JavaScript, so the wiring is pinned in source.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
OPERATE_JS = WEB / "static" / "js" / "operate.js"
ROSTER_JS = WEB / "static" / "js" / "panels" / "roster.js"


def test_the_rail_offers_centre_on_every_pane() -> None:
    js = OPERATE_JS.read_text(encoding="utf-8")
    mount = re.search(r"RosterPanel\.mount\('op-erail-list',\s*\{([^}]*)\}", js, re.S)
    assert mount, "the rail no longer mounts the roster"
    opts = mount.group(1)
    assert "'centre'" in opts, (
        "the rail lost its centre verb — the SPIM head is back to reporting "
        "'stage is elsewhere' with no way to act on it"
    )
    assert "compact: true" in opts, "the rail's verbs are no longer compact; rows will wrap"


def test_centre_moves_through_the_one_chokepoint() -> None:
    """Centring is a stage move and must keep its interlock."""
    js = OPERATE_JS.read_text(encoding="utf-8")
    centre = re.search(r"async function centerOnEmbryo\(emb\) \{(.*?)\n    \}", js, re.S)
    assert centre, "centerOnEmbryo is gone"
    assert "moveStageTo(" in centre.group(1), (
        "centring no longer routes through moveStageTo, the only caller of the "
        "stage-move route and the whole XY/F-drive guard"
    )


def test_a_glyph_verb_still_says_what_it_is() -> None:
    """Icon-only buttons carry their label for screen readers and tooltips."""
    js = ROSTER_JS.read_text(encoding="utf-8")
    assert 'aria-label="${a.title}"' in js, (
        "roster action buttons lost their aria-label; compact ones render as a "
        "bare glyph with no accessible name"
    )
    assert "opts.compact && a.icon" in js, "the compact rendering is gone"
    # The wide mount keeps words: Acquisition is the pre-run review surface.
    acq = re.search(
        r"RosterPanel\.mount\('op-roster',\s*\n?\s*\{([^}]*)\}",
        OPERATE_JS.read_text(encoding="utf-8"),
        re.S,
    )
    assert acq and "compact" not in acq.group(1), (
        "the Acquisition roster went compact; it has the width for words"
    )


def test_a_live_view_away_from_the_embryo_is_shown_and_says_what_it_is():
    """ "the not at the embryo is blocking on spim a and spim b camera operation
    at times ... we cannot always be so anal about being in the embryo detected
    position". The picture was withheld whenever the stage was not on the
    selected embryo. It is shown, and the line under it says where it is."""
    from pathlib import Path

    js = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "static" / "js"
    operate = (js / "operate.js").read_text(encoding="utf-8")
    frame = operate[operate.index("    function onSpimFrame(p) {") :]
    frame = frame[: frame.index("    function onEmbryosUpdate(p) {")]
    assert "atSelected()" not in frame and "clearImg(" not in frame
    target = operate[operate.index("    function renderSpimTarget() {") :][:1900]
    assert "µm from embryo ${labelFor(emb)}" in target
    assert "el.classList.toggle('is-elsewhere', !!emb && !here);" in target
    # Only a picture left over from before is taken down: one nothing is replacing.
    assert "if (!here && !_spimOn) clearImg(" in target
    assert "'Not at this embryo'" not in operate
