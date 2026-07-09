from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
UPLOADED_RDL_DIR = BASE_DIR / "uploaded_rdl"
PARSED_JSON_DIR = BASE_DIR / "parsed_json"
EDITED_RDL_DIR = BASE_DIR / "edited_rdl"
VERSIONS_DIR = BASE_DIR / "versions"


REQUIRED_DIRS = (
    UPLOADED_RDL_DIR,
    PARSED_JSON_DIR,
    EDITED_RDL_DIR,
    VERSIONS_DIR,
)


def ensure_directories() -> None:
    for folder in REQUIRED_DIRS:
        folder.mkdir(parents=True, exist_ok=True)


def safe_report_name(filename: str) -> str:
    stem = Path(filename).stem.strip() or "report"
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)
    return cleaned.strip("._") or "report"


def uploaded_rdl_path(filename: str) -> Path:
    return UPLOADED_RDL_DIR / f"{safe_report_name(filename)}.rdl"


def parsed_json_path(report_name: str) -> Path:
    return PARSED_JSON_DIR / f"{safe_report_name(report_name)}.json"


def edited_rdl_path(report_name: str) -> Path:
    return EDITED_RDL_DIR / f"{safe_report_name(report_name)}.rdl"


def save_uploaded_rdl(uploaded_file: Any) -> Path:
    ensure_directories()
    target = uploaded_rdl_path(uploaded_file.name)
    target.write_bytes(uploaded_file.getbuffer())
    return target


def save_json(report_name: str, data: dict[str, Any]) -> Path:
    ensure_directories()
    target = parsed_json_path(report_name)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def load_json(report_name: str) -> dict[str, Any]:
    return json.loads(parsed_json_path(report_name).read_text(encoding="utf-8"))


def list_uploaded_reports() -> list[dict[str, Any]]:
    ensure_directories()
    reports = []
    for path in sorted(UPLOADED_RDL_DIR.glob("*.rdl"), key=lambda item: item.name.lower()):
        report_name = safe_report_name(path.name)
        json_path = parsed_json_path(report_name)
        reports.append(
            {
                "report_name": report_name,
                "file_name": path.name,
                "rdl_path": path,
                "json_path": json_path,
                "parsed": json_path.exists(),
                "size_kb": round(path.stat().st_size / 1024, 1),
                "modified": path.stat().st_mtime,
            }
        )
    return reports


def next_version_path(report_name: str) -> Path:
    ensure_directories()
    report_versions = VERSIONS_DIR / safe_report_name(report_name)
    report_versions.mkdir(parents=True, exist_ok=True)
    existing_versions = []
    for path in report_versions.glob("v*.rdl"):
        match = re.fullmatch(r"v(\d+)\.rdl", path.name, flags=re.IGNORECASE)
        if match:
            existing_versions.append(int(match.group(1)))
    next_number = max(existing_versions, default=0) + 1
    return report_versions / f"v{next_number}.rdl"


def version_original_rdl(report_name: str) -> Path:
    source = uploaded_rdl_path(report_name)
    if not source.exists():
        raise FileNotFoundError(f"Original RDL not found for {report_name}.")
    target = next_version_path(report_name)
    shutil.copy2(source, target)
    return target


def save_edited_rdl(report_name: str, content: bytes) -> Path:
    ensure_directories()
    target = edited_rdl_path(report_name)
    target.write_bytes(content)
    return target
