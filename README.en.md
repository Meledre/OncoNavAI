# OncoAI (MVP+, LLM + RAG)

Language: [Русский](README.md) | **English**

OncoAI is an MVP+ clinical decision-support service for oncology treatment-plan verification with doctor/patient/admin flows, dual contracts (`legacy v0.1 + legacy v0.2`) plus bridge support for `pack v0.2`, RAG retrieval, and deterministic safety fallbacks.

## 1) Project Status

- Stage: **v0.5 auth/session hardening (without VPS deployment)**.
- Integration branch: `codex/v0-4-bridge-finalization`.
- Stage focus: LLM+RAG parity + fallback reliability + UX/contracts/security.
- Latest quality gates:
- `PYTHONPATH=. pytest backend/tests -q` -> `143 passed`
  - Frontend: `docker compose ... run --rm --no-deps --build frontend sh -lc 'npm run lint && npm run build'` -> pass
  - `npm audit --json` -> `0 vulnerabilities`
  - E2E smoke (`schema_version=0.2`) -> pass (`issues=1`, `patient_explain=true`)

## 2) Clinical Disclaimer

The system does not prescribe treatment and is not a substitute for physician judgment. It must be used only with anonymized/synthetic cases as a verification/explanation aid.

## 3) Implemented Scope

- Backend (FastAPI):
  - `/health`, `/analyze`, `/admin/*`, `/report/*`
  - 6-step analyze orchestration: validation -> normalize -> retrieve/rerank -> doctor report -> patient explain -> response/logging
  - Dual contract support `legacy schema_version=0.1|0.2` + bridge path for `pack 0.2`
  - `run_meta`, `insufficient_data`, evidence integrity enforcement
- Frontend (Next.js App Router):
  - Pages: `/doctor`, `/patient`, `/admin`
  - BFF API routes in `frontend/app/api/*`
  - Unified BFF error taxonomy (`BFF_*`)
- RAG:
  - PDF ingestion with page fidelity metadata
  - Vector backend abstraction: local + qdrant REST
  - Embeddings: `hash` + OpenAI-compatible backend
  - Rerank: `lexical` + `llm` fallback
- Security:
  - PII detection
  - RBAC normalization
  - Rate-limit hardening
  - Constant-time demo token compare
  - Safe logging
- QA/Observability:
  - smoke/E2E/metrics/load scripts
  - regression checklist + daily logs in `docs/cap`

## 4) Repository Layout

- `backend/` — FastAPI app, RAG, security, contract schemas, tests
- `frontend/` — Next.js UI + BFF
- `scripts/` — smoke/metrics/deploy utilities
- `infra/` — docker compose + production/deploy configs
- `docs/` — architecture, deploy docs, CAP logs, contracts
- `data/` — local runtime artifacts (docs/reports/sqlite)
- `reports/metrics/` — metrics snapshots

## 5) Requirements

Minimum:

- Docker Desktop + Docker Compose
- Python 3.10+ (for local scripts/tests)
- Node.js 20.19+ (if frontend is run locally, outside Docker)
- GNU Make (optional, for `make bootstrap` and short aliases)

## 6) Quick Start (Short Command)

For new contributors right after `git clone`:

```bash
./onco bootstrap
```

If executable bit is not preserved on your machine:

```bash
bash ./onco bootstrap
```

What `./onco bootstrap` does:

1. Creates `.env` from `.env.example` if missing.
2. Starts the Docker stack in background (`backend + frontend`).
3. Prints the current container status.

After startup:

- UI: `http://localhost:3000`
- Backend health: `http://localhost:8000/health`
- Start at `http://localhost:3000/` and select a role (session login).

### 6.1 Make Alternative

```bash
make bootstrap
```

### 6.2 Full Profile (Qdrant + vLLM)

```bash
./onco up --full
```

or:

```bash
make up-full
```

