from __future__ import annotations

from pathlib import Path
from typing import Any

from HR.RDL.rdl_parser import build_edited_rdl
from HR.RDL.rdl_storage import load_json, save_edited_rdl, save_json, uploaded_rdl_path, version_original_rdl


def update_textbox_values(report_name: str, textboxes: list[dict[str, Any]]) -> tuple[Path, Path, Path]:
    parsed = load_json(report_name)
    parsed["textboxes"] = textboxes

    version_path = version_original_rdl(report_name)
    json_path = save_json(report_name, parsed)
    edited_bytes = build_edited_rdl(uploaded_rdl_path(report_name), parsed)
    edited_path = save_edited_rdl(report_name, edited_bytes)

    return json_path, version_path, edited_path
