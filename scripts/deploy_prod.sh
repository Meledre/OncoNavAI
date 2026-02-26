#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/infra/.env.prod}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing env file: $ENV_FILE"
  echo "Copy template first: cp $ROOT_DIR/infra/.env.prod.example $ROOT_DIR/infra/.env.prod"
  exit 1
fi

echo "[1/3] Pull immutable images from registry..."
docker compose \
  -f "$ROOT_DIR/infra/docker-compose.prod.yml" \
  --env-file "$ENV_FILE" \
  pull

echo "[2/3] Apply deployment..."
docker compose \
  -f "$ROOT_DIR/infra/docker-compose.prod.yml" \
  --env-file "$ENV_FILE" \
  up -d

echo "[3/3] Service status..."
docker compose \
  -f "$ROOT_DIR/infra/docker-compose.prod.yml" \
  --env-file "$ENV_FILE" \
  ps
