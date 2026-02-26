#!/usr/bin/env bash
set -euo pipefail

EXIT_USAGE=2
EXIT_SECURITY=3
EXIT_GIT=4
EXIT_RUNTIME=5

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_BRANCH="main"
DEFAULT_WORKDIR="/tmp/oncoai-public-export"

PUBLIC_REPO_URL=""
BRANCH="$DEFAULT_BRANCH"
WORKDIR="$DEFAULT_WORKDIR"
COMMIT_MESSAGE=""
DRY_RUN="false"
NO_PUSH="false"
FROM_WORKING_TREE="false"

RUN_DIR=""
SRC_SNAPSHOT_DIR=""
PUBLIC_CLONE_DIR=""
SOURCE_REPO=""
SOURCE_COMMIT=""
SOURCE_SHORT_SHA=""

WHITELIST_ITEMS=(
  "backend"
  "frontend"
  "infra"
  "scripts"
  "Makefile"
  "LICENSE"
  "COPYRIGHT"
  "README.md"
  "README.en.md"
  ".env.example"
  ".dockerignore"
  ".gitignore"
)

BLOCKLIST_ITEMS=(
  ".env"
  ".env.*"
  "data/"
  "docs/cap/"
  "docs/qa/"
  "reports/"
  ".github/"
  ".idea/"
  ".venv/"
  ".worktrees/"
  "backend/tests/"
  "backend/vendor/"
  "backend/app/security/"
  "frontend/lib/security/"
  "scripts/security_gate.py"
  "scripts/session_incident_gate.py"
  "infra/offline/*.tar"
  "scripts/*.applescript"
)

SAFE_HINTS=(
  "example"
  "placeholder"
  "changeme"
  "demo-token"
  "dev-idp-secret"
)

usage() {
  cat <<'HELP'
Usage:
  ./scripts/public_export.sh \
    --public-repo-url git@github.com:<account>/<repo>.git \
    [--branch main] \
    [--workdir /tmp/oncoai-public-export] \
    [--commit-message "chore(public): sanitized sync from <sha>"] \
    [--dry-run] \
    [--no-push] \
    [--from-working-tree]

Description:
  Create a sanitized public snapshot from the private repository and publish to GitHub.
HELP
}

die() {
  local code="${1:-$EXIT_RUNTIME}"
  shift || true
  echo "error: $*" >&2
  exit "$code"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "$EXIT_RUNTIME" "required command not found: $1"
}

cleanup() {
  if [ -n "${RUN_DIR:-}" ] && [ -d "$RUN_DIR" ]; then
    rm -rf "$RUN_DIR"
  fi
}
trap cleanup EXIT

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --public-repo-url)
        [ "$#" -ge 2 ] || die "$EXIT_USAGE" "missing value for --public-repo-url"
        PUBLIC_REPO_URL="$2"
        shift 2
        ;;
      --branch)
        [ "$#" -ge 2 ] || die "$EXIT_USAGE" "missing value for --branch"
        BRANCH="$2"
        shift 2
        ;;
      --workdir)
        [ "$#" -ge 2 ] || die "$EXIT_USAGE" "missing value for --workdir"
        WORKDIR="$2"
        shift 2
        ;;
      --commit-message)
        [ "$#" -ge 2 ] || die "$EXIT_USAGE" "missing value for --commit-message"
        COMMIT_MESSAGE="$2"
        shift 2
        ;;
      --dry-run)
        DRY_RUN="true"
        shift
        ;;
      --no-push)
        NO_PUSH="true"
        shift
        ;;
      --from-working-tree)
        FROM_WORKING_TREE="true"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        usage
        die "$EXIT_USAGE" "unknown argument: $1"
        ;;
    esac
  done

  if [ -z "$PUBLIC_REPO_URL" ]; then
    usage
    die "$EXIT_USAGE" "--public-repo-url is required"
  fi
}

setup_runtime_dirs() {
  local run_stamp
  run_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  RUN_DIR="$WORKDIR/run_${run_stamp}_$$"
  SRC_SNAPSHOT_DIR="$RUN_DIR/source_snapshot"
  PUBLIC_CLONE_DIR="$RUN_DIR/public_clone"

  mkdir -p "$SRC_SNAPSHOT_DIR" "$PUBLIC_CLONE_DIR"
}

