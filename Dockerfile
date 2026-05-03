# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY api ./api
COPY evaluator ./evaluator
COPY leaderboard ./leaderboard
COPY prompts ./prompts
COPY corpora ./corpora

# Cloud Run sets $PORT; default to 8080 for local docker run.
ENV PORT=8080
EXPOSE 8080

# Single uvicorn worker per Cloud Run instance — Cloud Run handles horizontal scaling.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
