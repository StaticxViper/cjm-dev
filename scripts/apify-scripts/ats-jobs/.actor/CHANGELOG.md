# Changelog

## Unreleased

- Store README rewritten for buyers: who it is for, field table, sample row, cost for 100 and 1,000 results, limits, and FAQ. Listing description updated.

## 0.1

- Read Greenhouse, Lever (global and EU), Ashby, and Workable public job-board APIs for a list of company slugs. Endpoints checked live on 2026-11-02.
- One row per job with salary (structured when the ATS publishes it, plus raw text), remote flag, department, posted date, and firstSeen.
- Location, remote, and keyword filters. Dedupe on (ats, company slug, job id). `newSinceLastRun` keeps seen jobs in a named key-value store.
- Charge `job` for every pushed job row. A job row is pushed only when its charge fits under `maxSpendUsd` (minimum 0.01) and the platform limit; otherwise the feed stops with one free `spend_capped` row.
- `newSinceLastRun` records only jobs that were pushed and charged.
- Keywords match whole words. A `Remote` location also matches jobs the ATS flags as remote.
- Direct HTTP only. No proxy, no CAPTCHA solver, no browser. A block pushes one `blocked` row and skips the rest of that host's boards; other hosts still run.
