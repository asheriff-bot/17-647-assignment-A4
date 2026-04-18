#!/usr/bin/env bash
# A4: build microservice images for linux/amd64 and push to Docker Hub.
# Image names match k8s/*.yaml (YOUR_REGISTRY/book-command, book-query, book-data-sync, etc.).
#
# Usage (from repo root):
#   ./scripts/build-push-dockerhub-a3.sh
#
# Defaults (override by exporting before running):
#   DB_USER, DB_PASSWORD  — for RDS at runtime (EKS/docker-compose), not used during docker build
#   DH                    — Docker Hub user or org (repository namespace)
#   TAG                   — image tag
#
# Prerequisites:
#   docker login
#   Apple Silicon: if needed once:
#     docker buildx create --name amd64builder --driver docker-container --use
#     docker buildx inspect amd64builder --bootstrap

set -euo pipefail

export DB_USER="${DB_USER:-admin123}"
export DB_PASSWORD="${DB_PASSWORD:-admin123}"
export DH="${DH:-akramdocke}"
export TAG="${TAG:-a3-latest}"

PLATFORM="linux/amd64"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! docker buildx version >/dev/null 2>&1; then
  echo "error: docker buildx not found"
  exit 1
fi

echo "DB_USER / DB_PASSWORD are set for your shell (runtime only); images do not embed them."
echo "Building ${PLATFORM} -> ${DH}/*:${TAG}"
echo ""

build_push() {
  local context="$1"
  local dockerfile="$2"
  local repo_name="$3"
  local image="${DH}/${repo_name}:${TAG}"
  echo "=== ${image} ==="
  docker buildx build \
    --platform "${PLATFORM}" \
    --push \
    -f "${dockerfile}" \
    -t "${image}" \
    "${context}"
}

build_push "./customer_service" "customer_service/Dockerfile" "customer-service"
build_push "./book_command_service" "book_command_service/Dockerfile" "book-command"
build_push "./book_query_service" "book_query_service/Dockerfile" "book-query"
build_push "./book_data_sync" "book_data_sync/Dockerfile" "book-data-sync"
build_push "./crm_service" "crm_service/Dockerfile" "crm-service"
build_push "." "web_bff/Dockerfile" "web-bff"
build_push "." "mobile_bff/Dockerfile" "mobile-bff"

echo ""
echo "Done. Set in k8s/deploy.env (then ./scripts/render_k8s_from_env.sh):"
echo "  IMAGE_REGISTRY=${DH}"
echo "  IMAGE_TAG=${TAG}"
echo ""
echo "Pull on a host (example):"
echo "  docker pull ${DH}/book-command:${TAG}"
echo "  docker pull ${DH}/book-query:${TAG}"
echo "  docker pull ${DH}/book-data-sync:${TAG}"
