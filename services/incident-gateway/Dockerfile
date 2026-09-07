FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GATEWAY_DATABASE_PATH=/var/lib/incident-gateway/incidents.db

RUN addgroup --system --gid 10001 gateway \
    && adduser --system --uid 10001 --ingroup gateway gateway \
    && mkdir -p /var/lib/incident-gateway \
    && chown -R gateway:gateway /var/lib/incident-gateway

WORKDIR /srv/incident-gateway
COPY app ./app

USER gateway
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('GATEWAY_PORT','8080')+'/healthz', timeout=2).read()"]

CMD ["python", "-m", "app"]
