#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/infra/offline"
OUT_FILE="$OUT_DIR/oncoai-images.tar"

mkdir -p "$OUT_DIR"

echo "[1/2] Building local images..."
docker compose -f "$ROOT_DIR/infra/docker-compose.yml" build

echo "[2/2] Exporting images to $OUT_FILE ..."
docker save -o "$OUT_FILE" oncoai/backend:local oncoai/frontend:local

echo "Done."
echo "Transfer this file to server and run:"
echo "  docker load -i oncoai-images.tar"
