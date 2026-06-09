# Blog Automation

**Source:** `scripts/chikara_realms/blog_automation.py`

## Purpose

Automates the Chikara Realms blog pipeline: loads categories, picks or generates topics with GPT-4, writes SEO articles with Perplexity (`sonar-pro`), generates DALL·E 3 thumbnails, and publishes posts to Supabase via the `manage-blog` endpoint.

## Prerequisites

- Python 3.12+
- Dependencies from `requirements/requirements.txt` (`openai`, `perplexityai`, `httpx`, etc.)
- API keys in repo-root `.env`:
  - `CHATGPT_API_KEY`
  - `PERPLEXITY_API_KEY`
  - `CHIKARA_REALMS_SECRET`

## Configuration

| File | Description |
|------|-------------|
| `blog_category.json` | Parent categories and sub-category lists |
| `{category}_topics.json` | Topic queue per sub-category (e.g. `discipline_topics.json`) |
| `img_prompt.txt` | Base prompt prepended to DALL·E image subject |

All config files live in `scripts/chikara_realms/` and are read with relative paths.

## How to run

```bash
cd scripts/chikara_realms
python blog_automation.py
```

No CLI arguments. The script runs the full pipeline for every sub-category in `blog_category.json`.

## How it works

1. Load sub-categories from `blog_category.json`.
2. For each sub-category, call `topic_gen()`:
   - If `{category}_topics.json` is empty or missing, GPT-4 generates 60 titles and saves the remainder.
   - Otherwise, pop the next topic from the queue and save the file.
3. Perplexity writes a 1000+ word markdown article for the topic.
4. DALL·E 3 generates a featured image using `img_prompt.txt` plus a category/topic subject.
5. `APIManager.build_request()` POSTs the post to Supabase (`/manage-blog`) with `CHIKARA_REALMS_SECRET`.

## Related scripts

- [api_manager.md](../helper_scripts/api_manager.md) — HTTP and API key handling
- [logger.md](../helper_scripts/logger.md) — logging
