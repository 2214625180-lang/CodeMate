#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_project="${CODEMATE_E2E_COMPOSE_PROJECT:-codemate-e2e}"
backend_url="http://127.0.0.1:18000"
compose=(
  docker compose
  --project-name "$compose_project"
  --file "$repository_root/docker-compose.yml"
  --file "$repository_root/docker-compose.e2e.yml"
)

cleanup() {
  "${compose[@]}" down --volumes --remove-orphans || true
}

trap cleanup EXIT

"${compose[@]}" up --build --detach postgres redis qdrant migrate backend

ready=false
for _ in $(seq 1 60); do
  if curl --fail --silent --max-time 2 "$backend_url/health/readiness" >/dev/null; then
    ready=true
    break
  fi
  sleep 2
done

if [[ "$ready" != "true" ]]; then
  "${compose[@]}" logs backend migrate
  exit 1
fi

"${compose[@]}" run --build --rm e2e-seed

cd "$repository_root/frontend"
E2E_BACKEND_URL="$backend_url" npx playwright test
