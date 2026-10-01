#!/bin/sh
set -e
case "$1" in
  web)
    python -m app.cli init-db
    if [ "${ERP_SEED_DEMO:-false}" = "true" ]; then
      python -m app.cli seed-demo || true
    fi
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-2}" --proxy-headers --forwarded-allow-ips='*'
    ;;
  worker)
    exec python -m app.worker
    ;;
  *)
    exec "$@"
    ;;
esac
