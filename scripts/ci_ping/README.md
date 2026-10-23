# ci-ping

Read-only probe for the Script Manager. It prints one JSON object and does not read secrets, call the network, or write files.

**Inputs:** optional positional arguments, echoed in the payload. **Outputs:** stdout JSON `{"ok": true, "script": "ci-ping", "args": [...]}`.

**Local run** from the repo root:

```bash
python scripts/ci_ping/ci_ping.py --example
python -m scripts.script_manager run ci-ping -- --example
```

**Script Manager / Actions:** registry name `ci-ping`. [`.github/workflows/script_manager.yml`](../../.github/workflows/script_manager.yml) can dispatch it. No `confirm` is required because the script has no side effects.

**Secrets:** none.

Longer guide: [documentation/scripts/ci_ping.md](../../documentation/scripts/ci_ping.md).
