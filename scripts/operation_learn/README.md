# Operation Learn

Two personal job-search helpers. They are registered scripts and are not part of opp finder.

`source_recruiters.py` reads `companies.json`, searches public LinkedIn-style profiles through Apify, and writes `output/recruiters_<timestamp>.csv` (name, headline, company, relevance, hiring flag).

`draft_emails.py` reads the newest `output/recruiters_*.csv` and `resume_2026.md`, then writes `output/email_drafts_<timestamp>.md`. It does not send mail.

**Local run** from this directory:

```bash
python source_recruiters.py
python draft_emails.py
```

**Script Manager:** `source-recruiters` and `draft-emails`. No dedicated GitHub Actions workflow. Use `script_manager.yml` to dispatch a registered name.

**Secrets:** `APIFY_API_KEY` for `source_recruiters.py` only. Drafting has no secrets. Optional `MVLLC_LOGS_KEY` on the recruiter search.
