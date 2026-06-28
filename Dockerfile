FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        wget \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Brussels

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
RUN python -m textblob.download_corpora

COPY betbot/ /app/betbot/
COPY dashboard/ /app/dashboard/
COPY scripts/ /app/scripts/
COPY tests/ /app/tests/

RUN chmod +x /app/scripts/entrypoint.sh
RUN mkdir -p /app/data/logs

EXPOSE 8501

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["bot"]