### 6.3 Manual Mode (without `onco`)

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build -d
```

### 6.4 Common `onco` Commands

```bash
./onco help
./onco status
./onco logs backend
./onco health
./onco governance
./onco smoke
./onco idp-smoke
./onco case-smoke
./onco incident-check
./onco metrics
./onco load
./onco frontend-check
./onco preflight
./onco test
./onco down
```

## 7) Runtime Modes

### 7.1 Baseline (recommended for local/CI stability)

- `VECTOR_BACKEND=local`
- `EMBEDDING_BACKEND=hash`
- `RERANKER_BACKEND=lexical`
- `LLM_PROBE_ENABLED=false` (low latency + deterministic path)

### 7.2 Full profile (Qdrant + vLLM)

```bash
docker compose -f infra/docker-compose.yml --profile full up -d
```

Additional profile services:

- Qdrant: `localhost:6333`
- vLLM OpenAI-compatible: `localhost:8001`

## 7.3 Demo Quick Start (low-load)

Local LLM demo (Ollama + Qdrant, low load, `C16` + mandatory PDF page-flow):

```bash
ONCOAI_DEMO_REQUIRE_LLM=true ./onco demo-local-smoke
```

API demo (OpenAI, low traffic, `C16` + mandatory PDF page-flow):

```bash
ONCOAI_DEMO_REQUIRE_LLM=true ./onco demo-api-smoke
```

Optional debug override to skip PDF acceptance:

```bash
ONCOAI_DEMO_SKIP_PDF_PAGE_FLOW=true ./onco demo-local-smoke
```

## 8) Environment Variables (.env)

Core:

- `RATE_LIMIT_PER_MINUTE` — analyze rate limit per client
- `DEMO_TOKEN` — required token for backend/BFF calls
- `LOCAL_CORE_BASE_URL` — core backend base URL

LLM providers:

- `LLM_PRIMARY_URL`, `LLM_PRIMARY_MODEL`, `LLM_PRIMARY_API_KEY`
- `LLM_FALLBACK_URL`, `LLM_FALLBACK_MODEL`, `LLM_FALLBACK_API_KEY`
- `LLM_GENERATION_ENABLED=true|false` (default `false` for deterministic local/CI path)
- `LLM_PROBE_ENABLED=true|false`

RAG/vector:

- `VECTOR_BACKEND=local|qdrant`
- `QDRANT_URL`, `QDRANT_COLLECTION`
- `RETRIEVAL_TOP_K`, `RERANK_TOP_N`
- `RERANKER_BACKEND=lexical|llm`
- `RAG_ENGINE=basic|llamaindex` (default: `basic`)

For `RAG_ENGINE=llamaindex`, install the optional dependency:

```bash
pip install -r backend/requirements-llamaindex.txt
```

If the runtime is unavailable, the service safely falls back to `basic` and records the reason in `run_meta.fallback_reason`.

Embeddings:

- `EMBEDDING_BACKEND=hash|openai`
- `EMBEDDING_URL`, `EMBEDDING_MODEL`, `EMBEDDING_API_KEY`

Frontend/BFF:

- `BACKEND_URL` (compose frontend: `http://backend:8000`; local frontend: `http://localhost:8000`)
- `ROLE_COOKIE_SECRET` (HMAC secret used to sign server-side session cookies for BFF auth)
- `SESSION_AUTH_MODE=demo|credentials|idp` (default `demo`)
- `SESSION_USERS_JSON` (required for `SESSION_AUTH_MODE=credentials`; user array format `[{ "user_id": "clinician-1", "username": "clinician", "password": "sha256:<hex>|plain", "role": "clinician", "active": true }]`)
- `SESSION_IDP_ISSUER`, `SESSION_IDP_AUDIENCE`, `SESSION_IDP_JWKS_URL` (used in bridge mode when `SESSION_AUTH_MODE=idp`)
- `SESSION_IDP_JWKS_JSON` (optional inline JWKS JSON for local/staging without external fetch)
- `SESSION_IDP_HS256_SECRET` (optional HS256 token validation for local bridge mode)
- `SESSION_IDP_ROLE_CLAIM` (default `role`), `SESSION_IDP_USER_ID_CLAIM` (default `sub`)
- `SESSION_IDP_USER_ID_REGEX` (default `^[A-Za-z0-9._:@-]{1,120}$`; policy for accepted `user_id` claim, otherwise `idp_user_id_invalid_format`)
- `SESSION_IDP_ALLOWED_ALGS` (default `RS256,HS256`)
- `SESSION_IDP_ALLOWED_ROLES` (default `admin,clinician,patient`)
- `SESSION_IDP_CLOCK_SKEW_SEC` (default `60`, leeway for `exp/nbf/iat`, range `0..300`)
- `SESSION_IDP_REQUIRE_JTI` (default `true`, requires `jti` claim for anti-replay)
- `SESSION_IDP_REQUIRE_NBF` (default `false`; when `true`, `nbf` claim is required)
- `SESSION_IDP_REPLAY_CHECK_ENABLED` (default `true`, backend replay reserve check on `/session/idp/replay/reserve`)
- `SESSION_LOGIN_RATE_LIMIT_PER_MINUTE` (brute-force guard for `POST /api/session/login`, default `60`; set `0` to disable)
- `SESSION_LOGIN_RATE_LIMIT_WINDOW_SEC` (login rate-limit window in seconds, default `60`, range `10..600`)
- `SESSION_LOGIN_RATE_LIMIT_KEY_MODE=global|ip` (default `global`; use `ip` only behind a trusted proxy)
- `SESSION_TRUST_PROXY_HEADERS=true|false` (default `false`; when `true`, login rate-limit key uses `x-forwarded-for`/`x-real-ip`)
- `SESSION_CSRF_ENFORCED=true|false` (default `true`; same-origin guard for mutating session routes `/api/session/login|logout|revoke`)
- `SESSION_CSRF_TRUSTED_ORIGINS` (optional comma-separated trusted origins for CSRF checks)
- `SESSION_CSRF_ALLOW_UNKNOWN_CONTEXT=true|false` (default `true`; allows CLI/smoke requests without `Origin/Referer/Sec-Fetch-Site`)
- `SESSION_AUDIT_MAX_EVENTS` (max local fallback/UI audit ring buffer, default `500`; primary audit is persisted in backend SQLite)
- `SESSION_AUDIT_RETENTION_DAYS` (backend audit retention in days, default `90`, range `1..3650`)
- `SESSION_AUDIT_ALERT_MIN_EVENTS` (minimum events in the window before deny-rate alerts are evaluated, default `10`)
- `SESSION_AUDIT_ALERT_DENY_RATE_WARN` / `SESSION_AUDIT_ALERT_DENY_RATE_CRITICAL` (deny-rate thresholds for `warn|critical`, default `0.35|0.60`)
- `SESSION_AUDIT_ALERT_ERROR_COUNT_WARN` / `SESSION_AUDIT_ALERT_ERROR_COUNT_CRITICAL` (thresholds for `outcome=error`, default `5|20`)
- `SESSION_AUDIT_ALERT_REPLAY_COUNT_WARN` / `SESSION_AUDIT_ALERT_REPLAY_COUNT_CRITICAL` (thresholds for `idp_token_replay_detected`, default `1|3`)
- `SESSION_AUDIT_ALERT_CONFIG_ERROR_COUNT_WARN` / `SESSION_AUDIT_ALERT_CONFIG_ERROR_COUNT_CRITICAL` (thresholds for auth config errors, default `1|3`)
- `SESSION_ACCESS_TTL_SEC` (access-cookie TTL, default `900`)
- `SESSION_REFRESH_TTL_SEC` (refresh-cookie TTL, default `604800`)
- `CASE_IMPORT_ALLOW_FULL_MODE=true|false` (default `false`; enables FULL-mode imports only for private secured deployments)
- `CASE_IMPORT_FULL_REQUIRE_ACK=true|false` (default `true`; FULL-mode requires `full_mode_acknowledged=true`)
- `CASE_IMPORT_DEID_REDACT_PII=true|false` (default `true`; redacts detected PII fragments in DEID imports)

