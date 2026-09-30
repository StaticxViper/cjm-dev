# Job Automation Opportunity Finder

CLI Playwright research tool under [`scripts/opp_finder/`](../../scripts/opp_finder/).

Finds South NJ and remote U.S. jobs with potentially automatable repetitive digital workflows, scores them, researches public business contacts, drafts outreach, and writes CSV output.

Full usage guide: [`scripts/opp_finder/README.md`](../../scripts/opp_finder/README.md)

## Quick start

```bash
cd scripts/opp_finder
python main.py search --south-nj --limit 100
```

Outputs:

- `output/all_jobs.csv`
- `output/qualified_opportunities.csv`
- `output/search_history.csv`
