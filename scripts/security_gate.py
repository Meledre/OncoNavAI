#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github_token", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("openai_key_like", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
]

TEXT_EXTENSIONS = {
    ".py",
    ".sh",
    ".ts",
    ".tsx",
    ".js",
    ".mjs",
    ".cjs",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
    ".md",
    ".txt",
}

SKIP_PREFIXES = (
    ".git/",
    "frontend/node_modules/",
    "frontend/.next/",
    "reports/",
)

SKIP_NAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}

SAFE_LINE_HINTS = (
    "example",
    "placeholder",
    "changeme",
    "demo-token",
    "dev-idp-secret",
    "sk-...",
    "akia...",
    "ghp_...",
)


@dataclass(frozen=True)
class SecretFinding:
    file: str
    line: int
    pattern: str
    snippet: str


def _is_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    try:
        with path.open("rb") as handle:
            chunk = handle.read(4096)
    except OSError:
        return False
    return b"\x00" not in chunk


def _git_tracked_files(repo_root: Path) -> list[Path]:
    try:
        completed = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        files = []
        for raw in completed.stdout.splitlines():
            rel = raw.strip()
            if not rel:
                continue
            files.append(repo_root / rel)
        return files
    except subprocess.SubprocessError:
        return [path for path in repo_root.rglob("*") if path.is_file()]


def _is_safe_context(line: str, rel_path: str) -> bool:
    lower = line.lower()
    if any(hint in lower for hint in SAFE_LINE_HINTS):
        return True
    if rel_path.startswith("docs/") and "example" in lower:
        return True
    return False


def _scan_secrets(repo_root: Path, files: Iterable[Path]) -> tuple[list[SecretFinding], int]:
    findings: list[SecretFinding] = []
    scanned_files = 0
    for file_path in files:
        try:
            rel_path = file_path.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        if any(rel_path.startswith(prefix) for prefix in SKIP_PREFIXES):
            continue
        if file_path.name in SKIP_NAMES:
            continue
        if not _is_text_file(file_path):
            continue
        scanned_files += 1
        try:
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, start=1):
            for pattern_name, pattern in SECRET_PATTERNS:
                if not pattern.search(line):
                    continue
                if _is_safe_context(line, rel_path):
                    continue
                findings.append(
                    SecretFinding(
                        file=rel_path,
                        line=idx,
                        pattern=pattern_name,
                        snippet=line.strip()[:200],
                    )
                )
    return findings, scanned_files


def _parse_requirements(requirements_path: Path) -> list[dict[str, str]]:
    components: list[dict[str, str]] = []
    if not requirements_path.exists():
        return components
    for raw in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = line.split(";", 1)[0].strip()
        match = re.match(r"^([A-Za-z0-9_.-]+)(.*)$", line)
        if not match:
            continue
        name = match.group(1)
        specifier = match.group(2).strip() or ""
        components.append({"name": name, "specifier": specifier})
    return components


def _parse_frontend_packages(package_json_path: Path) -> list[dict[str, str]]:
    components: list[dict[str, str]] = []
    if not package_json_path.exists():
        return components
    raw = json.loads(package_json_path.read_text(encoding="utf-8"))
    for scope in ("dependencies", "devDependencies"):
        data = raw.get(scope) or {}
        for name, spec in sorted(data.items()):
            components.append({"name": name, "specifier": str(spec), "scope": scope})
    return components


def _build_sbom_manifest(repo_root: Path) -> dict[str, object]:
    backend = _parse_requirements(repo_root / "backend" / "requirements.txt")
    frontend = _parse_frontend_packages(repo_root / "frontend" / "package.json")
    return {
        "format": "onco-sbom-manifest-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "components": {
            "backend": backend,
            "frontend": frontend,
        },
        "counts": {
            "backend": len(backend),
            "frontend": len(frontend),
            "total": len(backend) + len(frontend),
        },
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="OncoAI security hygiene gate (secrets + SBOM manifest)")
    parser.add_argument("--repo-root", default=".", help="Repository root directory")
    parser.add_argument(
        "--sbom-out",
        default="reports/security/sbom_manifest.json",
        help="Path to write generated SBOM manifest",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when secret findings are present",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    tracked_files = _git_tracked_files(repo_root)
    findings, scanned_files = _scan_secrets(repo_root, tracked_files)
    sbom_manifest = _build_sbom_manifest(repo_root)
    sbom_path = Path(args.sbom_out)
    if not sbom_path.is_absolute():
        sbom_path = repo_root / sbom_path
    _write_json(sbom_path, sbom_manifest)

    output = {
        "secret_scan": {
            "scanned_files": scanned_files,
            "findings_count": len(findings),
            "findings": [
                {
                    "file": finding.file,
                    "line": finding.line,
                    "pattern": finding.pattern,
                    "snippet": finding.snippet,
                }
                for finding in findings
            ],
        },
        "sbom_out": sbom_path.as_posix(),
        "sbom_counts": sbom_manifest.get("counts", {}),
    }
    print(json.dumps(output, ensure_ascii=True))

    if args.strict and findings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
