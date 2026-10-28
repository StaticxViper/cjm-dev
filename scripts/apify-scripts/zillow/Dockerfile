# Repo-root build context. See .actor/actor.json dockerContextDir.
FROM apify/actor-python-playwright:3.12

ARG ACTOR_PATH_IN_DOCKER_CONTEXT=scripts/apify-scripts/zillow

USER myuser
WORKDIR /home/myuser

COPY --chown=myuser:myuser ${ACTOR_PATH_IN_DOCKER_CONTEXT}/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --user -r requirements.txt

COPY --chown=myuser:myuser ${ACTOR_PATH_IN_DOCKER_CONTEXT}/ ./

ENV CJM_REPO_ROOT=/home/myuser/repo
COPY --chown=myuser:myuser scripts/apify-scripts/runtime.py /home/myuser/repo/scripts/apify-scripts/runtime.py
COPY --chown=myuser:myuser scripts/apify-scripts/access.py /home/myuser/repo/scripts/apify-scripts/access.py

COPY --chown=myuser:myuser helper_scripts/__init__.py /home/myuser/repo/helper_scripts/__init__.py
COPY --chown=myuser:myuser helper_scripts/api_manager/__init__.py /home/myuser/repo/helper_scripts/api_manager/__init__.py
COPY --chown=myuser:myuser helper_scripts/api_manager/api_manager.py /home/myuser/repo/helper_scripts/api_manager/api_manager.py
COPY --chown=myuser:myuser helper_scripts/browser/__init__.py /home/myuser/repo/helper_scripts/browser/__init__.py
COPY --chown=myuser:myuser helper_scripts/browser/backoff.py /home/myuser/repo/helper_scripts/browser/backoff.py
COPY --chown=myuser:myuser helper_scripts/browser/google_session.py /home/myuser/repo/helper_scripts/browser/google_session.py
COPY --chown=myuser:myuser helper_scripts/browser/route_block.py /home/myuser/repo/helper_scripts/browser/route_block.py
COPY --chown=myuser:myuser helper_scripts/http/__init__.py /home/myuser/repo/helper_scripts/http/__init__.py
COPY --chown=myuser:myuser helper_scripts/http/client.py /home/myuser/repo/helper_scripts/http/client.py
COPY --chown=myuser:myuser helper_scripts/text/__init__.py /home/myuser/repo/helper_scripts/text/__init__.py
COPY --chown=myuser:myuser helper_scripts/text/names.py /home/myuser/repo/helper_scripts/text/names.py
COPY --chown=myuser:myuser helper_scripts/text/phones.py /home/myuser/repo/helper_scripts/text/phones.py
COPY --chown=myuser:myuser helper_scripts/utils/__init__.py /home/myuser/repo/helper_scripts/utils/__init__.py
COPY --chown=myuser:myuser helper_scripts/utils/logger/__init__.py /home/myuser/repo/helper_scripts/utils/logger/__init__.py
COPY --chown=myuser:myuser helper_scripts/utils/logger/logger.py /home/myuser/repo/helper_scripts/utils/logger/logger.py
COPY --chown=myuser:myuser helper_scripts/web/__init__.py /home/myuser/repo/helper_scripts/web/__init__.py
COPY --chown=myuser:myuser helper_scripts/web/html_signals.py /home/myuser/repo/helper_scripts/web/html_signals.py
COPY --chown=myuser:myuser helper_scripts/web/urls.py /home/myuser/repo/helper_scripts/web/urls.py

COPY --chown=myuser:myuser scripts/lead_automation/crm_enrich_match.py /home/myuser/repo/scripts/lead_automation/crm_enrich_match.py
COPY --chown=myuser:myuser scripts/lead_automation/email_discovery.py /home/myuser/repo/scripts/lead_automation/email_discovery.py
COPY --chown=myuser:myuser scripts/lead_automation/leadenrich.py /home/myuser/repo/scripts/lead_automation/leadenrich.py
COPY --chown=myuser:myuser scripts/lead_automation/leadenrich_playwright.py /home/myuser/repo/scripts/lead_automation/leadenrich_playwright.py
COPY --chown=myuser:myuser scripts/lead_automation/website_quality.py /home/myuser/repo/scripts/lead_automation/website_quality.py

COPY --chown=myuser:myuser scripts/opp_finder_v2/__init__.py /home/myuser/repo/scripts/opp_finder_v2/__init__.py
COPY --chown=myuser:myuser scripts/opp_finder_v2/browser/__init__.py /home/myuser/repo/scripts/opp_finder_v2/browser/__init__.py
COPY --chown=myuser:myuser scripts/opp_finder_v2/browser/detection.py /home/myuser/repo/scripts/opp_finder_v2/browser/detection.py
COPY --chown=myuser:myuser scripts/opp_finder_v2/models.py /home/myuser/repo/scripts/opp_finder_v2/models.py
COPY --chown=myuser:myuser scripts/opp_finder_v2/parsing.py /home/myuser/repo/scripts/opp_finder_v2/parsing.py
COPY --chown=myuser:myuser scripts/opp_finder_v2/politeness.py /home/myuser/repo/scripts/opp_finder_v2/politeness.py

COPY --chown=myuser:myuser scripts/zillow_automation/__init__.py /home/myuser/repo/scripts/zillow_automation/__init__.py
COPY --chown=myuser:myuser scripts/zillow_automation/zillow_agents.py /home/myuser/repo/scripts/zillow_automation/zillow_agents.py
COPY --chown=myuser:myuser scripts/zillow_automation/zillow_enrich.py /home/myuser/repo/scripts/zillow_automation/zillow_enrich.py
COPY --chown=myuser:myuser scripts/zillow_automation/zillow_parse.py /home/myuser/repo/scripts/zillow_automation/zillow_parse.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
