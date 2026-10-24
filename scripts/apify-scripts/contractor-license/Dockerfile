# Repo-root build context. See .actor/actor.json dockerContextDir.
# The image is the shared Playwright base. This Actor's lookup is HTTP only.
FROM apify/actor-python-playwright:3.12

ARG ACTOR_PATH_IN_DOCKER_CONTEXT=scripts/apify-scripts/contractor-license

USER myuser
WORKDIR /home/myuser

COPY --chown=myuser:myuser ${ACTOR_PATH_IN_DOCKER_CONTEXT}/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --user -r requirements.txt

COPY --chown=myuser:myuser ${ACTOR_PATH_IN_DOCKER_CONTEXT}/ ./

ENV CJM_REPO_ROOT=/home/myuser/repo
COPY --chown=myuser:myuser scripts/apify-scripts/runtime.py /home/myuser/repo/scripts/apify-scripts/runtime.py
COPY --chown=myuser:myuser scripts/lead_automation/crm_enrich_robots.py /home/myuser/repo/scripts/lead_automation/crm_enrich_robots.py
COPY --chown=myuser:myuser helper_scripts/__init__.py /home/myuser/repo/helper_scripts/__init__.py
COPY --chown=myuser:myuser helper_scripts/http/__init__.py /home/myuser/repo/helper_scripts/http/__init__.py
COPY --chown=myuser:myuser helper_scripts/http/client.py /home/myuser/repo/helper_scripts/http/client.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
