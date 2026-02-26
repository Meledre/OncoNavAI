from __future__ import annotations

from backend.app.storage import SQLiteStore


def _store(tmp_path) -> SQLiteStore:
    db_path = tmp_path / "data" / "oncoai.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return SQLiteStore(db_path)


def test_nosology_routes_upsert_and_list(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_nosology_route(
        {
            "route_id": "route-1",
            "language": "ru",
            "icd10_prefix": "C16",
            "keyword": "рак желудка",
            "disease_id": "disease-gastric",
            "cancer_type": "gastric_cancer",
            "source_id": "minzdrav",
            "doc_id": "minzdrav_574_1",
            "priority": 10,
            "active": 1,
            "updated_at": "2026-02-20T10:00:00Z",
        }
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-2",
            "language": "ru",
            "icd10_prefix": "C16",
            "keyword": "stomach cancer",
            "disease_id": "disease-gastric",
            "cancer_type": "gastric_cancer",
            "source_id": "russco",
            "doc_id": "russco_2023_22",
            "priority": 20,
            "active": 1,
            "updated_at": "2026-02-20T10:00:01Z",
        }
    )

    routes = store.list_nosology_routes(language="ru")
    assert len(routes) == 2
    assert [item["route_id"] for item in routes] == ["route-1", "route-2"]
    assert routes[0]["source_id"] == "minzdrav"
    assert routes[1]["source_id"] == "russco"


def test_nosology_routes_sync_marks_orphaned_routes_inactive(tmp_path) -> None:
    store = _store(tmp_path)
    store.upsert_nosology_route(
        {
            "route_id": "route-keep",
            "language": "ru",
            "icd10_prefix": "C50",
            "keyword": "рак молочной железы",
            "disease_id": "disease-breast",
            "cancer_type": "breast_hr+/her2-",
            "source_id": "minzdrav",
            "doc_id": "breast_doc",
            "priority": 10,
            "active": 1,
            "updated_at": "2026-02-20T10:00:00Z",
        }
    )
    store.upsert_nosology_route(
        {
            "route_id": "route-drop",
            "language": "ru",
            "icd10_prefix": "C34",
            "keyword": "рак легкого",
            "disease_id": "disease-lung",
            "cancer_type": "nsclc_egfr",
            "source_id": "russco",
            "doc_id": "lung_doc",
            "priority": 10,
            "active": 1,
            "updated_at": "2026-02-20T10:00:00Z",
        }
    )

    result = store.sync_nosology_routes_active_docs(active_pairs={("minzdrav", "breast_doc")})
    assert result["deactivated"] == 1
    assert result["active"] == 1

    active_routes = store.list_nosology_routes(language="ru", active_only=True)
    assert len(active_routes) == 1
    assert active_routes[0]["route_id"] == "route-keep"
