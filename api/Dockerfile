# Two targets: "api" (local; compose mounts app/dist) and "production" (Lightsail; the listener web app is baked in).

FROM node:24-slim AS webapp
WORKDIR /srv/app
COPY app/package.json app/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY app/ ./
# The export needs about 2 GB. Node sizes its heap from RAM, so on the 1 GB server it would stop short of what
# the swap file allows.
RUN NODE_OPTIONS=--max-old-space-size=3072 npx expo export -p web

FROM python:3.13-slim AS api

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/api

# FriBiDi lets Pillow lay out Telugu (book cover titles, services/covers.py).
RUN apt-get update && apt-get install -y --no-install-recommends libfribidi0 && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt api/requirements-dev.txt ./
ARG INSTALL_DEV=false
RUN pip install -r requirements.txt && if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

COPY api/ ./
COPY web/ /srv/web/
ENV KC_WEB_ROOT=/srv/web

RUN useradd --uid 10001 --create-home kathachepta && mkdir -p /data/media && chown -R kathachepta /data
USER kathachepta

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${KC_API_WORKERS:-2} --proxy-headers --forwarded-allow-ips='*' --no-access-log"]

FROM api AS production
COPY --from=webapp /srv/app/dist /srv/app
ENV KC_APP_ROOT=/srv/app
