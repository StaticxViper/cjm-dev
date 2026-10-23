# Chikara Realms

Publishes posts for the Chikara Realms blog. `blog_automation.py` loads categories, drafts a topic, writes an article, generates a thumbnail, and sends the post to the `manage-blog` endpoint.

**Inputs:** category and topic files in this folder, plus the prompts in the script. **Outputs:** a published blog post (no local article file).

**Local run** from this directory:

```bash
python blog_automation.py
```

**Script Manager:** `blog-automation` (registry status broken). `python -m scripts.script_manager run blog-automation` from the repo root. There is no dedicated GitHub Actions workflow.

**Secrets:** `CHATGPT_API_KEY`, `PERPLEXITY_API_KEY`, `CHIKARA_REALMS_SECRET`. Optional `MVLLC_LOGS_KEY` for log upload.

Longer guide: [documentation/scripts/blog_automation.md](../../documentation/scripts/blog_automation.md).
