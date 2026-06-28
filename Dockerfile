FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Brussels

COPY requirements.txt .
RUN pip install -r requirements.txt
RUN python -m textblob.download_corpora

COPY betbot/ ./betbot/
COPY dashboard/ ./dashboard/
COPY tests/ ./tests/

RUN mkdir -p /app/data/logs

EXPOSE 8501

CMD ["python", "-m", "betbot.main"]
