# Email manager

SMTP library for plain-text, HTML, and attachment messages. It has no CLI and no Script Manager entry.

**Inputs:** SMTP host, port, credentials, and message fields passed by the caller. **Outputs:** the message handed to the SMTP server. Nothing is written in this folder.

**Local run:** import it. Do not execute the module.

```python
from scripts.email_manager.email_manager import build_email, send_email
```

**Actions:** none.

**Secrets:** none in this package. Callers supply SMTP credentials at call time.

Longer guide: [documentation/scripts/email_manager.md](../../documentation/scripts/email_manager.md).
