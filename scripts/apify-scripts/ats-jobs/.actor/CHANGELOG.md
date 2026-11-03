# Changelog

## 0.1

- Read Greenhouse, Lever (global and EU), Ashby, and Workable public job-board APIs for a list of company slugs. Endpoints checked live on 2026-11-02.
- One row per job with salary (structured when the ATS publishes it, plus raw text), remote flag, department, posted date, and firstSeen.
- Location, remote, and keyword filters. Dedupe on (ats, company slug, job id). `newSinceLastRun` keeps seen jobs in a named key-value store.
- Charge `job` only for a pushed job row. Direct HTTP only. No proxy, no CAPTCHA solver, no browser. A block pushes one `blocked` row and stops.
