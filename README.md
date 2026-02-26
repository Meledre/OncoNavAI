# OncoAI (MVP+, LLM + RAG)

Язык: **Русский** | [English](README.en.md)

OncoAI — сервис поддержки клинической верификации онкологических планов лечения (MVP+), с разделением ролей врач/пациент/администратор, dual-контрактами `legacy v0.1 + legacy v0.2` и bridge-поддержкой `pack v0.2`, RAG-контуром и безопасными fallback-механизмами.

## 1) Статус проекта

- Этап: **v0.5 auth/session hardening (без деплоя на VPS)**.
- Ветка интеграции: `codex/v0-4-bridge-finalization`.
- Архитектурный фокус этапа: LLM+RAG parity + deterministic fallback, UX/контракты/безопасность.
- Последние quality-gates:
- `PYTHONPATH=. pytest backend/tests -q` -> `143 passed`
  - Frontend: `docker compose ... run --rm --no-deps --build frontend sh -lc 'npm run lint && npm run build'` -> pass
  - `npm audit --json` -> `0 vulnerabilities`
  - E2E smoke (`schema_version=0.2`) -> pass (`issues=1`, `patient_explain=true`)

## 2) Клинический дисклеймер

Система не назначает лечение и не заменяет врача. Использование допускается только для обезличенных или синтетических кейсов и как инструмент проверки/пояснения.

## 3) Что реализовано

- Backend (FastAPI):
  - `/health`, `/analyze`, `/admin/*`, `/report/*`
  - Пайплайн анализа в 6 шагах: validation -> normalize -> retrieve/rerank -> doctor report -> patient explain -> response/logging
- Dual support контрактов `legacy schema_version=0.1|0.2` + bridge для `pack 0.2`
  - `run_meta`, `insufficient_data`, evidence integrity
- Frontend (Next.js App Router):
  - Страницы: `/doctor`, `/patient`, `/admin`
  - BFF API: `frontend/app/api/*`
  - Unified BFF taxonomy ошибок (`BFF_*`)
- RAG:
  - Индексация PDF с page fidelity metadata
  - Векторный слой: local + qdrant REST
  - Embeddings: `hash` + OpenAI-compatible backend
  - Rerank: `lexical` + `llm` fallback
- Security:
  - PII detection
  - RBAC (role normalization)
  - Rate limit (edge-case hardened)
  - Constant-time demo token compare
  - Safe logging
- QA/observability:
  - Smoke/E2E, metrics harness, load smoke
  - Regression checklist + daily logs в `docs/cap`

## 4) Структура репозитория

- `backend/` — FastAPI сервис, RAG, security, схемы контрактов, тесты
- `frontend/` — Next.js UI + BFF
- `scripts/` — smoke/metrics/deploy утилиты
- `infra/` — docker compose и production/deploy конфиги
- `docs/` — архитектура, деплой, CAP логи, контракты
- `data/` — локальные артефакты (docs/reports/sqlite)
- `reports/metrics/` — отчеты метрик

## 5) Требования

Минимально:

- Docker Desktop + Docker Compose
- Python 3.10+ (для локальных скриптов/тестов)
- Node.js 20.19+ (если frontend запускается локально вне Docker)
- GNU Make (опционально, для `make bootstrap` и коротких алиасов)

## 6) Быстрый старт (короткая команда)

Для новых пользователей после `git clone`:

```bash
./onco bootstrap
```

Если на вашей машине не сохранился executable bit:

```bash
bash ./onco bootstrap
```

Что делает `./onco bootstrap`:

1. Создаёт `.env` из `.env.example` (если `.env` отсутствует).
2. Поднимает Docker-стек в фоне (`backend + frontend`).
3. Показывает статус контейнеров.

После запуска:

- UI: `http://localhost:3000`
- Backend health: `http://localhost:8000/health`
- Для входа откройте `http://localhost:3000/` и выберите роль (session login).

### 6.1 Альтернатива через Make

```bash
make bootstrap
```

### 6.2 Если нужен полный профиль (Qdrant + vLLM)

```bash
./onco up --full
```

или:

```bash
make up-full
```