Build mode:

- `PIP_INSTALL_MODE=online|offline`
- `NPM_INSTALL_MODE=online|offline`

CLI overrides (for `./onco`):

- `ONCOAI_UI_URL` (default `http://localhost:3000`)
- `ONCOAI_BACKEND_URL` (default `http://localhost:8000`)
- `ONCOAI_SCHEMA_VERSION` (default `0.2`)
- `ONCOAI_DEMO_TOKEN` (if you need to override `DEMO_TOKEN` only for CLI commands)
- `ONCOAI_DEMO_REINDEX_POLLS` (max polling attempts for `admin/reindex` in demo commands, default `120`)
- `ONCOAI_DEMO_DATA_SCOPE_SUFFIX` (suffix for demo data-dir; if unset, `./onco demo-*` uses a timestamp and starts from a clean demo store)
- `ONCOAI_DEMO_REQUIRE_LLM=true|false` (enables strict LLM path gate for `demo-local-smoke`/`demo-api-smoke`)
- `ONCOAI_DEMO_LOCAL_WITH_VLLM=true|false` (force `vllm` profile in `demo-local-smoke`; by default it is started only when needed)
- `ONCOAI_DEMO_ALLOW_API_EMBED_FALLBACK=true|false` (allows `demo-api-smoke` to run without API embedding key via `hash`; default `false`, so a real API key is required)
- `ONCOAI_DEMO_LOCAL_MULTI_ONCO_CASES` (default `C16` for low-load local demo)
- `ONCOAI_DEMO_API_MULTI_ONCO_CASES` (default `C16` for low-traffic API demo)
- `ONCOAI_DEMO_SKIP_PDF_PAGE_FLOW=true|false` (default `false`; disables PDF page-flow acceptance in demo commands)
- `ONCOAI_CASES_FILE`, `ONCOAI_IMPORT_CASES_FILE`, `ONCOAI_METRICS_OUT` (paths for `metrics/load/import-quality`)
- `ONCOAI_METRICS_WARMUP_CASES` (number of initial cases excluded from latency stats, default `3`)
- `ONCOAI_METRICS_P95_GATE` (default `120`)
- `ONCOAI_LOAD_P95_GATE` (default `200`)
- `ONCOAI_MIN_RECALL_GATE` (default `1.0`)
- `ONCOAI_MIN_EVIDENCE_VALID_GATE` (default `1.0`)
- `ONCOAI_REQUIRED_IMPORT_PROFILES` (default `FREE_TEXT,KIN_PDF,FHIR_BUNDLE`)
- `ONCOAI_MIN_IMPORT_SUCCESS_GATE` (default `1.0`)
- `ONCOAI_MIN_IMPORT_PROFILE_COVERAGE_GATE` (default `1.0`)
- `ONCOAI_MIN_IMPORT_REQUIRED_FIELD_COVERAGE_GATE` (default `1.0`)
- `ONCOAI_MIN_IMPORT_DATA_MODE_COVERAGE_GATE` (default `1.0`)
- `ONCOAI_SESSION_INCIDENT_WINDOW_HOURS` (incident summary window for gate, default `24`)
- `ONCOAI_SESSION_INCIDENT_FAIL_ON` (fail threshold for incident gate: `off|none|low|medium|high`, default `high`)
- `ONCOAI_SESSION_INCIDENT_MAX_CRITICAL_ALERTS` (max critical alerts, `-1` disables check)
- `ONCOAI_SESSION_INCIDENT_MAX_WARN_ALERTS` (max warn alerts, `-1` disables check)

