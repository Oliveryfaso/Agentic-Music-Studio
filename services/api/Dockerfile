FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

RUN pip install --no-cache-dir uv==0.12.1

COPY pyproject.toml uv.lock README.md ./
COPY services/api/src ./services/api/src
COPY alembic.ini ./alembic.ini
COPY infra/migrations ./infra/migrations

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "motif_forge.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
