from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import Path


def sanitize_filename(name: str, replacement: str = " ") -> str:
    """Sanitize a display name so it is safe as a single filename segment."""
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', replacement, str(name))
    sanitized = re.sub(r"\.\.+", replacement, sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized)
    sanitized = sanitized.strip(" .")
    return sanitized or "Contractor"


def sanitize_filename_for_legacy_docx(name: str) -> str:
    """Preserve the existing individual DOCX underscore filename style."""
    sanitized = re.sub(r"[^a-zA-Z0-9_\-\s]", "", str(name))
    sanitized = re.sub(r"\s+", "_", sanitized)
    return sanitized.strip("_")


def create_zip_from_paths(files: list[tuple[Path, str]]) -> bytes:
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for path, archive_name in files:
            zip_file.write(path, arcname=archive_name)
    zip_buffer.seek(0)
    return zip_buffer.getvalue()
