FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8008 \
    WHAT_TO_WEAR_DB=/app/data/what_to_wear.sqlite3

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system wtw \
    && useradd --system --gid wtw --home-dir /app --shell /usr/sbin/nologin wtw \
    && mkdir -p /app/data \
    && chown -R wtw:wtw /app

COPY --chown=wtw:wtw app.py README.md ./
COPY --chown=wtw:wtw static ./static
COPY --chown=wtw:wtw templates ./templates

USER wtw

EXPOSE 8008

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT', '8008'), timeout=3).read()"

CMD ["python", "app.py"]
