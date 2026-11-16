"""Gently sends mail through an account set up for it, and says when there is none."""

from pathlib import Path
from typing import Any

import pytest

from gently.core import mailer

ACCOUNT = {
    "GENTLY_SMTP_HOST": "smtp.example.org",
    "GENTLY_SMTP_USER": "gently@example.org",
    "GENTLY_SMTP_PASSWORD": "app-password",
}


class _Server:
    """Stands in for smtplib.SMTP: records what it was asked to do."""

    seen: list[Any] = []

    def __init__(self, host: str, port: int, **_: Any) -> None:
        _Server.seen = [("connect", host, port)]

    def __enter__(self) -> "_Server":
        return self

    def __exit__(self, *_: Any) -> None:
        _Server.seen.append(("quit",))

    def starttls(self, **_: Any) -> None:
        _Server.seen.append(("starttls",))

    def login(self, user: str, password: str) -> None:
        _Server.seen.append(("login", user, password))

    def send_message(self, msg: Any) -> None:
        _Server.seen.append(("send", msg))


def test_with_no_account_it_says_which_settings_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(mailer.MailNotConfigured) as said:
        mailer.send(["someone@example.org"], "hello", "body", env={})
    assert "GENTLY_SMTP_HOST" in str(said.value) and "GENTLY_SMTP_PASSWORD" in str(said.value)
    # And the command says so and fails, rather than tracing back. With the
    # machine's own account taken out of reach: a test never sends mail.
    for key in ACCOUNT:
        monkeypatch.delenv(key, raising=False)
    assert mailer.main(["--to", "someone@example.org", "--subject", "x"]) == 2


def test_a_message_is_encrypted_then_logged_in_then_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mailer.smtplib, "SMTP", _Server)
    guide = tmp_path / "guide.pdf"
    guide.write_bytes(b"%PDF-1.4 not really")
    mailer.send(["a@example.org", "b@example.org"], "The guide", "Attached.", [guide], env=ACCOUNT)
    steps = [s[0] for s in _Server.seen]
    assert steps == ["connect", "starttls", "login", "send", "quit"]
    assert _Server.seen[0][1:] == ("smtp.example.org", 587)
    msg = _Server.seen[3][1]
    assert msg["From"] == "gently@example.org"
    assert msg["To"] == "a@example.org, b@example.org"
    (attached,) = list(msg.iter_attachments())
    assert attached.get_filename() == "guide.pdf"
    assert attached.get_content_type() == "application/pdf"
    assert attached.get_content() == b"%PDF-1.4 not really"


def test_port_465_is_tls_from_the_first_byte(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", _Server)
    mailer.send(["a@example.org"], "s", "b", env={**ACCOUNT, "GENTLY_SMTP_PORT": "465"})
    assert [s[0] for s in _Server.seen] == ["connect", "login", "send", "quit"]
    assert _Server.seen[0][2] == 465
