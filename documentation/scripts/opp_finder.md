# Job Automation Opportunity Finder

CLI Playwright research tool under [`scripts/opp_finder/`](../../scripts/opp_finder/).

Finds multi-location (South Jersey, Philly metro, Delaware, North Jersey) and remote U.S. jobs with potentially automatable repetitive digital workflows. Remote roles are prioritized by default. Scores leads, researches public business contacts, drafts outreach, and writes CSV output.

Full usage guide: [`scripts/opp_finder/README.md`](../../scripts/opp_finder/README.md)

## Quick start

```bash
cd scripts/opp_finder
python main.py search --limit 100
# or narrow regions:
python main.py search --locations south_jersey,philadelphia_metro --limit 100
```

Outputs:

- `output/all_jobs.csv`
- `output/qualified_opportunities.csv`
- `output/search_history.csv`

API-callable GitHub Action: [`.github/workflows/opp_finder.yml`](../../.github/workflows/opp_finder.yml)  
(see the “GitHub Action” section in [`scripts/opp_finder/README.md`](../../scripts/opp_finder/README.md)).
