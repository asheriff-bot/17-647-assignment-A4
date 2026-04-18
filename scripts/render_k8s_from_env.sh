#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/k8s/deploy.env}"
OUT_DIR="$ROOT_DIR/k8s/rendered"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file not found: $ENV_FILE"
  echo "Copy k8s/deploy.env.example to k8s/deploy.env and fill values."
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

: "${IMAGE_REGISTRY:?IMAGE_REGISTRY is required}"
: "${IMAGE_TAG:?IMAGE_TAG is required}"
: "${RDS_ENDPOINT:?RDS_ENDPOINT is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"
: "${KAFKA_BROKERS:?KAFKA_BROKERS is required}"
: "${ANDREW_ID:?ANDREW_ID is required}"
: "${EMAIL_ADDRESS:?EMAIL_ADDRESS is required}"
: "${RECOMMENDATION_SERVICE_URL:?RECOMMENDATION_SERVICE_URL is required}"
: "${RECOMMENDATION_PATH_TEMPLATE:?RECOMMENDATION_PATH_TEMPLATE is required}"
: "${SMTP_HOST:?SMTP_HOST is required}"
: "${SMTP_PORT:?SMTP_PORT is required}"
: "${SMTP_STARTTLS:?SMTP_STARTTLS is required}"
: "${SMTP_USERNAME:?SMTP_USERNAME is required}"
: "${SMTP_PASSWORD:?SMTP_PASSWORD is required}"
: "${SMTP_SENDER_EMAIL:?SMTP_SENDER_EMAIL is required}"
: "${MONGO_URI:?MONGO_URI is required}"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

for f in "$ROOT_DIR"/k8s/*.yaml; do
  bn="$(basename "$f")"
  if [[ "$bn" == "namespace.yaml" ]]; then
    cp "$f" "$OUT_DIR/$bn"
    continue
  fi

  sed \
    -e "s|YOUR_REGISTRY/web-bff:latest|${IMAGE_REGISTRY}/web-bff:${IMAGE_TAG}|g" \
    -e "s|YOUR_REGISTRY/mobile-bff:latest|${IMAGE_REGISTRY}/mobile-bff:${IMAGE_TAG}|g" \
    -e "s|YOUR_REGISTRY/customer-service:latest|${IMAGE_REGISTRY}/customer-service:${IMAGE_TAG}|g" \
    -e "s|YOUR_REGISTRY/book-command:latest|${IMAGE_REGISTRY}/book-command:${IMAGE_TAG}|g" \
    -e "s|YOUR_REGISTRY/book-query:latest|${IMAGE_REGISTRY}/book-query:${IMAGE_TAG}|g" \
    -e "s|YOUR_REGISTRY/book-data-sync:latest|${IMAGE_REGISTRY}/book-data-sync:${IMAGE_TAG}|g" \
    -e "s|YOUR_REGISTRY/crm-service:latest|${IMAGE_REGISTRY}/crm-service:${IMAGE_TAG}|g" \
    -e "s|YOUR_RDS_ENDPOINT|${RDS_ENDPOINT}|g" \
    -e "s|YOUR_MONGO_URI|${MONGO_URI}|g" \
    -e "s|YOUR_DB_USER|${DB_USER}|g" \
    -e "s|YOUR_DB_PASSWORD|${DB_PASSWORD}|g" \
    -e "s|YOUR_KAFKA_BROKERS|${KAFKA_BROKERS}|g" \
    -e "s|YOUR_RECOMMENDATION_SERVICE_URL|${RECOMMENDATION_SERVICE_URL}|g" \
    -e "s|/recommended-titles/isbn/{isbn}|${RECOMMENDATION_PATH_TEMPLATE}|g" \
    -e "s|your_andrew_id|${ANDREW_ID}|g" \
    -e "s|your_email@gmail.com|${EMAIL_ADDRESS}|g" \
    -e "s|YOUR_SMTP_HOST|${SMTP_HOST}|g" \
    -e "s|YOUR_SMTP_PORT|${SMTP_PORT}|g" \
    -e "s|YOUR_SMTP_STARTTLS|${SMTP_STARTTLS}|g" \
    -e "s|YOUR_SMTP_USERNAME|${SMTP_USERNAME}|g" \
    -e "s|YOUR_SMTP_PASSWORD|${SMTP_PASSWORD}|g" \
    -e "s|YOUR_SMTP_SENDER_EMAIL|${SMTP_SENDER_EMAIL}|g" \
    "$f" > "$OUT_DIR/$bn"
done

echo "Rendered manifests written to: $OUT_DIR"