### 6.3 Ручной режим (без `onco`)

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build -d
```

### 6.4 Базовые команды `onco`

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

## 7) Режимы запуска

### 7.1 Strict LLM+RAG only (рекомендуется для локального/прод прогона)

- `ONCOAI_REASONING_MODE=llm_rag_only`
- `LLM_GENERATION_ENABLED=true`
- `LLM_FALLBACK_URL=` (пусто; fallback отключен)
- `VECTOR_BACKEND=qdrant`
- `EMBEDDING_BACKEND=openai`
- `RERANKER_BACKEND=llm`

### 7.2 Compat (legacy для локальной/CI стабилизации)

- `VECTOR_BACKEND=local`
- `EMBEDDING_BACKEND=hash`
- `RERANKER_BACKEND=lexical`
- `LLM_PROBE_ENABLED=false` (минимальная latency и детерминированный путь)

### 7.3 Full profile (Qdrant + vLLM)

```bash
docker compose -f infra/docker-compose.yml --profile full up -d
```

Сервисы профиля:

- Qdrant: `localhost:6333`
- vLLM OpenAI-compatible: `localhost:8001`

## 7.4 Демо quick start (low-load)

Local LLM demo (Ollama + Qdrant, минимальная нагрузка, `C16` + обязательный PDF page-flow):

```bash
ONCOAI_DEMO_REQUIRE_LLM=true ./onco demo-local-smoke
```

API demo (OpenAI, минимальный трафик, `C16` + обязательный PDF page-flow):

```bash
ONCOAI_DEMO_REQUIRE_LLM=true ./onco demo-api-smoke
```

Опционально можно отключить PDF acceptance-проверку для отладки:

```bash
ONCOAI_DEMO_SKIP_PDF_PAGE_FLOW=true ./onco demo-local-smoke
```

## 8) Переменные окружения (.env)

Основные:

- `RATE_LIMIT_PER_MINUTE` — лимит запросов `/analyze` на клиента
- `DEMO_TOKEN` — обязательный токен для backend/BFF вызовов
- `LOCAL_CORE_BASE_URL` — базовый URL core backend

LLM провайдеры:

- `LLM_PRIMARY_URL`, `LLM_PRIMARY_MODEL`, `LLM_PRIMARY_API_KEY`
- `LLM_FALLBACK_URL`, `LLM_FALLBACK_MODEL`, `LLM_FALLBACK_API_KEY`
- `LLM_GENERATION_ENABLED=true|false` (для `llm_rag_only` должно быть `true`)
- `LLM_PROBE_ENABLED=true|false`
- `ONCOAI_REASONING_MODE=llm_rag_only|compat` (default: `llm_rag_only`)

RAG/векторы:

- `VECTOR_BACKEND=local|qdrant`
- `QDRANT_URL`, `QDRANT_COLLECTION`
- `RETRIEVAL_TOP_K`, `RERANK_TOP_N`
- `RERANKER_BACKEND=lexical|llm`
- `RAG_ENGINE=basic|llamaindex` (default: `basic`)

Для режима `RAG_ENGINE=llamaindex` нужно установить optional dependency:

```bash
pip install -r backend/requirements-llamaindex.txt
```

Если runtime недоступен, сервис автоматически вернётся к `basic` и запишет причину в `run_meta.fallback_reason`.

В режиме `ONCOAI_REASONING_MODE=llm_rag_only` деградационные fallback-пути запрещены: `run_meta.llm_path=primary`, `run_meta.report_generation_path=primary`, `run_meta.fallback_reason=none`.

Embeddings:

- `EMBEDDING_BACKEND=hash|openai`
- `EMBEDDING_URL`, `EMBEDDING_MODEL`, `EMBEDDING_API_KEY`

Frontend/BFF:

- `BACKEND_URL` (если frontend в compose: `http://backend:8000`; если локально: `http://localhost:8000`)
- `ROLE_COOKIE_SECRET` (секрет HMAC-подписи server-side session cookies для BFF)
- `SESSION_AUTH_MODE=demo|credentials|idp` (default `demo`)
- `SESSION_USERS_JSON` (обязателен для `SESSION_AUTH_MODE=credentials`; массив пользователей формата `[{ "user_id": "clinician-1", "username": "clinician", "password": "sha256:<hex>|plain", "role": "clinician", "active": true }]`)
- `SESSION_IDP_ISSUER`, `SESSION_IDP_AUDIENCE`, `SESSION_IDP_JWKS_URL` (используются в bridge-режиме `SESSION_AUTH_MODE=idp`)
- `SESSION_IDP_JWKS_JSON` (опционально: inline JWKS JSON для локального/staging контура без внешнего fetch)
- `SESSION_IDP_HS256_SECRET` (опционально: HS256 token validation для локального bridge)
- `SESSION_IDP_ROLE_CLAIM` (default `role`), `SESSION_IDP_USER_ID_CLAIM` (default `sub`)
- `SESSION_IDP_USER_ID_REGEX` (default `^[A-Za-z0-9._:@-]{1,120}$`, policy для `user_id` claim; при нарушении возвращается `idp_user_id_invalid_format`)
- `SESSION_IDP_ALLOWED_ALGS` (default `RS256,HS256`)
- `SESSION_IDP_ALLOWED_ROLES` (default `admin,clinician,patient`)
- `SESSION_IDP_CLOCK_SKEW_SEC` (default `60`, leeway для `exp/nbf/iat`, диапазон `0..300`)
- `SESSION_IDP_REQUIRE_JTI` (default `true`, обязательный `jti` claim для anti-replay)
- `SESSION_IDP_REQUIRE_NBF` (default `false`, если `true` — `nbf` обязателен)
- `SESSION_IDP_REPLAY_CHECK_ENABLED` (default `true`, backend reserve-check `jti` на `/session/idp/replay/reserve`)
- `SESSION_LOGIN_RATE_LIMIT_PER_MINUTE` (guard для brute-force на `POST /api/session/login`, default `60`; `0` отключает)
- `SESSION_LOGIN_RATE_LIMIT_WINDOW_SEC` (окно login rate-limit в секундах, default `60`, диапазон `10..600`)
- `SESSION_LOGIN_RATE_LIMIT_KEY_MODE=global|ip` (default `global`; `ip` использовать только за trusted proxy)
- `SESSION_TRUST_PROXY_HEADERS=true|false` (default `false`; при `true` для rate-limit key учитываются `x-forwarded-for`/`x-real-ip`)
- `SESSION_CSRF_ENFORCED=true|false` (default `true`; same-origin guard для mutating session routes `/api/session/login|logout|revoke`)
- `SESSION_CSRF_TRUSTED_ORIGINS` (опциональный comma-list trusted origins для CSRF check)
- `SESSION_CSRF_ALLOW_UNKNOWN_CONTEXT=true|false` (default `true`; разрешает CLI/smoke запросы без `Origin/Referer/Sec-Fetch-Site`)
- `SESSION_AUDIT_MAX_EVENTS` (максимум локального audit ring buffer для fallback/UI, default `500`; основной audit хранится в backend SQLite)
- `SESSION_AUDIT_RETENTION_DAYS` (ретенция backend audit в днях, default `90`, диапазон `1..3650`)
- `SESSION_AUDIT_ALERT_MIN_EVENTS` (минимум событий в окне для оценки deny-rate alert, default `10`)
- `SESSION_AUDIT_ALERT_DENY_RATE_WARN` / `SESSION_AUDIT_ALERT_DENY_RATE_CRITICAL` (порог deny-rate для `warn|critical`, default `0.35|0.60`)
- `SESSION_AUDIT_ALERT_ERROR_COUNT_WARN` / `SESSION_AUDIT_ALERT_ERROR_COUNT_CRITICAL` (порог `outcome=error`, default `5|20`)
- `SESSION_AUDIT_ALERT_REPLAY_COUNT_WARN` / `SESSION_AUDIT_ALERT_REPLAY_COUNT_CRITICAL` (порог `idp_token_replay_detected`, default `1|3`)
- `SESSION_AUDIT_ALERT_CONFIG_ERROR_COUNT_WARN` / `SESSION_AUDIT_ALERT_CONFIG_ERROR_COUNT_CRITICAL` (порог config-ошибок auth, default `1|3`)
- `SESSION_ACCESS_TTL_SEC` (TTL access-cookie, default `900`)
- `SESSION_REFRESH_TTL_SEC` (TTL refresh-cookie, default `604800`)
- `CASE_IMPORT_ALLOW_FULL_MODE=true|false` (default `false`; включает FULL-mode импорт только для приватного защищенного контура)
- `CASE_IMPORT_FULL_REQUIRE_ACK=true|false` (default `true`; для FULL-mode требует `full_mode_acknowledged=true`)
- `CASE_IMPORT_DEID_REDACT_PII=true|false` (default `true`; редактирует найденные PII-фрагменты в DEID-импорте)

