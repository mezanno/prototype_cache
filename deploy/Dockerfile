# asset-store service image (B-002, ADR-002).
#
# Single FastAPI process serving the reserve/commit/resolve control plane, the
# capability-guarded data plane, and /healthz//readyz//metrics. Backends are
# selected from the environment by the create_app_from_env factory.
#
# Build context is the repository root:
#   docker build -f deploy/Dockerfile -t asset-store:dev .
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first for better layer caching. The [s3,pg] extras pull in
# boto3 and psycopg so the durable S3 and Postgres backends are available.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[s3,pg]"

# Drop privileges.
RUN useradd --no-create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# The ASGI factory picks LocalObjectStore or S3ObjectStore from the environment.
CMD ["uvicorn", "asset_store_core.api.app:create_app_from_env", "--factory", \
     "--host", "0.0.0.0", "--port", "8000"]
