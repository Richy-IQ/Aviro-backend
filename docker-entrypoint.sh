#!/bin/sh
# Container start-up.
#
# Railway assigns a port per deploy and injects it as PORT, then routes only to
# that port. Binding a hardcoded 8000 is the usual way a Railway deploy builds
# green and is unreachable, so the bind address is read from the environment.
set -e

PORT="${PORT:-8000}"

# Migrations run before the first request rather than as a separate release
# step, so a deploy can never serve traffic against a schema it does not have.
echo "Applying migrations…"
python manage.py migrate --noinput

echo "Starting gunicorn on 0.0.0.0:${PORT}"
exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WEB_CONCURRENCY:-3}" \
    --worker-class gthread \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