Build режим:

- `PIP_INSTALL_MODE=online|offline`
- `NPM_INSTALL_MODE=online|offline`

CLI overrides (для `./onco`):

- `ONCOAI_UI_URL` (по умолчанию `http://localhost:3000`)
- `ONCOAI_BACKEND_URL` (по умолчанию `http://localhost:8000`)
- `ONCOAI_SCHEMA_VERSION` (по умолчанию `0.2`)
- `ONCOAI_DEMO_TOKEN` (если нужно переопределить `DEMO_TOKEN` только для CLI-скрипта)
- `ONCOAI_DEMO_REINDEX_POLLS` (максимум poll-итераций ожидания `admin/reindex` в demo-командах, по умолчанию `120`)
- `ONCOAI_DEMO_DATA_SCOPE_SUFFIX` (суффикс demo data-dir; если не задан, `./onco demo-*` использует timestamp и стартует с чистого demo-хранилища)
- `ONCOAI_DEMO_REQUIRE_LLM=true|false` (включает strict gate на LLM path для `demo-local-smoke`/`demo-api-smoke`)
- `ONCOAI_DEMO_LOCAL_WITH_VLLM=true|false` (принудительно поднимать `vllm` профиль в `demo-local-smoke`; по умолчанию только при необходимости)
- `ONCOAI_DEMO_ALLOW_API_EMBED_FALLBACK=true|false` (разрешает `demo-api-smoke` работать без API embedding ключа через `hash`; по умолчанию `false`, т.е. требуется реальный API-ключ)
- `ONCOAI_DEMO_LOCAL_MULTI_ONCO_CASES` (по умолчанию `C16` для low-load локального демо)
- `ONCOAI_DEMO_API_MULTI_ONCO_CASES` (по умолчанию `C16` для low-traffic API демо)
- `ONCOAI_DEMO_SKIP_PDF_PAGE_FLOW=true|false` (по умолчанию `false`; отключает PDF page-flow acceptance в demo-командах)
- `ONCOAI_CASES_FILE`, `ONCOAI_IMPORT_CASES_FILE`, `ONCOAI_METRICS_OUT` (пути для `metrics/load/import-quality`)
- `ONCOAI_METRICS_WARMUP_CASES` (сколько первых кейсов не учитывать в latency-статистике, по умолчанию `3`)
- `ONCOAI_METRICS_P95_GATE` (по умолчанию `120`)
- `ONCOAI_LOAD_P95_GATE` (по умолчанию `200`)
- `ONCOAI_MIN_RECALL_GATE` (по умолчанию `1.0`)
- `ONCOAI_MIN_EVIDENCE_VALID_GATE` (по умолчанию `1.0`)
- `ONCOAI_REQUIRED_IMPORT_PROFILES` (по умолчанию `FREE_TEXT,KIN_PDF,FHIR_BUNDLE`)
- `ONCOAI_MIN_IMPORT_SUCCESS_GATE` (по умолчанию `1.0`)
- `ONCOAI_MIN_IMPORT_PROFILE_COVERAGE_GATE` (по умолчанию `1.0`)
- `ONCOAI_MIN_IMPORT_REQUIRED_FIELD_COVERAGE_GATE` (по умолчанию `1.0`)
- `ONCOAI_MIN_IMPORT_DATA_MODE_COVERAGE_GATE` (по умолчанию `1.0`)
- `ONCOAI_SESSION_INCIDENT_WINDOW_HOURS` (окно incident summary для gate, по умолчанию `24`)
- `ONCOAI_SESSION_INCIDENT_FAIL_ON` (уровень fail для incident gate: `off|none|low|medium|high`, по умолчанию `high`)
- `ONCOAI_SESSION_INCIDENT_MAX_CRITICAL_ALERTS` (максимум critical alerts, `-1` отключает)
- `ONCOAI_SESSION_INCIDENT_MAX_WARN_ALERTS` (максимум warn alerts, `-1` отключает)

