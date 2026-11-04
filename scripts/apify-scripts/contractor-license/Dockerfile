# Build context is this Actor folder. The repo modules it imports are copied
# into platform_bundle/ by ../actor_build.py bundle; CI fails if they drift.
# The image is the shared Playwright base. This Actor is HTTP only.
FROM apify/actor-python-playwright:3.12

# The base image ENTRYPOINT is ./xvfb-entrypoint.sh and its WORKDIR is /usr/src/app.
# A different WORKDIR makes that relative entrypoint exit 127.
USER myuser

COPY --chown=myuser:myuser requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --user -r requirements.txt

COPY --chown=myuser:myuser . ./

ENV CJM_REPO_ROOT=/usr/src/app/platform_bundle
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
