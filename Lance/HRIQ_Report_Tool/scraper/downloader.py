from __future__ import annotations

import re
import hashlib
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

import requests

from Lance.HRIQ_Report_Tool.scraper.models import DownloadResult


WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _safe_segment(value: str, *, max_length: int = 100) -> str:
    value = unquote(value).replace("\x00", "")
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).rstrip(" .")
    cleaned = cleaned or "_"
    if cleaned.split(".", 1)[0].upper() in WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    if len(cleaned) > max_length:
        suffix = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:10]
        cleaned = f"{cleaned[:max_length - 11]}_{suffix}"
    return cleaned


def remote_path_to_local(raw_root: Path, remote_path: str, root_segment: str) -> Path:
    parts = [part for part in PurePosixPath(unquote(remote_path)).parts if part not in {"/", "", "."}]
    if any(part == ".." for part in parts):
        raise ValueError("Unsafe remote path")
    if parts and root_segment and parts[0].casefold() == root_segment.casefold():
        parts = parts[1:]
    if not parts:
        raise ValueError("Report path is empty")
    safe_parts = [_safe_segment(part, max_length=80) for part in parts]
    safe_parts[-1] = safe_parts[-1] if safe_parts[-1].casefold().endswith(".rdl") else f"{safe_parts[-1]}.rdl"
    target = raw_root.joinpath(*safe_parts).resolve()
    root = raw_root.resolve()
    if target == root or root not in target.parents:
        raise ValueError("Unsafe download path")
    if len(str(target)) > 245:
        available = 240 - len(str(root)) - len(safe_parts)
        segment_limit = max(12, available // len(safe_parts))
        safe_parts = [_safe_segment(part, max_length=segment_limit) for part in parts]
        safe_parts[-1] = safe_parts[-1] if safe_parts[-1].casefold().endswith(".rdl") else f"{safe_parts[-1]}.rdl"
        target = root.joinpath(*safe_parts).resolve()
    if len(str(target)) > 245:
        raise ValueError("Mapped report path exceeds the safe Windows path limit")
    return target


def validate_rdl(content: bytes) -> tuple[str, int]:
    if not content or not content.strip():
        raise ValueError("Downloaded report definition is empty")
    prefix = content.lstrip()[:256].lower()
    if prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html"):
        raise ValueError("Server returned an HTML login or error page")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError("Downloaded response is not valid XML") from exc
    if root.tag.rsplit("}", 1)[-1] != "Report":
        raise ValueError("Downloaded XML is not an SSRS Report")
    namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    if namespace and "reportdefinition" not in namespace.casefold():
        raise ValueError("XML does not use an SSRS report-definition namespace")
    return hashlib.sha256(content).hexdigest(), len(content)


def save_rdl_atomic(content: bytes, target: Path) -> DownloadResult:
    digest, size = validate_rdl(content)
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
        return DownloadResult("skipped", target, digest, size)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        validate_rdl(temporary.read_bytes())
        os.replace(temporary, target)
        return DownloadResult("downloaded", target, digest, size)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def download_rdl(session: requests.Session, url: str, target: Path) -> str:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    return save_rdl_atomic(response.content, target).status