## 8.1 Troubleshooting demo

- `sqlite3.OperationalError: unable to open database file`:
  проверьте `ONCOAI_DATA_DIR` и `ONCOAI_DB_PATH` (пустые значения недопустимы), затем `./onco up` и `./onco health`.
- `demo-local-smoke` падает на Ollama model missing:
  выполните `docker compose -f infra/docker-compose.yml --profile full up -d ollama` и дайте `./onco demo-local-smoke` подтянуть модель.
- `demo-api-smoke` падает по ключам:
  проверьте `LLM_PRIMARY_API_KEY`/`OPENAI_API_KEY` и `EMBEDDING_API_KEY` (или включите `ONCOAI_DEMO_ALLOW_API_EMBED_FALLBACK=true`).
- `admin/reindex` через BFF долго отвечает:
  увеличьте `ONCOAI_DEMO_REINDEX_POLLS` и проверьте логи `backend`/`frontend`.

## 9) API контур

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
- `GET /session/audit/summary` (admin session security telemetry summary за окно времени)
- `POST /session/idp/replay/reserve` (internal anti-replay reserve для `idp` `jti`)

Обязательные заголовки для прямых backend-вызовов:

- `x-role`
- `x-demo-token`
- (опционально для `/analyze`) `x-client-id`

Для BFF (`/api/*`) клиентский заголовок `x-role` больше не используется для авторизации:

