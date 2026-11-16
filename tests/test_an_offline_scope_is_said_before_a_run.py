"""Before a run starts, a microscope that is offline is the thing in the way."""

from pathlib import Path

OPERATE = (
    Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "static" / "js" / "operate.js"
).read_text(encoding="utf-8")


def test_the_lines_before_a_run_say_the_microscope_is_offline() -> None:
    ctx = OPERATE[OPERATE.index("    function preflightContext(plan) {") :]
    ctx = ctx[: ctx.index("    function patchLines(")]
    assert "if (scopeOffline()) {" in ctx
    assert "problems.unshift('The microscope is offline:" in ctx
    # It takes the place of the advice to go and detect embryos, which an
    # unread list gave whether or not there were any.
    assert "problems.filter(q => !/^No embryos yet/.test(q));" in ctx
    # Offline is the header's own reading, and unread is not offline.
    assert "ConnectionStatus.get().microscopeConnected === false" in OPERATE
    # And the lines follow the connection as it changes.
    assert "ClientEventBus.on('CONNECTION_STATUS'," in OPERATE


def test_a_two_view_plan_is_judged_on_both_sides_fits() -> None:
    ctx = OPERATE[OPERATE.index("    function preflightContext(plan) {") :]
    ctx = ctx[: ctx.index("    function patchLines(")]
    # Every side the plan images has to have a fit, and the fit that is
    # reported is the weakest of them.
    # The rule itself is tested in tests/js/operate-math.test.mjs.
    assert "const missing = M.sidesWithoutFit(e, sides);" in ctx
    assert "Math.min(...sides.map(side => fitScore({ calibration: M.sideFit(e, side) })))" in ctx
    # And the ways past the line are judged the same way, not on side A alone.
    fix = OPERATE[OPERATE.index("    function preflightFix(action) {") :]
    fix = fix[: fix.index("action === 'head'")]
    assert "const fitted = e => !M.sidesWithoutFit(e, sides).length;" in fix
    assert "hasFit" not in fix


def test_a_walk_of_several_embryos_shows_its_steps() -> None:
    walk = OPERATE[OPERATE.index("    async function calibrateAll(") :]
    walk = walk[: walk.index("CalProgressPanel.begin(null);")]
    assert "if (_pane !== 'cal') showPane('cal');" in walk
