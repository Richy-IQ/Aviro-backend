# syntax=docker/dockerfile:1

# ─────────────────────────────────────────────────────────────────────────────
# Base — everything both targets share. Kept thin so the layers cache well.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq is needed at runtime by psycopg; curl is used by the container healthcheck.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies are installed from the manifest alone, so editing application
# code never invalidates the install layer.
COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools wheel

# ─────────────────────────────────────────────────────────────────────────────
# Development — dev dependencies, source bind-mounted at run time, autoreload.
# ─────────────────────────────────────────────────────────────────────────────
FROM base AS development

RUN pip install ".[dev]"

COPY . .

ENV DJANGO_SETTINGS_MODULE=config.settings.development

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# ─────────────────────────────────────────────────────────────────────────────
# Production — no dev tooling, no source mount, non-root, gunicorn.
# ─────────────────────────────────────────────────────────────────────────────
FROM base AS production

RUN pip install .

COPY . .
RUN chmod +x docker-entrypoint.sh

ENV DJANGO_SETTINGS_MODULE=config.settings.production

# Static files are collected at build time so the running container never needs
# write access to the image.
RUN DJANGO_SECRET_KEY=build-only \
    DATABASE_URL=postgres://build:build@localhost:5432/build \
    DJANGO_ALLOWED_HOSTS=localhost \
    CORS_ALLOWED_ORIGINS=http://localhost \
    python manage.py collectstatic --noinput

# Running as root inside a container is the default and it should not be.
RUN useradd --system --create-home --uid 10001 aviro \
    && chown -R aviro:aviro /app
USER aviro

# Documentation only. The port actually bound is whatever PORT says at run
# time, which is how Railway and most other platforms assign one.
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT:-8000}/api/health/" || exit 1

# Migrates, then serves. See docker-entrypoint.sh.
CMD ["./docker-entrypoint.sh"]