## 8.1 Demo Troubleshooting

- `sqlite3.OperationalError: unable to open database file`:
  verify `ONCOAI_DATA_DIR` and `ONCOAI_DB_PATH` (empty values are invalid), then run `./onco up` and `./onco health`.
- `demo-local-smoke` fails with missing Ollama model:
  run `docker compose -f infra/docker-compose.yml --profile full up -d ollama` and let `./onco demo-local-smoke` pull the model.
- `demo-api-smoke` fails due to keys:
  verify `LLM_PRIMARY_API_KEY`/`OPENAI_API_KEY` and `EMBEDDING_API_KEY` (or enable `ONCOAI_DEMO_ALLOW_API_EMBED_FALLBACK=true`).
- `admin/reindex` is slow through BFF:
  increase `ONCOAI_DEMO_REINDEX_POLLS` and check `backend`/`frontend` logs.

## 9) API Surface

Backend endpoints:

- `GET /health`
- `POST /analyze`
- `GET /admin/docs`
- `POST /admin/upload`
- `POST /admin/reindex`
- `GET /admin/reindex/{job_id}`
- `GET /admin/docs/{doc_id}/{doc_version}/pdf`
- `POST /case/import`
- `GET /case/import/runs?limit=20`
- `GET /case/import/{import_run_id}`
- `GET /case/{case_id}`
- `GET /report/{report_id}.json`
- `GET /report/{report_id}.html`
- `POST /session/check` (internal BFF session access check)
- `POST /session/revoke` (internal BFF session revocation/forced logout persistence)
- `POST /session/audit` (internal BFF session audit event write)
- `GET /session/audit` (admin session audit read)
- `GET /session/audit/summary` (admin session security telemetry summary for a time window)
- `POST /session/idp/replay/reserve` (internal anti-replay reserve for idp `jti`)

