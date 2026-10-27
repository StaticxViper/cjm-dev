# Changelog

## 0.3

- A Maps block retries once through Apify Proxy when maxSpendUsd and maxProxyCostUsd still have room. CAPTCHA solving stays off unless allowCaptcha is true and the cap covers a solve.
- Pay per event adds proxy ($0.01) and captcha ($1.00). Result stays the accepted-match charge.

## 0.2

- A candidate has to share every brand token and the query city. A different business is omitted. A short Maps title that passed that check is scored as the query name, and the row still shows the Maps title.
- A Maps search that opens a place page uses that page's heading.
- Dataset Detail view includes the query, score breakdown, hard rejects, and candidate.
- Input example is Wegmans Food Markets, Rochester, NY.
- Pay per event: $0.05 for an accepted match. Default timeout is 900 seconds.

## 0.1

- First marketplace draft. Google Maps search and place pages only.
- Name and location scoring from issue #127. No first-result fallback.
- Block pages stop the run. Web search (`/search`) is not requested.
