# Repo-root build context. See .actor/actor.json dockerContextDir.
FROM apify/actor-python-playwright:3.12

ARG ACTOR_PATH_IN_DOCKER_CONTEXT=scripts/apify-scripts/city-data

USER myuser
WORKDIR /home/myuser

COPY --chown=myuser:myuser ${ACTOR_PATH_IN_DOCKER_CONTEXT}/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --user -r requirements.txt

COPY --chown=myuser:myuser ${ACTOR_PATH_IN_DOCKER_CONTEXT}/ ./

ENV CJM_REPO_ROOT=/home/myuser/repo
COPY --chown=myuser:myuser scripts/city_data /home/myuser/repo/scripts/city_data
COPY --chown=myuser:myuser scripts/lead_automation/crm_enrich_robots.py /home/myuser/repo/scripts/lead_automation/crm_enrich_robots.py
COPY --chown=myuser:myuser helper_scripts/__init__.py /home/myuser/repo/helper_scripts/__init__.py
COPY --chown=myuser:myuser helper_scripts/utils/__init__.py /home/myuser/repo/helper_scripts/utils/__init__.py
COPY --chown=myuser:myuser helper_scripts/utils/logger/logger.py /home/myuser/repo/helper_scripts/utils/logger/logger.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