Required headers for direct backend calls:

- `x-role`
- `x-demo-token`
- (optional for `/analyze`) `x-client-id`

For BFF (`/api/*`), client-provided `x-role` is no longer trusted:

- role is resolved only from signed server-side session cookies (`session_access/session_access_sig`, with fallback to `session_refresh/session_refresh_sig`);
- missing/invalid role returns `401 BFF_AUTH_REQUIRED`;
- disallowed role for endpoint returns `403 BFF_FORBIDDEN`.

Session endpoints (frontend):

- `GET|POST /api/session/login`
- `GET|POST /api/session/logout`
- `GET /api/session/me`
- `POST /api/session/revoke` (self revoke or admin forced logout by `user_id`)
- `GET /api/session/audit` (admin-only session audit events + revoked session IDs sample)
- `GET /api/session/audit/summary` (admin-only `Auth Risk Snapshot`: `total_events/outcomes/top_reasons` + `incident_level/incident_score/incident_signals/alerts`)
- `GET /api/session/audit/export` (admin-only audit export in `json|csv`; supports `all=1` to walk all cursor pages)
- session revoke/audit state is persisted in backend shared storage (SQLite), not only frontend process memory.
- refresh-token rotation is enabled: refresh-authenticated requests issue new cookies and immediately revoke the used refresh `session_id` (`refresh_rotation`).
- `GET /api/session/audit` supports filters/pagination: `limit`, `outcome`, `event`, `reason`, `reason_group`, `user_id`, `correlation_id`, `from_ts`, `to_ts`, `cursor` (response includes `next_cursor`).
- `POST /api/session/login`, `POST /api/session/logout`, `POST /api/session/revoke` are protected with same-origin CSRF guard; reject reason: `csrf_origin_mismatch|csrf_context_missing_or_cross_site`.
- `GET /api/session/audit/export` supports the same filters plus `format=json|csv`, `all=0|1`, `max_pages`, `max_events` (bounded, hard cap).
- Export numeric params (`limit`, `max_pages`, `max_events`) are strictly validated; invalid/out-of-range values return `400 BFF_BAD_REQUEST`.
- `from_ts/to_ts` use strict ISO timestamp parsing with UTC normalization; invalid format or inverted range (`from_ts > to_ts`) returns backend `400 ValidationError`.
- CSV export is hardened against spreadsheet-formula injection: values starting with `=`, `+`, `-`, `@` (including leading whitespace) are prefixed with `'`.
- Export responses include guard headers: `x-onco-export-max-events`, `x-onco-export-truncated`, `x-onco-export-truncated-reason`.
- `scripts/e2e_smoke.py` now validates audit export runtime path (`/api/session/audit/export`) in both JSON and CSV modes (headers + basic payload format), including truncation path (`max_events=1`).

Login modes:

