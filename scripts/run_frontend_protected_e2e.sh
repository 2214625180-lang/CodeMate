#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_project="${CODEMATE_E2E_PROTECTED_COMPOSE_PROJECT:-codemate-e2e-protected}"
backend_url="http://127.0.0.1:18000"
product_token="${CODEMATE_E2E_PRODUCT_API_TOKEN:-codemate-e2e-product-token-not-for-production}"
product_identity_secret="${CODEMATE_E2E_PRODUCT_IDENTITY_SECRET:-codemate-e2e-product-identity-not-for-production}"
session_secret="${CODEMATE_E2E_SESSION_SECRET:-codemate-e2e-session-secret-not-for-production}"
compose=(
  docker compose
  --project-name "$compose_project"
  --file "$repository_root/docker-compose.yml"
  --file "$repository_root/docker-compose.e2e.yml"
  --file "$repository_root/docker-compose.e2e-protected.yml"
)

cleanup() {
  "${compose[@]}" down --volumes --remove-orphans || true
}

trap cleanup EXIT

export CODEMATE_E2E_PRODUCT_API_TOKEN="$product_token"
export CODEMATE_E2E_PRODUCT_IDENTITY_SECRET="$product_identity_secret"

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
CODEMATE_E2E_SUITE=protected \
E2E_BACKEND_URL="$backend_url" \
CODEMATE_PRODUCT_API_TOKEN="$product_token" \
CODEMATE_PRODUCT_IDENTITY_SECRET="$product_identity_secret" \
FRONTEND_ADMIN_SESSION_SECRET="$session_secret" \
GITHUB_OAUTH_CLIENT_ID="codemate-e2e-client" \
GITHUB_OAUTH_CLIENT_SECRET="codemate-e2e-client-secret" \
CODEMATE_RBAC_ADMIN_USERS="alice,bob" \
npx playwright test