- роль берётся только из server-side подписанной session-модели (`session_access/session_access_sig` с fallback на `session_refresh/session_refresh_sig`);
- при отсутствии/некорректной роли BFF возвращает `401 BFF_AUTH_REQUIRED`;
- при недопустимой роли для endpoint BFF возвращает `403 BFF_FORBIDDEN`.

Session endpoints (frontend):

- `GET|POST /api/session/login`
- `GET|POST /api/session/logout`
- `GET /api/session/me`
- `POST /api/session/revoke` (self revoke или admin forced logout по `user_id`)
- `GET /api/session/audit` (admin-only аудит session-событий + sample revoked session IDs)
- `GET /api/session/audit/summary` (admin-only сводка `Auth Risk Snapshot`: `total_events/outcomes/top_reasons` + `incident_level/incident_score/incident_signals/alerts`)
- `GET /api/session/audit/export` (admin-only export audit в `json|csv`, поддерживает `all=1` для выгрузки по всем страницам cursor)
- session revoke/audit state хранится в backend shared storage (SQLite), а не только в runtime frontend процесса.
- refresh-token rotation включен: при auth через refresh-cookie выдаются новые cookies, использованный refresh `session_id` сразу попадает в revoke registry (`refresh_rotation`).
- `GET /api/session/audit` поддерживает фильтры/пагинацию: `limit`, `outcome`, `event`, `reason`, `reason_group`, `user_id`, `correlation_id`, `from_ts`, `to_ts`, `cursor` (в ответе `next_cursor`).
- `POST /api/session/login`, `POST /api/session/logout`, `POST /api/session/revoke` защищены same-origin CSRF guard; reject reason: `csrf_origin_mismatch|csrf_context_missing_or_cross_site`.
- `GET /api/session/audit/export` поддерживает те же фильтры + `format=json|csv`, `all=0|1`, `max_pages`, `max_events` (bounded, hard cap).
- Числовые параметры export (`limit`, `max_pages`, `max_events`) валидируются строго; невалидные/вне диапазона значения возвращают `400 BFF_BAD_REQUEST`.
- Для `from_ts/to_ts` используется strict ISO timestamp в UTC-нормализации; при невалидном формате или диапазоне `from_ts > to_ts` backend возвращает `400 ValidationError`.
- CSV export защищён от spreadsheet-formula injection: значения, начинающиеся с `=`, `+`, `-`, `@` (включая leading whitespace), префиксуются `'`.
- Export-ответ добавляет guard headers: `x-onco-export-max-events`, `x-onco-export-truncated`, `x-onco-export-truncated-reason`.
- `scripts/e2e_smoke.py` проверяет runtime export-контур (`/api/session/audit/export`) в JSON и CSV режимах (headers + базовая структура), включая truncation path (`max_events=1`).

Режимы login:

