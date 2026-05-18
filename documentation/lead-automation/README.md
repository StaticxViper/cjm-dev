# Lead automation

Step-by-step guides for generating local business leads and syncing them to the leads-ingest API.

## Guides

| Guide | Use when |
|-------|----------|
| [Setup](setup.md) | First-time configuration (env vars, folder, config files) |
| [Pipeline A: Add new leads](pipeline-a-add-leads.md) | Scrape → filter → dedupe → batch create leads in the API |
| [Pipeline B: Update existing leads](pipeline-b-update-leads.md) | Match API leads to a CSV and push field updates |
| [Reference](reference.md) | What each script/file does, tuning, tests, troubleshooting |

## Quick commands

Run all commands from `scripts/lead_automation/`:

```powershell
cd E:\REPOS\cjm-dev\scripts\lead_automation
```

**Pipeline A (add)**

```powershell
python leadgen.py --group <pipeline-group-name>
python lead_automation.py add
```

**Pipeline B (update)**

```powershell
python lead_automation.py update --group <pipeline-group-name>
```

## Flow overview

```
Pipeline A (add)
  leadgen.py --group  →  leads_output.csv
  lead_automation.py add  →  score filter → GET API → dedupe → batch POST

Pipeline B (update)
  leads_output.csv (or other CSV)
  lead_automation.py update [--group]  →  GET API → match CSV → POST each lead
```
