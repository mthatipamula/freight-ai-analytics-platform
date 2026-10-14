#!/usr/bin/env bash
# Local stack: FastAPI backend (Gemini on Vertex AI + BigQuery) and the web app on http://localhost:8060.
#   ./scripts/dev.sh start        build and start
#   ./scripts/dev.sh stop         stop
#   ./scripts/dev.sh status       containers and backend health
#   ./scripts/dev.sh logs [svc]   follow logs
#   ./scripts/dev.sh setup-data   create the BigQuery dataset, tables and views and load synthetic freight data
#   ./scripts/dev.sh samples      redraw the sample bills of lading
#   ./scripts/dev.sh test         governance unit tests
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example. Set GOOGLE_CLOUD_PROJECT if needed."; }
[ -f "$HOME/.config/gcloud/application_default_credentials.json" ] ||
  echo "Note: no Application Default Credentials found. Run: gcloud auth application-default login"

case "${1:-start}" in
  start)
    docker compose up -d --build
    printf 'Waiting for the API'
    for _ in $(seq 1 60); do curl -sf localhost:8061/health >/dev/null && break; printf '.'; sleep 2; done
    echo
    docker compose ps --format 'table {{.Service}}\t{{.Status}}'
    cat <<MSG

Web app:  http://localhost:8060
API:      http://localhost:8061/docs
MSG
    ;;
  stop)       docker compose stop ;;
  status)     docker compose ps --format 'table {{.Service}}\t{{.Status}}'; curl -s localhost:8061/health; echo ;;
  logs)       docker compose logs -f --tail 100 ${2:+"$2"} ;;
  setup-data) docker compose run --rm --no-deps backend python -m app.data.generate ;;
  samples)    docker compose run --rm --no-deps -v "$PWD/backend/samples:/app/samples" backend python -m app.data.make_samples ;;
  test)       docker compose run --rm --no-deps -v "$PWD/backend/tests:/app/tests:ro" backend sh -c "pip install -q pytest && python -m pytest -q -p no:cacheprovider tests" ;;
  *) echo "usage: $0 [start|stop|status|logs [service]|setup-data|samples|test]"; exit 1 ;;
esac
