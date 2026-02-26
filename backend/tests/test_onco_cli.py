from __future__ import annotations

from pathlib import Path


def test_onco_cli_includes_governance_command() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert "governance             Print governance snapshot" in text
    assert "governance) cmd_governance ;;" in text


def test_onco_cli_includes_case_smoke_command() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert "case-smoke             Run E2E smoke via case import -> analyze(case_id) path" in text
    assert "case-smoke) cmd_case_smoke ;;" in text


def test_onco_cli_includes_gastric_smoke_command() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert "gastric-smoke          Run gastric e2e flow using json_pack payloads" in text
    assert "gastric-smoke) cmd_gastric_smoke ;;" in text
    assert "ONCOAI_GASTRIC_PACK_DIR" in text


def test_onco_cli_includes_demo_profile_smoke_commands() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert "demo-local-smoke       Run demo smoke with .env.demo.local profile (local LLM stack)" in text
    assert "demo-api-smoke         Run demo smoke with .env.demo.api profile (API stack)" in text
    assert "demo-local-smoke) cmd_demo_local_smoke ;;" in text
    assert "demo-api-smoke) cmd_demo_api_smoke ;;" in text
    assert "apply_demo_profile_stack local" in text
    assert "apply_demo_profile_stack api" in text
    assert "configure_demo_data_scope local" in text
    assert "configure_demo_data_scope api" in text
    assert "--reindex-polls \"$reindex_polls\"" in text
    assert "ONCOAI_DEMO_REINDEX_POLLS" in text
    assert "fallback_url=\"${LLM_FALLBACK_URL:-}\"" in text
    assert "ONCOAI_DEMO_LOCAL_WITH_VLLM" in text
    assert "ONCOAI_DEMO_LOCAL_WITH_OLLAMA" in text
    assert "with_ollama" in text
    assert "ensure_ollama_model" in text
    assert "if compose exec -T ollama ollama list >/dev/null 2>&1; then" in text
    assert "ONCOAI_DEMO_LOCAL_HTTP_TIMEOUT_SEC" in text
    assert "ONCO_SMOKE_HTTP_TIMEOUT_SEC" in text
    assert "compose --profile full up -d --force-recreate backend qdrant ollama" in text
    assert "ONCOAI_DEMO_ALLOW_API_EMBED_FALLBACK" in text
    assert "first_non_empty" in text
    assert "ONCO_PROBE_URL" in text
    assert "ONCOAI_DEMO_DATA_SCOPE_SUFFIX" in text
    assert "date +%Y%m%d%H%M%S" in text
    assert "cli_openai_api_key=\"${OPENAI_API_KEY:-}\"" in text
    assert "cli_llm_primary_api_key=\"${LLM_PRIMARY_API_KEY:-}\"" in text
    assert "cli_embedding_api_key=\"${EMBEDDING_API_KEY:-}\"" in text
    assert "if [ -z \"$cli_llm_primary_url\" ]; then export LLM_PRIMARY_URL=\"\"; fi" in text
    assert "if [ -z \"$cli_llm_primary_model\" ]; then export LLM_PRIMARY_MODEL=\"\"; fi" in text
    assert "if [ -z \"$cli_llm_primary_api_key\" ] && [ -z \"$cli_openai_api_key\" ]; then export LLM_PRIMARY_API_KEY=\"\"; fi" in text
    assert "--multi-onco-flow" in text
    assert "--require-vector-backend \"qdrant\"" in text
    assert "--require-embedding-backend \"hash\"" in text
    assert "--require-embedding-backend \"$expected_embedding_backend\"" in text
    assert "--require-reranker-backend \"$expected_reranker_backend\"" in text
    assert "--require-reranker-backend \"lexical\"" in text
    assert "--multi-onco-cases \"$multi_onco_cases\"" in text
    assert "--require-report-generation-path \"fallback\"" in text
    assert "--require-report-generation-path \"primary\"" in text
    assert "ONCOAI_DEMO_LOCAL_MULTI_ONCO_CASES" in text
    assert "local multi_onco_cases=\"${ONCOAI_DEMO_LOCAL_MULTI_ONCO_CASES:-C16}\"" in text
    assert "cli_embedding_backend=\"${EMBEDDING_BACKEND:-}\"" in text
    assert "if [ -z \"$cli_embedding_backend\" ]; then export EMBEDDING_BACKEND=\"\"; fi" in text
    assert "if [ -n \"$cli_embedding_backend\" ]; then export EMBEDDING_BACKEND=\"$cli_embedding_backend\"; fi" in text
    assert "ONCOAI_DEMO_API_MULTI_ONCO_CASES" in text
    assert "local multi_onco_cases=\"${ONCOAI_DEMO_API_MULTI_ONCO_CASES:-C16}\"" in text
    assert "configured_embedding_backend" in text
    assert "if [ \"$configured_embedding_backend\" != \"openai\" ]" in text
    assert "expected_embedding_backend=\"$configured_embedding_backend\"" in text
    assert "ONCO_PROBE_API_KEY" in text
    assert "cannot reach LLM_PRIMARY_URL" in text


