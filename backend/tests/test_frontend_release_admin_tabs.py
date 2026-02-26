from __future__ import annotations

from pathlib import Path


def _admin_page() -> str:
    return (Path(__file__).resolve().parents[2] / "frontend" / "app" / "admin" / "page.tsx").read_text()


def test_admin_page_has_single_route_tabs_and_query_sync() -> None:
    page = _admin_page()
    assert "AdminTabs" in page
    assert "useSearchParams" in page
    assert "useRouter" in page
    assert "tab=docs" in page
    assert "tab=references" in page
    assert "tab=sync" in page
    assert "tab=import" in page
    assert "tab=security" in page


def test_admin_page_composes_tab_components() -> None:
    page = _admin_page()
    assert "AdminDocsTab" in page
    assert "AdminReferencesTab" in page
    assert "AdminSyncTab" in page
    assert "AdminImportRunsTab" in page
    assert "AdminSecurityTab" in page
    assert 'data-testid="admin-layout"' in page