- `SESSION_AUTH_MODE=demo`: role-based login (`role`) for local demo flow.
- `SESSION_AUTH_MODE=credentials`: login only via `POST /api/session/login` with `username/password`; role is resolved from `SESSION_USERS_JSON`.
- `SESSION_AUTH_MODE=idp`: `GET /api/session/login` remains disabled for interactive login, while `POST /api/session/login` acts as token exchange (`id_token` or `Authorization: Bearer ...`) and issues server-side session cookies after signature/claim validation; anti-replay (`jti`) and clock-skew leeway checks are enabled by default.

BFF endpoints (frontend):

- `/api/analyze`
- `/api/admin/docs`
- `/api/admin/upload`
- `/api/admin/reindex`
- `/api/admin/reindex/[job_id]`
- `/api/admin/docs/[doc_id]/[doc_version]/pdf`
- `/api/case/import`
- `/api/case/import/runs`
- `/api/case/import/[import_run_id]`
- `/api/case/[case_id]`
- `/api/report/[slug]/json`
- `/api/report/[slug]/html`
- legacy-compatible: `/api/report/[slug]` (`.json`/`.html`)

BFF error codes:

- `BFF_BAD_REQUEST`
- `BFF_AUTH_REQUIRED`
- `BFF_FORBIDDEN`
- `BFF_UPSTREAM_VALIDATION_ERROR`
- `BFF_UPSTREAM_AUTH_ERROR`
- `BFF_UPSTREAM_NOT_FOUND`
- `BFF_UPSTREAM_RATE_LIMITED`
- `BFF_UPSTREAM_HTTP_ERROR`
- `BFF_UPSTREAM_NETWORK_ERROR`

BFF JSON error shape:

- Canonical field: `error_code`
- Backward-compatible alias: `code`

BFF tracing:

- BFF forwards `x-correlation-id` to backend and returns the same header to clients.
- For JSON errors, BFF includes `correlation_id` in the payload.

## 10) Contract Versions and Request Dialects

- `legacy v0.1` remains backward-compatible.
- `legacy v0.2` adds richer clinical structure (`case.patient`, `diagnosis`, `biomarkers`, etc.), `run_meta`, and explicit `insufficient_data`.
- `pack v0.2` (`onco_json_pack`) is accepted through a bridge adapter: backend normalizes request to internal analyze payload and returns a pack-compatible response.
- `pack v0.2` supports `case_id` flow: when `case.case_json` is omitted, backend resolves `case.case_id` from local case storage (`POST /case/import` -> `POST /analyze`).
- `run_meta` keeps `report_generation_path`, `retrieval_engine`, optional `fallback_reason`; pack responses use mapped enums (`primary|fallback|deterministic_only`).

Contract spec:

- `docs/contracts/analyze_dual_support_v0_1_v0_2.md`
- Canonical pack schemas/examples/seeds: `docs/contracts/onco_json_pack_v1/`

Minimal v0.2 request example:

```json
{
  "schema_version": "0.2",
  "request_id": "demo-001",
  "case": {
    "cancer_type": "nsclc_egfr",
    "language": "ru",
    "patient": {"sex": "female", "age": 62},
    "diagnosis": {"stage": "IV"},
    "biomarkers": [{"name": "EGFR", "value": "L858R"}],
    "comorbidities": [],
    "contraindications": [],
    "notes": "Synthetic case"
  },
  "treatment_plan": {
    "plan_text": "Osimertinib 80 mg daily",
    "plan_structured": [{"step_type": "systemic_therapy", "name": "Osimertinib"}]
  },
  "return_patient_explain": true
}
```

## 11) Quality Gates and Validation Scenarios

Backend unit/regression:

```bash
PYTHONPATH=. pytest backend/tests -q
```

Frontend quality (local):

```bash
cd frontend
npm ci
npm run lint
npm run build
```

Local pre-release gate (single command):

```bash
./onco preflight
```

`./onco preflight` automatically restarts backend and waits for `/health` before runtime smoke checks; it runs both baseline smoke and `case-flow` smoke to avoid stale runtime after `backend/app` changes.

Session incident policy check:

```bash
./onco incident-check
```

Local security gate:

```bash
./onco security-check
```

