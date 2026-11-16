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
