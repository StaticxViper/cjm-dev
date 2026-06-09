# Webhook Manager

**Source:** `scripts/webhook_manager/webhook_manager.py`

## Purpose

Sends email-oriented payloads to a Make.com webhook URL. Used to trigger external automation (e.g. outbound email workflows) without direct SMTP from this repo.

## Prerequisites

- Python 3.12+
- `requests`

No environment variables required. Default webhook URL is hardcoded in the class; override via constructor.

## Configuration

None. Optional custom URL passed to `WebhookManager(url=...)`.

## How to run

**Test send** (uses built-in sample payload):

```bash
cd scripts/webhook_manager
python webhook_manager.py
```

**Programmatic use:**

```python
from scripts.webhook_manager.webhook_manager import WebhookManager

payload = {
    "business_name": "Example Co",
    "email": "contact@example.com",
    "subject": "Quick question",
    "message": "Hello...",
}
WebhookManager().send_email(payload)
```

## How it works

1. `WebhookManager.__init__` sets the webhook URL (default or custom).
2. `send_email(payload)` POSTs JSON to the webhook via `requests`.
3. Logs the HTTP status code.

## Related scripts

- [email_manager.md](email_manager.md) — SMTP helpers (imported but not used by the webhook path)
