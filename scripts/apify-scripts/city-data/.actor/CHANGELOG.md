# Changelog

## 0.2

- Dataset fields include population, income, housing, cost of living, education, and crime, with a Detail view.
- Field groups are a multi-select.
- Pay per event: $0.01 for a fetched city profile. Default timeout is 600 seconds.
- Page-fetch progress is logged at CRITICAL.

## 0.1

- First marketplace draft. Wraps the Playwright city-data scraper (issue #99).
- Checks city-data robots.txt before each city or crime URL.
