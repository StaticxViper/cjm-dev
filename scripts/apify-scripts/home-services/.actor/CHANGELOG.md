# Changelog

## Unreleased

- Store README rewritten for buyers: who it is for, field table, sample row, cost for 100 and 1,000 results, limits, and FAQ. Listing description updated. Title is now "Home Services Leads – Local Contractor Leads with Emails".

## 0.1

- Home-services lead enricher. Niche and area, or an upstream Maps dataset.
- Match rules from issue #127 via the google-business scorer. No first-card fallback.
- Pay per event: place, email-found, and score. Empty, failed, and rejected rows are not billed.
- Block pages stop the run. Google web search and the Places API are not requested.
