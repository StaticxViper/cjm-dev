# Changelog

## 0.1

- Package verified Chicago, Seattle, Austin, and Los Angeles building-permit feeds as an Actor.
- Charge `permit` only when a permit row is pushed. Direct requests are free.
- Apify Proxy only after a block. CAPTCHA only when that retry is still a challenge, `allowCaptcha` is true, and the spend cap covers the solve.
