#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 /path/to/oncoai-images.tar"
  exit 1
fi

ARCHIVE="$1"
docker load -i "$ARCHIVE"
echo "Images loaded. Start stack without rebuild:"
echo "  docker compose -f infra/docker-compose.yml up -d"
