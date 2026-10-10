# Repo-root build context. See .actor/actor.json dockerContextDir.
FROM apify/actor-python-playwright:3.12

ARG ACTOR_PATH_IN_DOCKER_CONTEXT=scripts/apify-scripts/google-business

USER myuser
WORKDIR /home/myuser

COPY --chown=myuser:myuser ${ACTOR_PATH_IN_DOCKER_CONTEXT}/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --user -r requirements.txt

COPY --chown=myuser:myuser ${ACTOR_PATH_IN_DOCKER_CONTEXT}/ ./

ENV CJM_REPO_ROOT=/home/myuser/repo
COPY --chown=myuser:myuser scripts/lead_automation/playwright_discovery.py /home/myuser/repo/scripts/lead_automation/playwright_discovery.py
COPY --chown=myuser:myuser scripts/lead_automation/crm_enrich_match.py /home/myuser/repo/scripts/lead_automation/crm_enrich_match.py
COPY --chown=myuser:myuser scripts/lead_automation/crm_enrich_robots.py /home/myuser/repo/scripts/lead_automation/crm_enrich_robots.py
COPY --chown=myuser:myuser scripts/lead_automation/email_discovery.py /home/myuser/repo/scripts/lead_automation/email_discovery.py
COPY --chown=myuser:myuser scripts/lead_automation/website_quality.py /home/myuser/repo/scripts/lead_automation/website_quality.py
COPY --chown=myuser:myuser scripts/lead_automation/leadenrich.py /home/myuser/repo/scripts/lead_automation/leadenrich.py
COPY --chown=myuser:myuser scripts/lead_automation/keywords.json /home/myuser/repo/scripts/lead_automation/keywords.json
COPY --chown=myuser:myuser scripts/lead_automation/data/zip_county.json /home/myuser/repo/scripts/lead_automation/data/zip_county.json
COPY --chown=myuser:myuser scripts/lead_automation/data/npa_state.json /home/myuser/repo/scripts/lead_automation/data/npa_state.json
COPY --chown=myuser:myuser helper_scripts/__init__.py /home/myuser/repo/helper_scripts/__init__.py
COPY --chown=myuser:myuser helper_scripts/utils/__init__.py /home/myuser/repo/helper_scripts/utils/__init__.py
COPY --chown=myuser:myuser helper_scripts/utils/logger/logger.py /home/myuser/repo/helper_scripts/utils/logger/logger.py
COPY --chown=myuser:myuser helper_scripts/api_manager/__init__.py /home/myuser/repo/helper_scripts/api_manager/__init__.py
COPY --chown=myuser:myuser helper_scripts/api_manager/api_manager.py /home/myuser/repo/helper_scripts/api_manager/api_manager.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
