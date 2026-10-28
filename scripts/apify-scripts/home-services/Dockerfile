# Repo-root build context. See .actor/actor.json dockerContextDir.
FROM apify/actor-python-playwright:3.12

ARG ACTOR_PATH_IN_DOCKER_CONTEXT=scripts/apify-scripts/home-services

USER myuser
WORKDIR /home/myuser

COPY --chown=myuser:myuser ${ACTOR_PATH_IN_DOCKER_CONTEXT}/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir --user -r requirements.txt

COPY --chown=myuser:myuser ${ACTOR_PATH_IN_DOCKER_CONTEXT}/ ./

ENV CJM_REPO_ROOT=/home/myuser/repo
COPY --chown=myuser:myuser scripts/apify-scripts/runtime.py /home/myuser/repo/scripts/apify-scripts/runtime.py
COPY --chown=myuser:myuser scripts/apify-scripts/access.py /home/myuser/repo/scripts/apify-scripts/access.py
COPY --chown=myuser:myuser scripts/apify-scripts/google-business/src/__init__.py /home/myuser/repo/scripts/apify-scripts/google-business/src/__init__.py
COPY --chown=myuser:myuser scripts/apify-scripts/google-business/src/mapping.py /home/myuser/repo/scripts/apify-scripts/google-business/src/mapping.py
COPY --chown=myuser:myuser scripts/apify-scripts/google-business/src/runtime.py /home/myuser/repo/scripts/apify-scripts/google-business/src/runtime.py
COPY --chown=myuser:myuser scripts/lead_automation/playwright_discovery.py /home/myuser/repo/scripts/lead_automation/playwright_discovery.py
COPY --chown=myuser:myuser scripts/lead_automation/crm_enrich_match.py /home/myuser/repo/scripts/lead_automation/crm_enrich_match.py
COPY --chown=myuser:myuser scripts/lead_automation/crm_enrich_robots.py /home/myuser/repo/scripts/lead_automation/crm_enrich_robots.py
COPY --chown=myuser:myuser scripts/lead_automation/email_discovery.py /home/myuser/repo/scripts/lead_automation/email_discovery.py
COPY --chown=myuser:myuser scripts/lead_automation/website_quality.py /home/myuser/repo/scripts/lead_automation/website_quality.py
COPY --chown=myuser:myuser scripts/lead_automation/intent_scoring.py /home/myuser/repo/scripts/lead_automation/intent_scoring.py
COPY --chown=myuser:myuser scripts/lead_automation/lead_signals.py /home/myuser/repo/scripts/lead_automation/lead_signals.py
COPY --chown=myuser:myuser scripts/lead_automation/niche_config.py /home/myuser/repo/scripts/lead_automation/niche_config.py
COPY --chown=myuser:myuser scripts/lead_automation/niches.json /home/myuser/repo/scripts/lead_automation/niches.json
COPY --chown=myuser:myuser scripts/lead_automation/intent_score_rules.json /home/myuser/repo/scripts/lead_automation/intent_score_rules.json
COPY --chown=myuser:myuser scripts/lead_automation/geo_regions.json /home/myuser/repo/scripts/lead_automation/geo_regions.json
COPY --chown=myuser:myuser scripts/lead_automation/keywords.json /home/myuser/repo/scripts/lead_automation/keywords.json
COPY --chown=myuser:myuser scripts/lead_automation/data/zip_county.json /home/myuser/repo/scripts/lead_automation/data/zip_county.json
COPY --chown=myuser:myuser scripts/lead_automation/data/npa_state.json /home/myuser/repo/scripts/lead_automation/data/npa_state.json
COPY --chown=myuser:myuser helper_scripts/__init__.py /home/myuser/repo/helper_scripts/__init__.py
COPY --chown=myuser:myuser helper_scripts/http/__init__.py /home/myuser/repo/helper_scripts/http/__init__.py
COPY --chown=myuser:myuser helper_scripts/http/client.py /home/myuser/repo/helper_scripts/http/client.py
COPY --chown=myuser:myuser helper_scripts/web/__init__.py /home/myuser/repo/helper_scripts/web/__init__.py
COPY --chown=myuser:myuser helper_scripts/web/urls.py /home/myuser/repo/helper_scripts/web/urls.py
COPY --chown=myuser:myuser helper_scripts/web/html_signals.py /home/myuser/repo/helper_scripts/web/html_signals.py
COPY --chown=myuser:myuser helper_scripts/text/__init__.py /home/myuser/repo/helper_scripts/text/__init__.py
COPY --chown=myuser:myuser helper_scripts/text/names.py /home/myuser/repo/helper_scripts/text/names.py
COPY --chown=myuser:myuser helper_scripts/text/phones.py /home/myuser/repo/helper_scripts/text/phones.py
COPY --chown=myuser:myuser helper_scripts/maps/__init__.py /home/myuser/repo/helper_scripts/maps/__init__.py
COPY --chown=myuser:myuser helper_scripts/maps/identity.py /home/myuser/repo/helper_scripts/maps/identity.py
COPY --chown=myuser:myuser helper_scripts/browser/__init__.py /home/myuser/repo/helper_scripts/browser/__init__.py
COPY --chown=myuser:myuser helper_scripts/browser/google_session.py /home/myuser/repo/helper_scripts/browser/google_session.py
COPY --chown=myuser:myuser helper_scripts/browser/backoff.py /home/myuser/repo/helper_scripts/browser/backoff.py
COPY --chown=myuser:myuser helper_scripts/browser/route_block.py /home/myuser/repo/helper_scripts/browser/route_block.py
COPY --chown=myuser:myuser helper_scripts/utils/__init__.py /home/myuser/repo/helper_scripts/utils/__init__.py
COPY --chown=myuser:myuser helper_scripts/utils/logger/__init__.py /home/myuser/repo/helper_scripts/utils/logger/__init__.py
COPY --chown=myuser:myuser helper_scripts/utils/logger/logger.py /home/myuser/repo/helper_scripts/utils/logger/logger.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
