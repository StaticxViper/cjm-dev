# Build context is this Actor folder. The repo modules it imports are copied
# into platform_bundle/ by ../actor_build.py bundle; CI fails if they drift.
# HTTP only. The slim Python base has no browser and no xvfb entrypoint.
# Leave WORKDIR at the image default (/usr/src/app).
FROM apify/actor-python:3.12

USER myuser

COPY --chown=myuser:myuser requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --user -r requirements.txt

COPY --chown=myuser:myuser . ./

ENV CJM_REPO_ROOT=/usr/src/app/platform_bundle
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
