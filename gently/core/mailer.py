"""Mail from Gently, through an account somebody has set up for it.

    python -m gently.core.mailer --to someone@example.org --subject "..." \\
        --body "..." --attach docs/guide/Gently-two-view-imaging-guide.pdf

The rig's network lets authenticated submission out (ports 587 and 465) and
blocks port 25, so Gently cannot deliver mail itself: it hands each message to
a mail account's own server. Which account is the lab's to choose and is read
from the environment, never from a file in the repository:

    GENTLY_SMTP_HOST       e.g. smtp.gmail.com
    GENTLY_SMTP_PORT       587 (STARTTLS, the default) or 465 (TLS from the start)
    GENTLY_SMTP_USER       the account
    GENTLY_SMTP_PASSWORD   its password, or an app password
    GENTLY_MAIL_FROM       the From address; the account, when not given

shortcut: one message, sent while the caller waits, no queue and no retry;
give it a queue when a run sends mail from its own loop.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import smtplib
import ssl
from collections.abc import Iterable, Mapping
from email.message import EmailMessage
from pathlib import Path

SENT_WITHIN_S = 30.0


class MailNotConfigured(RuntimeError):
    """No account has been set up for Gently to send through."""


def _account(env: Mapping[str, str]) -> dict[str, str]:
    need = ("GENTLY_SMTP_HOST", "GENTLY_SMTP_USER", "GENTLY_SMTP_PASSWORD")
    missing = [k for k in need if not env.get(k)]
    if missing:
        raise MailNotConfigured(
            "Gently has no mail account to send through: set " + ", ".join(missing)
        )
    return {
        "host": env["GENTLY_SMTP_HOST"],
        "port": env.get("GENTLY_SMTP_PORT") or "587",
        "user": env["GENTLY_SMTP_USER"],
        "password": env["GENTLY_SMTP_PASSWORD"],
        "sender": env.get("GENTLY_MAIL_FROM") or env["GENTLY_SMTP_USER"],
    }


def build(
    sender: str,
    to: Iterable[str],
    subject: str,
    body: str,
    attachments: Iterable[Path | str] = (),
) -> EmailMessage:
    """The message, with each file attached under its own name and type."""
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    for item in attachments:
        path = Path(item)
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        main, _, sub = kind.partition("/")
        msg.add_attachment(path.read_bytes(), maintype=main, subtype=sub, filename=path.name)
    return msg


def send(
    to: Iterable[str],
    subject: str,
    body: str,
    attachments: Iterable[Path | str] = (),
    *,
    env: Mapping[str, str] | None = None,
) -> None:
    """Send one message. Raises MailNotConfigured with no account, and
    whatever the mail server says when it refuses."""
    account = _account(os.environ if env is None else env)
    msg = build(account["sender"], list(to), subject, body, attachments)
    port = int(account["port"])
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(
            account["host"], port, timeout=SENT_WITHIN_S, context=context
        ) as server:
            server.login(account["user"], account["password"])
            server.send_message(msg)
        return
    with smtplib.SMTP(account["host"], port, timeout=SENT_WITHIN_S) as server:
        server.starttls(context=context)
        server.login(account["user"], account["password"])
        server.send_message(msg)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Send one message from Gently's mail account.")
    p.add_argument("--to", action="append", required=True, help="a recipient; repeat for more")
    p.add_argument("--subject", required=True)
    p.add_argument("--body", default="")
    p.add_argument("--attach", action="append", default=[], help="a file to attach; repeat")
    a = p.parse_args(argv)
    try:
        send(a.to, a.subject, a.body, a.attach)
    except MailNotConfigured as exc:
        print(exc)
        return 2
    print(f"sent to {', '.join(a.to)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
