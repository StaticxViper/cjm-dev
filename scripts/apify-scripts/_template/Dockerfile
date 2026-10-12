# Copy this file with the template. Apify builds with the repo as context
# (dockerContextDir in .actor/actor.json) and sets ACTOR_PATH_IN_DOCKER_CONTEXT.
FROM apify/actor-python-playwright:3.12

ARG ACTOR_PATH_IN_DOCKER_CONTEXT=scripts/apify-scripts/_template

USER myuser
WORKDIR /home/myuser

COPY --chown=myuser:myuser ${ACTOR_PATH_IN_DOCKER_CONTEXT}/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --user -r requirements.txt

COPY --chown=myuser:myuser ${ACTOR_PATH_IN_DOCKER_CONTEXT}/ ./

ENV CJM_REPO_ROOT=/home/myuser/repo
COPY --chown=myuser:myuser scripts/apify-scripts/runtime.py /home/myuser/repo/scripts/apify-scripts/runtime.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
