# Build context is this Actor folder. The repo modules it imports are copied
# into platform_bundle/ by ../actor_build.py bundle; CI fails if they drift.
# The image is the shared Playwright base. Permit feeds are HTTP only and do not launch Chromium.
FROM apify/actor-python-playwright:3.12

USER myuser
WORKDIR /home/myuser

COPY --chown=myuser:myuser requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --user -r requirements.txt

COPY --chown=myuser:myuser . ./

ENV CJM_REPO_ROOT=/home/myuser/platform_bundle
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