- `SESSION_AUTH_MODE=demo`: вход через роль (`role`), используется для локального демо.
- `SESSION_AUTH_MODE=credentials`: вход только через `POST /api/session/login` с `username/password`; роль берется из `SESSION_USERS_JSON`.
- `SESSION_AUTH_MODE=idp`: `GET /api/session/login` отключен для interactive login; `POST /api/session/login` работает как token exchange (`id_token` или `Authorization: Bearer ...`) и после валидации claim/signature выдает server-side session cookies; по умолчанию включены anti-replay (`jti`) и clock-skew leeway-проверки.

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
- legacy-совместимость: `/api/report/[slug]` (`.json`/`.html`)

Коды BFF ошибок:

- `BFF_BAD_REQUEST`
- `BFF_AUTH_REQUIRED`
- `BFF_FORBIDDEN`
- `BFF_UPSTREAM_VALIDATION_ERROR`
- `BFF_UPSTREAM_AUTH_ERROR`
- `BFF_UPSTREAM_NOT_FOUND`
- `BFF_UPSTREAM_RATE_LIMITED`
- `BFF_UPSTREAM_HTTP_ERROR`
- `BFF_UPSTREAM_NETWORK_ERROR`

Формат BFF JSON-ошибки:

- Canonical поле: `error_code`
- Backward-compatible alias: `code`

Трассировка BFF:

- BFF проксирует `x-correlation-id` в backend и возвращает этот же header клиенту.
- Для JSON-ошибок BFF добавляет поле `correlation_id`.

## 10) Контракты и диалекты запроса

- `legacy v0.1` поддерживается без ломающих изменений
- `legacy v0.2` добавляет расширенную клиническую структуру (`case.patient`, `diagnosis`, `biomarkers`, ...), `run_meta`, `insufficient_data`
- `pack v0.2` (`onco_json_pack`) принимается через bridge-адаптер: backend нормализует вход в внутренний analyze pipeline и возвращает pack-совместимый ответ
- `pack v0.2` поддерживает `case_id`-путь: если `case.case_json` не передан, backend подставляет кейс из локального хранилища (`POST /case/import` -> `POST /analyze`)
- В `run_meta` поддерживаются поля `report_generation_path`, `retrieval_engine`, опционально `fallback_reason`; для pack-ответа применяется enum-мэппинг (`primary|fallback|deterministic_only`)

Спецификация:

- `docs/contracts/analyze_dual_support_v0_1_v0_2.md`
- Canonical pack schemas/examples/seeds: `docs/contracts/onco_json_pack_v1/`
- Governance bootstrap: backend автоматически загружает `guideline_sources` и `disease_registry` из `docs/contracts/onco_json_pack_v1/seeds/*` при старте.

Минимальный пример v0.2 запроса:

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
    "notes": "Синтетический кейс"
  },
  "treatment_plan": {
    "plan_text": "Осимертиниб 80 мг ежедневно",
    "plan_structured": [{"step_type": "systemic_therapy", "name": "Осимертиниб"}]
  },
  "return_patient_explain": true
}
```

## 11) Проверки качества и сценарии

Backend unit/regression:

```bash
PYTHONPATH=. pytest backend/tests -q
```

Frontend quality (локально):

```bash
cd frontend
npm ci
npm run lint
npm run build
```

Локальный pre-release gate (короткая команда):

```bash
./onco preflight
```

`./onco preflight` автоматически перезапускает backend и ждет `/health` перед runtime smoke-шагами; включает и базовый smoke, и `case-flow` smoke, чтобы исключить stale-runtime после изменений `backend/app`.

Проверка session incident policy:

```bash
./onco incident-check
```

Локальный security gate:

```bash
./onco security-check
```

Выполняет строгий secrets scan + генерацию SBOM-манифеста (`reports/security/sbom_manifest.json`).

Локальный release-readiness gate:

```bash
./onco release-readiness
```

Запускает `preflight` и проверку release-артефактов (`reports/release/readiness_report.json`).

Публикация sanitized public export в отдельный GitHub-репозиторий:

```bash
./scripts/public_export.sh \
  --public-repo-url git@github.com:<public_account>/<public_repo>.git \
  --branch main \
  --dry-run
