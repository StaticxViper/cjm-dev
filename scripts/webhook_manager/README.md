# Webhook manager

Posts an email-oriented JSON payload to a Make.com webhook so an external scenario can send mail. This repo does not open an SMTP session here.

**Inputs:** the payload built by `WebhookManager` (a sample payload is used for the test send). **Outputs:** the HTTP response from the webhook. No local file.

**Local run** from this directory:

```bash
python webhook_manager.py
```

**Script Manager:** `webhook-manager` (registry status broken). No GitHub Actions workflow.

**Secrets:** none. The default webhook URL is hardcoded. Pass `WebhookManager(url=...)` to override it.

Longer guide: [documentation/scripts/webhook_manager.md](../../documentation/scripts/webhook_manager.md).
