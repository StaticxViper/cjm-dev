# Lovable automation

Creates a Lovable project from a prompt, waits for the build, can ask chat to remove the Lovable badge, publishes, and prints a share link. It stops when workspace credits fall below the threshold.

**Inputs:** a project prompt (CLI or prompt file in this folder). **Outputs:** the published share URL on stdout. The script does not write a local site.

**Local run** from this directory:

```bash
python lovable_automation.py
```

**Script Manager:** `lovable-automation` (registry status broken). No dedicated GitHub Actions workflow.

**Secrets:** `LOVABLE_API_KEY`. Optional `LOVABLE_WORKSPACE_ID` and `LOVABLE_CREDIT_THRESHOLD` (default `5`).

Longer guide: [documentation/scripts/lovable_automation.md](../../documentation/scripts/lovable_automation.md).
