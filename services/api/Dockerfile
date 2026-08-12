FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

RUN pip install --no-cache-dir uv==0.12.1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md ./README.md
COPY services/api/src ./services/api/src
RUN uv sync --frozen --no-dev --no-editable \
    && rm -rf /root/.cache/uv

FROM python:3.12-slim AS runtime-base

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./alembic.ini
COPY infra/migrations ./infra/migrations

FROM runtime-base AS api

EXPOSE 8000

CMD ["uvicorn", "motif_forge.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim AS media-worker-base

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && attempt=1 \
    && while ! apt-get -o Acquire::Retries=3 install -y --no-install-recommends ffmpeg; do \
         test "$attempt" -lt 5; \
         attempt=$((attempt + 1)); \
         apt-get update; \
       done \
    && command -v ffmpeg >/dev/null \
    && rm -rf /var/cache/apt/archives/*.deb /var/lib/apt/lists/*

RUN groupadd --gid 10001 motif-forge \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin motif-forge

FROM media-worker-base AS media-worker

COPY --from=builder /opt/venv /opt/venv
COPY alembic.ini ./alembic.ini
COPY infra/migrations ./infra/migrations

USER 10001:10001

CMD ["celery", "-A", "motif_forge.worker.celery_app:celery_app", "worker", "--queues=media", "--concurrency=1", "--prefetch-multiplier=1", "--without-gossip", "--without-mingle", "--loglevel=INFO"]

FROM api AS runtime