def test_onco_cli_demo_smoke_enables_pdf_page_flow_by_default() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()

    assert text.count('local pdf_page_flow_flag="--pdf-page-flow"') >= 2
    assert "ONCOAI_DEMO_SKIP_PDF_PAGE_FLOW" in text


def test_onco_cli_includes_multi_onco_smoke_command() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert "multi-onco-smoke       Run multi-oncology smoke (C16/C34/C50) via file import + analyze + patient" in text
    assert "multi-onco-smoke) cmd_multi_onco_smoke ;;" in text
    assert "--multi-onco-flow" in text
    assert "min_routing_reduction_gate()" in text
    assert "ONCOAI_MIN_ROUTING_REDUCTION_GATE" in text
    assert '--min-routing-reduction "$(min_routing_reduction_gate)"' in text


def test_onco_cli_includes_pdf_pack_smoke_command() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert "pdf-pack-smoke         Run shadow smoke on v8_smooth synthetic PDF pack (pilot/full)" in text
    assert "pdf-pack-smoke) cmd_pdf_pack_smoke \"$@\" ;;" in text
    assert "scripts/eval_pdf_pack.py" in text
    assert "DEFAULT_PDF_PACK_ZIP" in text
    assert "DEFAULT_PDF_PACK_XLSX" in text
    assert "DEFAULT_PDF_PACK_SAMPLE_MODE" in text
    assert "DEFAULT_PDF_PACK_AUTH_MODE" in text
    assert "DEFAULT_PDF_PACK_HTTP_TIMEOUT_SEC" in text
    assert "pdf_pack_zip()" in text
    assert "pdf_pack_xlsx()" in text
    assert "pdf_pack_sample_mode()" in text
    assert "pdf_pack_auth_mode()" in text
    assert "pdf_pack_http_timeout_sec()" in text
    assert "ONCOAI_PDF_PACK_OUT_DIR" in text
    assert "--sample-mode \"$(pdf_pack_sample_mode)\"" in text


def test_onco_cli_includes_prod_release_command() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert "prod-release          Run production release orchestration helper" in text
    assert "prod-release) cmd_prod_release \"$@\" ;;" in text
    assert "scripts/prod_release_orchestrator.py" in text


def test_onco_cli_includes_incident_check_command() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert "incident-check         Run session incident gate from /session/audit/summary" in text
    assert "incident-check) cmd_incident_check ;;" in text
    assert "scripts/session_incident_gate.py" in text
    assert "ONCOAI_SESSION_INCIDENT_FAIL_ON" in text


def test_onco_cli_includes_idp_smoke_command() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert "idp-smoke              Run E2E smoke using idp token-exchange login mode" in text
    assert "idp-smoke) cmd_idp_smoke" in text
    assert "SESSION_AUTH_MODE=idp" in text
    assert "SESSION_IDP_HS256_SECRET" in text
    assert "ONCO_SMOKE_IDP_ADMIN_TOKEN" in text
    assert "ONCO_SMOKE_IDP_CLINICIAN_TOKEN" in text