collect_source_meta() {
  SOURCE_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"
  SOURCE_SHORT_SHA="$(git -C "$ROOT_DIR" rev-parse --short HEAD)"
  SOURCE_REPO="$(git -C "$ROOT_DIR" config --get remote.origin.url || true)"
  if [ -z "$SOURCE_REPO" ]; then
    SOURCE_REPO="$ROOT_DIR"
  fi
}

create_source_snapshot() {
  if [ "$FROM_WORKING_TREE" = "true" ]; then
    rsync -a --delete \
      --exclude ".git/" \
      --exclude ".worktrees/" \
      --exclude ".idea/" \
      --exclude ".venv/" \
      "$ROOT_DIR/" "$SRC_SNAPSHOT_DIR/"
    return 0
  fi

  (
    cd "$ROOT_DIR"
    git archive --format=tar HEAD
  ) | tar -xf - -C "$SRC_SNAPSHOT_DIR"
}

apply_whitelist() {
  shopt -s dotglob nullglob
  local path
  for path in "$SRC_SNAPSHOT_DIR"/*; do
    local name keep
    name="$(basename "$path")"
    keep="false"
    for allowed in "${WHITELIST_ITEMS[@]}"; do
      if [ "$name" = "$allowed" ]; then
        keep="true"
        break
      fi
    done
    if [ "$keep" != "true" ]; then
      rm -rf "$path"
    fi
  done
  shopt -u dotglob nullglob
}

sanitize_snapshot() {
  rm -f "$SRC_SNAPSHOT_DIR/.env"
  find "$SRC_SNAPSHOT_DIR" -maxdepth 1 -type f -name ".env*" ! -name ".env.example" -delete

  rm -rf \
    "$SRC_SNAPSHOT_DIR/data" \
    "$SRC_SNAPSHOT_DIR/docs/cap" \
    "$SRC_SNAPSHOT_DIR/docs/qa" \
    "$SRC_SNAPSHOT_DIR/reports" \
    "$SRC_SNAPSHOT_DIR/.github" \
    "$SRC_SNAPSHOT_DIR/.idea" \
    "$SRC_SNAPSHOT_DIR/.venv" \
    "$SRC_SNAPSHOT_DIR/.worktrees" \
    "$SRC_SNAPSHOT_DIR/backend/tests" \
    "$SRC_SNAPSHOT_DIR/backend/vendor" \
    "$SRC_SNAPSHOT_DIR/backend/app/security" \
    "$SRC_SNAPSHOT_DIR/frontend/lib/security"

  if [ -d "$SRC_SNAPSHOT_DIR/infra/offline" ]; then
    find "$SRC_SNAPSHOT_DIR/infra/offline" -maxdepth 1 -type f -name "*.tar" -delete
  fi

  if [ -d "$SRC_SNAPSHOT_DIR/scripts" ]; then
    rm -f \
      "$SRC_SNAPSHOT_DIR/scripts/security_gate.py" \
      "$SRC_SNAPSHOT_DIR/scripts/session_incident_gate.py"
    find "$SRC_SNAPSHOT_DIR/scripts" -maxdepth 1 -type f -name "*.applescript" -delete
  fi
}

sanitize_public_readmes() {
  cat > "$SRC_SNAPSHOT_DIR/README.md" <<'EOF'
# OncoNavAI (Public Snapshot)

Публичная укороченная версия репозитория для демонстрации архитектуры, интерфейсов и структуры проекта.

## Состав
- `backend/` — серверная логика и API
- `frontend/` — интерфейс и клиентская логика
- `infra/` — docker compose и окружение
- `scripts/` — служебные утилиты

## Быстрый старт (локально)
```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build -d
```

## Ограничения публичной версии
- часть внутренних и служебных компонентов удалена;
- тестовые наборы и vendor-артефакты не публикуются;
- репозиторий предназначен для ознакомления и презентации.

## Лицензия
См. `LICENSE` и `COPYRIGHT`.
EOF

  cat > "$SRC_SNAPSHOT_DIR/README.en.md" <<'EOF'
# OncoNavAI (Public Snapshot)

This is a shortened public repository intended for architecture and product demos.

## Included
- `backend/` — server-side logic and API
- `frontend/` — UI and client logic
- `infra/` — docker compose and runtime config
- `scripts/` — helper utilities

## Quick start (local)
```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build -d
```

## Public snapshot scope
- selected internal/service components are removed;
- test suites and vendor artifacts are not published;
- repository is intended for review and presentation.

## License
See `LICENSE` and `COPYRIGHT`.
EOF
}

write_manifest() {
  local whitelist_joined blocklist_joined
  whitelist_joined="$(IFS=:; echo "${WHITELIST_ITEMS[*]}")"
  blocklist_joined="$(IFS=:; echo "${BLOCKLIST_ITEMS[*]}")"

  ONCO_PUBLIC_SOURCE_REPO="$SOURCE_REPO" \
  ONCO_PUBLIC_SOURCE_COMMIT="$SOURCE_COMMIT" \
  ONCO_PUBLIC_EXPORTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  ONCO_PUBLIC_WHITELIST="$whitelist_joined" \
  ONCO_PUBLIC_BLOCKLIST="$blocklist_joined" \
  ONCO_PUBLIC_MANIFEST_PATH="$SRC_SNAPSHOT_DIR/PUBLIC_EXPORT_MANIFEST.json" \
  python3 - <<'PY'
import json
import os
from pathlib import Path

manifest = {
    "source_repo": os.environ.get("ONCO_PUBLIC_SOURCE_REPO", ""),
    "source_commit": os.environ.get("ONCO_PUBLIC_SOURCE_COMMIT", ""),
    "exported_at_utc": os.environ.get("ONCO_PUBLIC_EXPORTED_AT", ""),
    "whitelist": [x for x in os.environ.get("ONCO_PUBLIC_WHITELIST", "").split(":") if x],
    "blocklist": [x for x in os.environ.get("ONCO_PUBLIC_BLOCKLIST", "").split(":") if x],
}
path = Path(os.environ["ONCO_PUBLIC_MANIFEST_PATH"])
path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
PY
}

run_security_gate() {
  python3 "$ROOT_DIR/scripts/security_gate.py" \
    --repo-root "$SRC_SNAPSHOT_DIR" \
    --sbom-out "$RUN_DIR/sbom_manifest.json" \
    --strict
}

run_regex_gate() {
  local high_risk_pattern assignment_pattern safe_hints_joined
  local high_risk_hits_file assignment_hits_file merged_hits_file findings_file
  high_risk_pattern='-----BEGIN [A-Z ]*PRIVATE KEY-----|\bghp_[A-Za-z0-9]{36}\b|\bAKIA[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9]{20,}\b'
  assignment_pattern='(?i)\b(token|secret|password)\b[^=\n:]{0,40}[:=][^#\n]*'

  high_risk_hits_file="$RUN_DIR/high_risk_hits.txt"
  assignment_hits_file="$RUN_DIR/assignment_hits.txt"
  merged_hits_file="$RUN_DIR/merged_hits.txt"
  findings_file="$RUN_DIR/regex_findings.txt"

  rg -n --no-heading --color=never -I -g '!.git/**' -e "$high_risk_pattern" "$SRC_SNAPSHOT_DIR" >"$high_risk_hits_file" || true
  rg -n --no-heading --color=never -I -g '!.git/**' -e "$assignment_pattern" "$SRC_SNAPSHOT_DIR" >"$assignment_hits_file" || true
  cat "$high_risk_hits_file" "$assignment_hits_file" >"$merged_hits_file"
  safe_hints_joined="$(IFS=:; echo "${SAFE_HINTS[*]}")"

  ONCO_PUBLIC_SAFE_HINTS="$safe_hints_joined" \
  python3 - "$merged_hits_file" "$findings_file" <<'PY'
import os
import re
import sys

safe_hints = [x.strip().lower() for x in os.environ.get("ONCO_PUBLIC_SAFE_HINTS", "").split(":") if x.strip()]
high_risk_re = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bghp_[A-Za-z0-9]{36}\b|\bAKIA[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9]{20,}\b")

if len(sys.argv) != 3:
    raise SystemExit("expected paths: <hits_in> <findings_out>")
hits_path = sys.argv[1]
findings_path = sys.argv[2]

seen = set()
findings = []
with open(hits_path, "r", encoding="utf-8", errors="ignore") as handle:
    for raw in handle:
        line = raw.rstrip("\n")
        if not line or line in seen:
            continue
        seen.add(line)
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        path, _, content = parts
        content_lower = content.lower()
        if any(hint in content_lower for hint in safe_hints):
            continue
        if high_risk_re.search(content):
            findings.append(line)
            continue

        # Assignment candidates are limited to config-like files to avoid noisy code/doc hits.
        lower_path = path.lower()
        filename = lower_path.rsplit("/", 1)[-1]
        config_exts = (".env", ".ini", ".cfg", ".conf", ".toml", ".yaml", ".yml", ".json")
        is_config_like = filename.startswith(".env") or lower_path.endswith(config_exts)
        if not is_config_like:
            continue

        # Assignment candidates for token|secret|password with non-placeholder values.
        if path.endswith(".md"):
            continue
        marker = "=" if "=" in content else (":" if ":" in content else "")
        if not marker:
            continue
        rhs = content.split(marker, 1)[1].strip().strip("'\"")
        rhs_lower = rhs.lower()
        if not rhs:
            continue
        if any(hint in rhs_lower for hint in safe_hints):
            continue
        if rhs_lower in {"true", "false", "none", "null", "0", "1"}:
            continue
        if rhs.startswith("$") or "${" in rhs:
            continue
        if "://" in rhs:
            continue
        if "/" in rhs and " " not in rhs:
            continue
        if rhs.startswith("<") and rhs.endswith(">"):
            continue
        findings.append(line)

with open(findings_path, "w", encoding="utf-8") as handle:
    if findings:
        handle.write("\n".join(findings) + "\n")
PY

  if [ -s "$findings_file" ]; then
    echo "regex security gate found suspicious lines:" >&2
    cat "$findings_file" >&2
    return 1
  fi
  return 0
}

prepare_public_repo() {
  local fetch_log
  fetch_log="$RUN_DIR/fetch.log"
  git init "$PUBLIC_CLONE_DIR" >/dev/null
  git -C "$PUBLIC_CLONE_DIR" remote add origin "$PUBLIC_REPO_URL"
  if git -C "$PUBLIC_CLONE_DIR" fetch --depth 1 origin "$BRANCH" >"$fetch_log" 2>&1; then
    git -C "$PUBLIC_CLONE_DIR" checkout -B "$BRANCH" FETCH_HEAD >/dev/null
  else
    if rg -q "couldn't find remote ref|fatal: couldn't find remote ref" "$fetch_log"; then
      # Empty/new repository without target branch yet.
      git -C "$PUBLIC_CLONE_DIR" checkout --orphan "$BRANCH" >/dev/null
    else
      echo "error: unable to fetch remote branch '$BRANCH' from '$PUBLIC_REPO_URL'" >&2
      cat "$fetch_log" >&2
      return 1
    fi
  fi
}

sync_snapshot_to_public_repo() {
  rsync -a --delete --exclude ".git/" "$SRC_SNAPSHOT_DIR/" "$PUBLIC_CLONE_DIR/"
}

publish_changes() {
  git -C "$PUBLIC_CLONE_DIR" add -A

  if git -C "$PUBLIC_CLONE_DIR" diff --cached --quiet; then
    echo "No changes to publish"
    return 0
  fi

  if [ "$DRY_RUN" = "true" ]; then
    local dry_message
    dry_message="${COMMIT_MESSAGE:-chore(public): sanitized sync from $SOURCE_SHORT_SHA}"
    echo "[dry-run] Changes staged for commit: $dry_message"
    git -C "$PUBLIC_CLONE_DIR" status --short
    return 0
  fi

  local final_commit_message
  final_commit_message="${COMMIT_MESSAGE:-chore(public): sanitized sync from $SOURCE_SHORT_SHA}"
  if ! git -C "$PUBLIC_CLONE_DIR" commit -m "$final_commit_message" >/dev/null; then
    return 1
  fi

  if [ "$NO_PUSH" = "true" ]; then
    echo "Commit created with --no-push: $final_commit_message"
    return 0
  fi

  if ! git -C "$PUBLIC_CLONE_DIR" push origin "$BRANCH"; then
    return 1
  fi
  echo "Published sanitized snapshot to $PUBLIC_REPO_URL ($BRANCH)"
}

main() {
  parse_args "$@"

  require_cmd git
  require_cmd rsync
  require_cmd python3
  require_cmd rg
  require_cmd tar

  collect_source_meta
  setup_runtime_dirs

  create_source_snapshot || die "$EXIT_RUNTIME" "failed to create source snapshot"
  apply_whitelist
  sanitize_snapshot
  sanitize_public_readmes
  write_manifest

  run_security_gate || die "$EXIT_SECURITY" "security_gate.py reported findings"
  run_regex_gate || die "$EXIT_SECURITY" "regex security gate reported suspicious content"

  prepare_public_repo || die "$EXIT_GIT" "failed to initialize/fetch public repository"
  sync_snapshot_to_public_repo || die "$EXIT_GIT" "failed to sync snapshot to public repository"
  publish_changes || die "$EXIT_GIT" "failed to publish changes"
}

main "$@"
