FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/api

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
