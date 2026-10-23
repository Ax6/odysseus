# Keep the application version unchanged while correcting its independent trust.
FROM docker.io/searxng/searxng:2026.10.19-81371861f@sha256:5ed0323b5f5f8701264ef65e239a2bd83cb57098f2b971fa30bf79c06eeae271 AS base

FROM base AS baseline-validation
COPY docker/searxng/repair_trust.py docker/searxng/blocked-certificates.json docker/searxng/validate_image.py /opt/odysseus-trust/
COPY tests/fixtures/ca-trust/incident.json /opt/odysseus-trust/incident.json
RUN /usr/local/searxng/.venv/bin/python /opt/odysseus-trust/validate_image.py --baseline

FROM base AS repaired
COPY docker/searxng/repair_trust.py docker/searxng/blocked-certificates.json /opt/odysseus-trust/
RUN /usr/local/searxng/.venv/bin/python /opt/odysseus-trust/repair_trust.py

# Optional offline validation runs inside the actual SearXNG filesystem.
FROM repaired AS validation
COPY tests/fixtures/ca-trust/incident.json /opt/odysseus-trust/incident.json
COPY docker/searxng/validate_image.py /opt/odysseus-trust/validate_image.py
RUN /usr/local/searxng/.venv/bin/python /opt/odysseus-trust/validate_image.py

FROM validation AS live-validation
RUN /usr/local/searxng/.venv/bin/python /opt/odysseus-trust/validate_image.py --live

FROM repaired AS runtime