def test_onco_preflight_restarts_backend_before_smoke() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert "cmd_preflight()" in text
    assert "cmd_restart backend" in text
    assert "wait_backend_health" in text
    assert "wait_ui_health" in text
    start = text.index("cmd_preflight() {")
    end = text.index("\n}\n\nmain()")
    preflight_block = text[start:end]
    assert "wait_ui_health 30 1" in preflight_block
    assert "(ONCO_SMOKE_HTTP_TIMEOUT_SEC=180 ONCO_SMOKE_CHECK_LOGIN_RATE_LIMIT=true ONCO_SMOKE_LOGIN_RATE_LIMIT_PROBE_ATTEMPTS=120 ONCO_SMOKE_CHECK_SESSION_CSRF=true ONCO_SMOKE_SKIP_REINDEX=true cmd_smoke)" in preflight_block
    assert "(ONCOAI_CASE_SMOKE_HTTP_TIMEOUT_SEC=180 ONCO_SMOKE_CHECK_SESSION_CSRF=true ONCO_SMOKE_SKIP_REINDEX=true cmd_case_smoke)" in preflight_block
    assert "cmd_case_smoke" in preflight_block
    assert "cmd_incident_check" in preflight_block
    assert "cmd_security_check" in preflight_block
    assert "--min-import-data-mode-coverage" in preflight_block
    assert "--http-timeout-sec \"$preflight_load_http_timeout\"" in preflight_block
    assert "--http-timeout-sec \"$preflight_metrics_http_timeout\"" in preflight_block
    assert "--http-retry-attempts 1" in preflight_block
    assert "--http-retry-delay-ms 0" in preflight_block
    assert "--min-recall-like" in preflight_block
    assert "--min-throughput-cases-per-hour" in preflight_block
    assert "--min-top3-acceptance-rate" in preflight_block
    assert "--min-sus-score" in preflight_block
    assert "--max-rewrite-required-rate" in preflight_block
    assert "--min-approved-ratio" in preflight_block
    assert "--min-approved-pairs-by-nosology" in preflight_block
    assert "ONCOAI_PREFLIGHT_METRICS_P95_GATE" in text
    assert "ONCOAI_PREFLIGHT_LOAD_P95_GATE" in text
    assert "ONCOAI_PREFLIGHT_LOAD_HTTP_TIMEOUT_SEC" in text
    assert "ONCOAI_PREFLIGHT_METRICS_HTTP_TIMEOUT_SEC" in text
    assert "ONCOAI_MIN_PRECISION_GATE" in text
    assert "ONCOAI_MIN_F1_GATE" in text
    assert "ONCOAI_MIN_THROUGHPUT_CASES_PER_HOUR_GATE" in text
    assert "ONCOAI_MIN_TOP3_ACCEPTANCE_RATE_GATE" in text
    assert "ONCOAI_MIN_SUS_SCORE_GATE" in text
    assert "ONCOAI_TOP3_SCORECARD_FILE" in text
    assert "ONCOAI_SUS_INPUT_FILE" in text
    assert "ONCOAI_MAX_REWRITE_REQUIRED_RATE_GATE" in text
    assert "ONCOAI_MIN_APPROVED_RATIO_GATE" in text
    assert "ONCOAI_MIN_APPROVED_PAIRS_BY_NOSOLOGY_GATE" in text


def test_onco_preflight_load_gate_default_is_demo_friendly() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert 'DEFAULT_PREFLIGHT_LOAD_P95_GATE="120000"' in text


def test_onco_cli_includes_security_and_release_readiness_commands() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert "security-check         Run local security hygiene gate" in text
    assert "release-readiness      Run preflight + release-readiness artifact checks" in text
    assert "security-check) cmd_security_check ;;" in text
    assert "release-readiness) cmd_release_readiness ;;" in text


def test_onco_cli_has_import_data_mode_gate_default() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()
    assert "DEFAULT_MIN_IMPORT_DATA_MODE_COVERAGE_GATE" in text
    assert "ONCOAI_MIN_IMPORT_DATA_MODE_COVERAGE_GATE" in text
    assert "--min-import-data-mode-coverage" in text
    assert "DEFAULT_MIN_RECALL_GATE=\"0.90\"" in text
    assert "DEFAULT_MIN_PRECISION_GATE=\"0.80\"" in text
    assert "DEFAULT_MIN_F1_GATE=\"0.85\"" in text


def test_onco_cli_loads_optional_hidden_secrets_env() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()

    assert "DEFAULT_SECRETS_ENV_FILE=\"$HOME/.config/oncoai/secrets.env\"" in text
    assert "ONCOAI_SECRETS_ENV_FILE" in text
    assert "load_secrets_env()" in text
    assert ". \"$file_path\"" in text


def test_onco_prepare_env_calls_load_secrets_env() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()

    start = text.index("prepare_env() {")
    end = text.index("\n}\n\nload_profile_env_file()")
    prepare_env_block = text[start:end]
    assert "load_env" in prepare_env_block
    assert "load_secrets_env" in prepare_env_block


def test_onco_demo_data_scope_sets_isolated_qdrant_collection() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()

    start = text.index("configure_demo_data_scope() {")
    end = text.index("\n}\n\npython_cmd()")
    scope_block = text[start:end]
    assert "QDRANT_COLLECTION" in scope_block
    assert "oncoai_demo_" in scope_block


def test_onco_metrics_and_load_have_backend_fail_fast_guard() -> None:
    script = Path(__file__).resolve().parents[2] / "onco"
    text = script.read_text()

    assert "ensure_backend_ready_for_runtime()" in text
    metrics_start = text.index("cmd_metrics() {")
    metrics_end = text.index("\n}\n\ncmd_load()")
    metrics_block = text[metrics_start:metrics_end]
    assert 'ensure_backend_ready_for_runtime "metrics"' in metrics_block

    load_start = text.index("cmd_load() {")
    load_end = text.index("\n}\n\ncmd_test()")
    load_block = text[load_start:load_end]
    assert 'ensure_backend_ready_for_runtime "load"' in load_block
