# LivingDoc: one container serves the API and the website. Data lives in /data (mount a volume there).
FROM python:3.12-slim

ENV LIVINGDOC_DEMO_STOREFRONT=1 \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    LIVINGDOC_DB=/data/livingdoc.db LIVINGDOC_HUB=/data/livingdoc_hub.db LIVINGDOC_SCANNER_INBOX=/data/scanner_inbox

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend backend
COPY frontend frontend
COPY scripts scripts
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown -R app /data
USER app
WORKDIR /app/backend

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT','8000'),timeout=3)"
# $PORT is set by Render, Railway, Cloud Run and Heroku-style hosts; 8000 elsewhere.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
