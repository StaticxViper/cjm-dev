# Changelog

## 0.2

- California license numbers and business names use the CSLB Check a License form. The statewide master file is not downloaded for those lookups.
- A trade-only search still reads the master file, streamed, and stops at the result cap.

## 0.1

- California CSLB master file lookup.
- Arizona ROC posting-list parser. A Cloudflare challenge stops the run.
- New Jersey DCA and Pennsylvania HIC stop with unsupported or captcha. No form submit and no CAPTCHA solving.