```

Полный runbook: `docs/deploy/public-sanitized-export.md`.

Отдельная проверка frontend runtime parity (с пересборкой контейнера):

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

# Если в окружении нет секрета для генерации негативных токенов:
# ONCO_SMOKE_REQUIRE_IDP_NEGATIVE=false
# Либо передайте заранее подписанные negative tokens (например для RS256):
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
# Опционально: проверить контракт login rate-limit (429 + retry-after)
# ONCO_SMOKE_CHECK_LOGIN_RATE_LIMIT=true
# ONCO_SMOKE_LOGIN_RATE_LIMIT_PROBE_ATTEMPTS=120

# Для short-command варианта:
# 1) выставите SESSION_AUTH_MODE=idp в .env и SESSION_IDP_HS256_SECRET
# 2) перезапустите frontend: ./onco restart frontend
./onco idp-smoke
```

Metrics harness:

```bash
python scripts/run_metrics.py \
  --base-url http://localhost:8000 \
  --token demo-token \
  --cases data/synthetic_cases/cases_v1_strict_release_3.json \
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

## 12) Актуальный performance baseline

Актуальный срез (2026-02-18):

- HTTP metrics: `p50=6.81ms`, `p95=9.28ms`, `recall_like=1.0`, `evidence_valid_ratio=1.0`
- Load smoke: `ok=20/20`, `p50=28.1ms`, `p95=38.93ms`

Артефакт:

- `/tmp/onco_metrics_v03.json`

## 13) Безопасность

Реализовано:

- Блокировка PII в контуре анализа
- RBAC проверка ролей (admin/clinician)
- Rate-limit с понятной ошибкой и retry-hint
- Constant-time проверка demo token
- Safe logging без утечки кейсов

## 14) Известные ограничения

- Деплой на VPS для этого этапа **отложен**.
- Нозология MVP-фокуса: `nsclc_egfr`.
- `case_import` поддерживает `FREE_TEXT`, `CUSTOM_TEMPLATE`, `FHIR_BUNDLE`, `KIN_PDF`; по умолчанию `data_mode=DEID`, optional `data_mode=FULL` доступен только при policy-включении.
- Для `FHIR_BUNDLE` извлекаются `Procedure`/`MedicationRequest`/`MedicationStatement` и заполняются `timeline` + `last_plan.line/cycle` при наличии данных.
- Доступны run-трекинг endpoints для импорта кейсов: `GET /case/import/runs`, `GET /case/import/{import_run_id}`.
- FULL-mode policy защищена: при выключенном `CASE_IMPORT_ALLOW_FULL_MODE` импорт вернет `FULL_MODE_DISABLED`; при включенном режиме и `CASE_IMPORT_FULL_REQUIRE_ACK=true` требуется `full_mode_acknowledged=true`.
- `eslint@10` доступен, но пока intentionally pinned `eslint@9.39.2` из-за совместимости текущего `eslint-config-next@16.1.6`.

## 15) Troubleshooting

### 15.1 Docker build: `Network is unreachable`

Это обычно сеть/proxy/VPN в Docker, а не ошибка API-ключа.

Проверьте:

1. интернет на хосте,
2. proxy в Docker Desktop,
3. доступ Docker через VPN,
4. повторный `docker compose ... up --build -d`.

### 15.2 Frontend зависимости

Если есть сбой lockfile/peer deps:

```bash
cd frontend
npm install --package-lock-only
npm ci
```

### 15.3 Backend не отвечает

```bash
docker compose -f infra/docker-compose.yml ps
docker compose -f infra/docker-compose.yml logs backend --tail=200
```

## 16) Документация этапа

- Freeze summary: `docs/cap/v0_2_freeze_summary.md`
- Bridge freeze summary v0.4: `docs/cap/v0_4_bridge_freeze_summary.md`
- Daily logs: `docs/cap/daily_log_D12.md` ... `docs/cap/daily_log_D17.md`
- Regression checklist: `docs/qa/regression_checklist.md`
- Контракты: `docs/contracts/analyze_dual_support_v0_1_v0_2.md`

## 17) Деплой

В этом этапе инфраструктурный релиз на VPS намеренно не выполнялся. Для production-процесса см.:

- `docs/deploy/prod-registry-digest-deploy.md`
- `docs/deploy/public-sanitized-export.md`
- `infra/.env.prod.example`
- GitHub workflows в `.github/workflows/`
