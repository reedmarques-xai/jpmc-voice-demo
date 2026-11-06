"""Renders the deposit recap email and sends it through Resend.

Sends for real only when RESEND_API_KEY is set. Without it, send() returns a
preview so the call still works and the email shows up in GET /state.
"""

import html
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

RESEND_URL = "https://api.resend.com/emails"
DEFAULT_SENDER = "Merchant Services <onboarding@resend.dev>"
TIMEOUT_SECONDS = 10

SPOKEN_SYMBOLS = {".": "dot", "_": "underscore", "-": "dash", "+": "plus"}
SPOKEN_AS_WORDS = {"com", "net", "org", "edu", "gov", "io", "co", "us", "example"}


class MailError(Exception):
    pass


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    html: str


def _spell(part: str) -> str:
    words, letters = [], []
    for ch in part:
        if ch.isalnum():
            letters.append(ch.lower())
            continue
        if letters:
            words.append("-".join(letters))
            letters = []
        words.append(SPOKEN_SYMBOLS.get(ch, ch))
    if letters:
        words.append("-".join(letters))
    return " ".join(words)


def spoken_email(address: str) -> str:
    """'r.marques@x.ai' -> 'r dot m-a-r-q-u-e-s at x dot a-i'. Common endings like 'com' stay words."""
    local, _, domain = address.strip().partition("@")
    labels = domain.split(".")
    spoken_domain = " dot ".join(
        label.lower() if i == len(labels) - 1 and label.lower() in SPOKEN_AS_WORDS else _spell(label)
        for i, label in enumerate(labels)
    )
    return f"{_spell(local)} at {spoken_domain}"


def render(to: str, subject: str, greeting: str, sections: list[tuple[str, list[str]]], footer: str) -> Email:
    text_parts = [greeting, ""]
    html_parts = [f"<p>{html.escape(greeting)}</p>"]
    for heading, lines in sections:
        text_parts += [heading, *(f"- {line}" for line in lines), ""]
        html_parts.append(f"<h3 style=\"margin:16px 0 4px\">{html.escape(heading)}</h3>")
        html_parts.append("<ul>" + "".join(f"<li>{html.escape(line)}</li>" for line in lines) + "</ul>")
    text_parts.append(footer)
    html_parts.append(f"<p style=\"color:#666;font-size:12px\">{html.escape(footer)}</p>")
    body = "<div style=\"font-family:Arial,sans-serif;font-size:14px;color:#222\">" + "".join(html_parts) + "</div>"
    return Email(to=to, subject=subject, text="\n".join(text_parts), html=body)


def send(email: Email) -> dict[str, str]:
    """Returns {"delivery": "resend", "id": ...} or {"delivery": "preview"}. Raises MailError on failure."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        return {"delivery": "preview"}
    payload = {
        "from": os.environ.get("RECAP_EMAIL_FROM") or DEFAULT_SENDER,
        "to": [email.to],
        "subject": email.subject,
        "text": email.text,
        "html": email.html,
    }
    request = urllib.request.Request(
        RESEND_URL,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Resend's edge rejects urllib's default User-Agent.
            "User-Agent": "chase-mock-backend/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise MailError(f"Resend returned {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise MailError(f"Couldn't reach Resend: {exc}")
    return {"delivery": "resend", "id": str(body.get("id", ""))}
