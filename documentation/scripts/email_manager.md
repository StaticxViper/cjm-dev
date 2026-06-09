# Email Manager

**Source:** `scripts/email_manager/email_manager.py`

## Purpose

SMTP helper library for building and sending multipart emails (plain text, HTML, attachments). Import-only; no CLI entry point.

## Prerequisites

- Python 3.12+ (stdlib: `smtplib`, `email`)

## Configuration

None. Callers pass SMTP host, port, credentials, and message content.

## How to run

Not runnable directly. Example usage:

```python
from scripts.email_manager.email_manager import build_email, send_email

msg = build_email(
    sender="you@example.com",
    recipients=["client@example.com"],
    subject="Hello",
    body_text="Plain text body",
    body_html="<p>HTML body</p>",
    attachments=["/path/to/file.pdf"],
)

send_email(
    smtp_server="smtp.example.com",
    port=587,
    sender="you@example.com",
    password="your-app-password",
    recipients=["client@example.com"],
    message=msg,
)
```

## API

### `build_email(sender, recipients, subject, body_text=None, body_html=None, attachments=None)`

Returns a `MIMEMultipart` message with optional text, HTML, and file attachments.

### `send_email(smtp_server, port, sender, password, recipients, message)`

Connects via STARTTLS, logs in, and sends the message.

## Related scripts

- [webhook_manager.md](webhook_manager.md) — imports this module but uses Make.com webhooks for email in practice