Runs strict secret scanning and SBOM manifest generation (`reports/security/sbom_manifest.json`).

Local release-readiness gate:

```bash
./onco release-readiness
```

Runs `preflight` plus release-artifact validation (`reports/release/readiness_report.json`).

Public export to a separate sanitized GitHub repository:

```bash
./scripts/public_export.sh \
  --public-repo-url git@github.com:<public_account>/<public_repo>.git \
  --branch main \
  --dry-run
```

Full runbook: `docs/deploy/public-sanitized-export.md`.

Dedicated frontend runtime parity gate (rebuild + lint + build):

```bash
./onco frontend-check
```

E2E smoke:

```bash
python3 scripts/e2e_smoke.py --base-url http://localhost:3000 --schema-version 0.2
```

E2E case-flow smoke (`case import -> analyze(case_id)`):

```bash
python3 scripts/e2e_smoke.py --base-url http://localhost:3000 --schema-version 0.2 --case-flow
./onco case-smoke
```

E2E idp-mode smoke (`SESSION_AUTH_MODE=idp`, token exchange login):

```bash
ONCO_SMOKE_IDP_SECRET=dev-idp-secret \
ONCO_SMOKE_AUTH_MODE=idp \
python3 scripts/e2e_smoke.py --base-url http://localhost:3000 --schema-version 0.2 --auth-mode idp

# If your environment has no secret for generating negative test tokens:
# ONCO_SMOKE_REQUIRE_IDP_NEGATIVE=false
# Or provide pre-signed negative tokens (for example RS256):
# ONCO_SMOKE_IDP_NEG_TOKEN_MISSING_USER_ID=...
# ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_USER_ID=...
# ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_ROLE=...
# ONCO_SMOKE_IDP_NEG_TOKEN_ISSUER_MISMATCH=...
# ONCO_SMOKE_IDP_NEG_TOKEN_AUDIENCE_MISMATCH=...
# ONCO_SMOKE_IDP_NEG_TOKEN_EXPIRED=...
# ONCO_SMOKE_IDP_NEG_TOKEN_NOT_YET_VALID=...
# ONCO_SMOKE_IDP_NEG_TOKEN_IAT_IN_FUTURE=...
# ONCO_SMOKE_IDP_NEG_TOKEN_MISSING_JTI=...
# ONCO_SMOKE_IDP_NEG_TOKEN_REPLAY=...
# ONCO_SMOKE_IDP_NEG_TOKEN_MALFORMED=...
# ONCO_SMOKE_IDP_NEG_TOKEN_ALG_NOT_ALLOWED=...
# ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_SIGNATURE=...
# ONCO_SMOKE_IDP_NEG_TOKEN_INVALID_SIGNATURE_REASON=idp_signature_invalid_rs256
# Optional: verify login rate-limit contract (429 + retry-after)
# ONCO_SMOKE_CHECK_LOGIN_RATE_LIMIT=true
# ONCO_SMOKE_LOGIN_RATE_LIMIT_PROBE_ATTEMPTS=120

# For short-command usage:
# 1) set SESSION_AUTH_MODE=idp and SESSION_IDP_HS256_SECRET in .env
# 2) restart frontend: ./onco restart frontend
./onco idp-smoke
```

Metrics harness:

```bash
python scripts/run_metrics.py \
  --base-url http://localhost:8000 \
  --token demo-token \
  --cases data/synthetic_cases/cases_v1_all.json \
  --import-cases data/synthetic_cases/import_cases_v0.json \
  --golden-pairs data/golden_answers/golden_pairs_v1_2_all.jsonl \
  --report-by-nosology \
  --required-import-profiles FREE_TEXT,KIN_PDF,FHIR_BUNDLE \
  --schema-version 0.2 \
  --out /tmp/onco_metrics_v03.json \
  --warmup-cases 3 \
  --max-p95-ms 120 \
  --min-recall-like 0.88 \
  --min-evidence-valid-ratio 0.95 \
  --max-insufficient-ratio 0.25 \
  --min-import-success-ratio 0.95 \
  --min-import-profile-coverage 1.0 \
  --min-import-required-field-coverage 0.98 \
  --min-import-data-mode-coverage 1.0 \
  --max-sanity-fail-rate 0.05 \
  --min-citation-coverage 0.9 \
  --min-key-fact-retention 0.9 \
  --min-recall-like-by-nosology gastric:0.88,lung:0.88,breast:0.88,colorectal:0.88,prostate:0.88,rcc:0.88,bladder:0.88,brain:0.88 \
  --min-citation-coverage-by-nosology gastric:0.9,lung:0.9,breast:0.9,colorectal:0.9,prostate:0.9,rcc:0.9,bladder:0.9,brain:0.9
```

