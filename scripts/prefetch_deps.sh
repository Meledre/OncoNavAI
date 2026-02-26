#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[1/3] Preparing vendor directories..."
mkdir -p "$ROOT_DIR/backend/vendor/wheels" "$ROOT_DIR/frontend/vendor/npm-cache"

echo "[2/3] Downloading Python wheels for Docker runtime (linux, cp311)..."
find "$ROOT_DIR/backend/vendor/wheels" -type f -name '*.whl' -delete
for platform in manylinux2014_aarch64 manylinux2014_x86_64; do
  python3 -m pip download \
    --only-binary=:all: \
    --implementation cp \
    --python-version 3.11 \
    --abi cp311 \
    --platform "$platform" \
    -r "$ROOT_DIR/backend/requirements.txt" \
    -d "$ROOT_DIR/backend/vendor/wheels"
done

echo "[3/3] Priming npm cache..."
(
  cd "$ROOT_DIR/frontend"
  NEXT_VERSION="$(
    python3 -c "import json; print(json.load(open('package.json')).get('dependencies', {}).get('next', ''))" \
      | tr -d '\r\n'
  )"
  if [ -n "$NEXT_VERSION" ]; then
    for swc_pkg in \
      @next/swc-linux-arm64-gnu \
      @next/swc-linux-x64-gnu \
      @next/swc-linux-arm64-musl \
      @next/swc-linux-x64-musl; do
      if ! npm cache add "${swc_pkg}@${NEXT_VERSION}" --cache "$ROOT_DIR/frontend/vendor/npm-cache" >/dev/null 2>&1; then
        echo "WARN: failed to cache ${swc_pkg}@${NEXT_VERSION}" >&2
      fi
    done
  fi
  if [ -f package-lock.json ]; then
    npm ci --cache "$ROOT_DIR/frontend/vendor/npm-cache" --prefer-offline --no-audit --no-fund
  else
    npm install --cache "$ROOT_DIR/frontend/vendor/npm-cache" --prefer-offline --no-audit --no-fund
  fi
)
rm -rf "$ROOT_DIR/frontend/node_modules"

echo "Dependency prefetch complete."
echo "You can now build with offline args:"
echo "  PIP_INSTALL_MODE=offline NPM_INSTALL_MODE=offline docker compose -f infra/docker-compose.yml up --build -d"
