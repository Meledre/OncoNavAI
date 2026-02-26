#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Shot:
    step: int
    title: str
    file: str
    captured_at: str


class WebDriverClient:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.session_id = ""

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base}{path}",
            method=method,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = response.read().decode("utf-8")
                body = json.loads(raw) if raw.strip() else {}
                return body if isinstance(body, dict) else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"webdriver http {exc.code}: {raw}") from exc

    def start_session(self) -> None:
        payload = {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": "safari",
                }
            }
        }
        body = self._request("POST", "/session", payload)
        session_id = str(body.get("sessionId") or "")
        if not session_id:
            value = body.get("value")
            if isinstance(value, dict):
                session_id = str(value.get("sessionId") or "")
        if not session_id:
            raise RuntimeError(f"Failed to create webdriver session: {body}")
        self.session_id = session_id

    def close_session(self) -> None:
        if not self.session_id:
            return
        try:
            self._request("DELETE", f"/session/{self.session_id}")
        except Exception:
            pass
        self.session_id = ""

    def navigate(self, url: str) -> None:
        self._request("POST", f"/session/{self.session_id}/url", {"url": url})

    def screenshot(self) -> bytes:
        body = self._request("GET", f"/session/{self.session_id}/screenshot")
        value = str(body.get("value") or "")
        if not value:
            raise RuntimeError(f"Screenshot payload is empty: {body}")
        return base64.b64decode(value)

    def find_element(self, using: str, value: str) -> str:
        body = self._request(
            "POST",
            f"/session/{self.session_id}/element",
            {"using": using, "value": value},
        )
        item = body.get("value") if isinstance(body.get("value"), dict) else {}
        if not isinstance(item, dict):
            raise RuntimeError(f"Element not found: {using} {value}")
        element_id = str(item.get("element-6066-11e4-a52e-4f735466cecf") or item.get("ELEMENT") or "")
        if not element_id:
            raise RuntimeError(f"Element id is missing: {using} {value} -> {body}")
        return element_id

    def click(self, element_id: str) -> None:
        self._request("POST", f"/session/{self.session_id}/element/{element_id}/click", {})

    def element_text(self, element_id: str) -> str:
        body = self._request("GET", f"/session/{self.session_id}/element/{element_id}/text")
        return str(body.get("value") or "")

    def accept_alert(self) -> None:
        self._request("POST", f"/session/{self.session_id}/alert/accept", {})


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _shot(out_dir: Path, manifest: list[Shot], title: str, filename: str, png_bytes: bytes) -> None:
    path = out_dir / filename
    path.write_bytes(png_bytes)
    manifest.append(
        Shot(
            step=len(manifest) + 1,
            title=title,
            file=filename,
            captured_at=datetime.now(timezone.utc).isoformat(),
        )
    )


def _click_xpath(client: WebDriverClient, xpath: str) -> bool:
    try:
        element_id = client.find_element("xpath", xpath)
        client.click(element_id)
        return True
    except Exception:
        return False


def _wait(seconds: float = 1.2) -> None:
    time.sleep(seconds)