Load smoke:

```bash
python3 scripts/load_smoke.py \
  --base-url http://localhost:8000 \
  --token demo-token \
  --schema-version 0.2 \
  --parallel 5 \
  --requests 20 \
  --max-p95-ms 200 \
  --require-all-ok
```

## 12) Current Performance Baseline

Current snapshot (2026-02-18):

- HTTP metrics: `p50=6.81ms`, `p95=9.28ms`, `recall_like=1.0`, `evidence_valid_ratio=1.0`
- Load smoke: `ok=20/20`, `p50=28.1ms`, `p95=38.93ms`

Artifact:

- `/tmp/onco_metrics_v03.json`

## 13) Security Controls

Implemented controls:

- PII blocking in analyze flow
- RBAC enforcement for admin/clinician
- Rate limiting with explicit retry hints
- Constant-time demo token comparison
- Safe logging without raw case leakage

## 14) Known Limitations

- VPS deployment intentionally deferred for this stage.
- MVP nosology focus remains `nsclc_egfr`.
- `case_import` supports `FREE_TEXT`, `CUSTOM_TEMPLATE`, `FHIR_BUNDLE`, `KIN_PDF`; default mode is `data_mode=DEID`, optional `data_mode=FULL` is policy-gated.
- For `FHIR_BUNDLE`, import now extracts `Procedure`/`MedicationRequest`/`MedicationStatement` into case `timeline` and fills `last_plan.line/cycle` when available.
- Case import run tracking endpoints are available: `GET /case/import/runs`, `GET /case/import/{import_run_id}`.
- FULL-mode policy is enforced: when `CASE_IMPORT_ALLOW_FULL_MODE=false`, import fails with `FULL_MODE_DISABLED`; when enabled and `CASE_IMPORT_FULL_REQUIRE_ACK=true`, `full_mode_acknowledged=true` is required.
- `eslint@10` is available but currently intentionally pinned to `eslint@9.39.2` due compatibility limits in the current `eslint-config-next@16.1.6` chain.

## 15) Troubleshooting

### 15.1 Docker build: `Network is unreachable`

Usually Docker networking/proxy/VPN issue, not an API key issue.

Check:

1. host internet access,
2. Docker Desktop proxy settings,
3. Docker access through VPN,
4. retry `docker compose ... up --build -d`.

### 15.2 Frontend dependency sync

If lockfile/peer dependency issues appear:

```bash
cd frontend
npm install --package-lock-only
npm ci
```

### 15.3 Backend not responding

```bash
docker compose -f infra/docker-compose.yml ps
docker compose -f infra/docker-compose.yml logs backend --tail=200
```

## 16) Stage Documentation

- Freeze summary: `docs/cap/v0_2_freeze_summary.md`
- Bridge freeze summary v0.4: `docs/cap/v0_4_bridge_freeze_summary.md`
- Daily logs: `docs/cap/daily_log_D12.md` ... `docs/cap/daily_log_D17.md`
- Regression checklist: `docs/qa/regression_checklist.md`
- Contracts: `docs/contracts/analyze_dual_support_v0_1_v0_2.md`

## 17) Deployment

VPS release is intentionally out of scope for this stage. For production delivery options see:

- `docs/deploy/prod-registry-digest-deploy.md`
- `docs/deploy/public-sanitized-export.md`
- `infra/.env.prod.example`
- GitHub workflows in `.github/workflows/`
