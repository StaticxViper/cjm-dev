# Build context is this Actor directory. Shared modules are in platform_bundle
# because the platform rejects a context outside the Actor directory.
# Refresh that folder with: python bundle_context.py
FROM apify/actor-python-playwright:3.12

USER myuser

COPY --chown=myuser:myuser requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --user -r requirements.txt

COPY --chown=myuser:myuser src ./src
COPY --chown=myuser:myuser platform_bundle /home/myuser/repo

ENV CJM_REPO_ROOT=/home/myuser/repo
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