def _zip_artifacts(out_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(out_dir.glob("*")):
            archive.write(item, arcname=item.name)


def _run_preflight(*, driver_port: int) -> tuple[bool, dict[str, Any]]:
    if shutil.which("safaridriver") is None:
        return False, {"reason": "safaridriver_not_found", "hint": "Install Safari WebDriver / Xcode Command Line Tools."}

    log_file = tempfile.NamedTemporaryFile(prefix="safaridriver_preflight_", suffix=".log", delete=False)
    log_file.close()
    proc = subprocess.Popen(
        ["safaridriver", "-p", str(driver_port)],
        stdout=open(log_file.name, "w", encoding="utf-8"),  # noqa: SIM115
        stderr=subprocess.STDOUT,
    )
    client = WebDriverClient(f"http://127.0.0.1:{driver_port}")
    try:
        for _ in range(20):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{driver_port}/status", timeout=1)
                break
            except Exception:
                _wait(0.25)
        else:
            return False, {"reason": "webdriver_status_unreachable", "driver_log": log_file.name}
        try:
            client.start_session()
        except Exception as exc:  # noqa: BLE001
            return False, {
                "reason": "webdriver_session_create_failed",
                "error": str(exc),
                "hint": "Enable Safari: Develop -> Allow Remote Automation",
                "driver_log": log_file.name,
            }
        return True, {"reason": "ok", "driver_log": log_file.name}
    finally:
        client.close_session()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture admin ingest flow screenshots via Safari WebDriver")
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--out-dir", default=f"/tmp/oncoai_admin_ingest_screens_{_timestamp()}")
    parser.add_argument("--downloads-dir", default=str(Path.home() / "Downloads"))
    parser.add_argument("--driver-port", type=int, default=4444)
    parser.add_argument("--preflight", action="store_true", help="Only validate WebDriver prerequisites.")
    args = parser.parse_args()

    if args.preflight:
        ok, details = _run_preflight(driver_port=args.driver_port)
        print(json.dumps({"status": "ok" if ok else "blocked", **details}, ensure_ascii=False))
        return 0 if ok else 2

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[Shot] = []

    log_file = tempfile.NamedTemporaryFile(prefix="safaridriver_", suffix=".log", delete=False)
    log_file.close()
    driver_proc = subprocess.Popen(
        ["safaridriver", "-p", str(args.driver_port)],
        stdout=open(log_file.name, "w", encoding="utf-8"),  # noqa: SIM115
        stderr=subprocess.STDOUT,
    )
    client = WebDriverClient(f"http://127.0.0.1:{args.driver_port}")

    try:
        for _ in range(20):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{args.driver_port}/status", timeout=1)
                break
            except Exception:
                _wait(0.4)
        client.start_session()

        client.navigate(f"{args.base_url.rstrip('/')}/")
        _wait()
        _shot(out_dir, manifest, "Login admin", "01_login_admin.png", client.screenshot())

        _click_xpath(client, "//a[contains(., 'Войти как администратор')]")
        _wait(1.5)
        client.navigate(f"{args.base_url.rstrip('/')}/admin?tab=docs")
        _wait()
        _shot(out_dir, manifest, "Docs before cleanup", "02_docs_before_cleanup.png", client.screenshot())

        _click_xpath(client, "//button[contains(., 'Dry-run очистки')]")
        _wait(1.8)
        _shot(out_dir, manifest, "Cleanup dry-run", "03_cleanup_dry_run.png", client.screenshot())

        if _click_xpath(client, "//button[contains(., 'Применить очистку')]"):
            _wait(0.6)
            try:
                client.accept_alert()
            except Exception:
                pass
            _wait(2.0)
        _shot(out_dir, manifest, "Cleanup apply", "04_cleanup_apply.png", client.screenshot())

        _shot(out_dir, manifest, "Upload form with source_url/doc_kind", "05_upload_form.png", client.screenshot())

        # Demonstrate workflow transitions on MKB10 reference row.
        _click_xpath(client, "//tr[td[contains(., 'russco_2025_mkb10')]]//button[contains(., 'Re-chunk')]")
        _wait(2.2)
        _shot(out_dir, manifest, "Reference status after rechunk", "06_rechunk_status.png", client.screenshot())

        _click_xpath(client, "//tr[td[contains(., 'russco_2025_mkb10')]]//button[contains(., 'Approve')]")
        _wait(2.0)
        _shot(out_dir, manifest, "Reference status after approve", "07_approve_status.png", client.screenshot())

        _click_xpath(client, "//tr[td[contains(., 'russco_2025_mkb10')]]//button[contains(., 'Index')]")
        _wait(2.2)
        _click_xpath(client, "//tr[td[contains(., 'russco_2025_mkb10')]]//button[contains(., 'Verify')]")
        _wait(1.4)
        _shot(out_dir, manifest, "Reference index + verify", "08_index_verify_status.png", client.screenshot())

        # Final release guideline list.
        client.navigate(f"{args.base_url.rstrip('/')}/admin?tab=docs")
        _wait(1.0)
        _shot(out_dir, manifest, "Valid guideline list", "09_valid_guideline_list.png", client.screenshot())

        client.navigate(f"{args.base_url.rstrip('/')}/admin?tab=references")
        _wait(1.0)
        _shot(out_dir, manifest, "References tab with MKB10", "10_references_tab_mkb10.png", client.screenshot())

        client.navigate(f"{args.base_url.rstrip('/')}/admin?tab=sync")
        _wait(1.0)
        _shot(out_dir, manifest, "Sync tab snapshot", "11_sync_tab_snapshot.png", client.screenshot())

        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "base_url": args.base_url,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "screenshots": [shot.__dict__ for shot in manifest],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        zip_path = Path(f"/tmp/oncoai_admin_ingest_presentation_{_timestamp()}.zip")
        _zip_artifacts(out_dir, zip_path)
        downloads_zip = Path(args.downloads_dir).resolve() / zip_path.name
        shutil.copy2(zip_path, downloads_zip)

        print(
            json.dumps(
                {
                    "status": "ok",
                    "out_dir": str(out_dir),
                    "manifest": str(manifest_path),
                    "zip_tmp": str(zip_path),
                    "zip_downloads": str(downloads_zip),
                    "driver_log": log_file.name,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        status_payload = {
            "status": "blocked",
            "error": str(exc),
            "driver_log": log_file.name,
            "hint": "Run preflight: python3 scripts/capture_admin_ingest_flow.py --preflight",
        }
        (out_dir / "capture_status.json").write_text(
            json.dumps(status_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(status_payload, ensure_ascii=False))
        return 2
    finally:
        try:
            client.close_session()
        except Exception:
            pass
        driver_proc.terminate()
        try:
            driver_proc.wait(timeout=3)
        except Exception:
            driver_proc.kill()
            try:
                driver_proc.wait(timeout=1)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
