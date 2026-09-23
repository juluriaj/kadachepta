FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/worker
COPY worker/requirements.txt ./
RUN pip install -r requirements.txt
COPY worker/ ./
RUN useradd --uid 10001 --create-home kathachepta
USER kathachepta
CMD ["python", "-m", "kc_worker"]
