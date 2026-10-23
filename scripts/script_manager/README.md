# Script Manager

One CLI for every registered script. It sets the working directory, `PYTHONPATH`, and environment, then runs the entry in [`registry.json`](registry.json). Menus for leadgen, opp finder, and the video tools live in `menus/`.

**Inputs:** a registry script name and that script's arguments. **Outputs:** the child process stdout/stderr, plus a run summary. Sinks (artifact, dashboard, property portal, callback, email) are optional and named in the registry.

**Local run** from the repo root:

```bash
python -m scripts.script_manager list
python -m scripts.script_manager validate
python -m scripts.script_manager menu
python -m scripts.script_manager run leadgen -- --defaults
```

**Actions:** [`.github/workflows/script_manager.yml`](../../.github/workflows/script_manager.yml) dispatches `run`. [script_manager_schedule.yml](../../.github/workflows/script_manager_schedule.yml) starts saved schedules. Secrets are the ones declared on each script, supplied as Actions secrets. `ci-ping` is the read-only probe.

Longer guides: [script manager](../../documentation/scripts/script_manager.md), [Actions](../../documentation/scripts/script_manager_actions.md).
