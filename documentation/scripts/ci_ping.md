# ci-ping

Read-only probe for the Script Manager on GitHub Actions. It prints one JSON object and does not read secrets, call the network, or write files.

```bash
python -m scripts.script_manager run ci-ping -- --example
```

Stdout:

```json
{"ok": true, "script": "ci-ping", "args": ["--example"]}
```

`ci-ping` is `ci_allowed` and has no `side_effects`, so a workflow run does not need `confirm=true`. The run summary puts that object in `data`.
