from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from Lance.HRIQ_Report_Tool.scraper.downloader import validate_rdl


@dataclass(frozen=True)
class ArchiveResult:
    archive_path: Path
    report_count: int
    archive_size: int
    sha256: str
    created_at: str
    validation_status: str
    sidecar_path: Path


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    if "\x00" in normalized or normalized.startswith(("/", "//")):
        return False
    if re.match(r"^[A-Za-z]:", normalized):
        return False
    return ".." not in PurePosixPath(normalized).parts


def verify_rdl_archive(path: Path) -> tuple[int, dict]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError(f"ZIP integrity failed at member: {bad}")
            names = archive.namelist()
            if any(not _safe_member(name) for name in names):
                raise ValueError("ZIP contains an unsafe member path")
            if len({name.casefold() for name in names}) != len(names):
                raise ValueError("ZIP contains duplicate member paths")
            if "manifest.json" not in names:
                raise ValueError("ZIP manifest is missing")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            reports = manifest.get("reports", [])
            report_names = [item.get("relative_path", "") for item in reports]
            if not report_names:
                raise ValueError("ZIP contains no RDL reports")
            if manifest.get("report_count") != len(report_names):
                raise ValueError("Manifest report count does not match its entries")
            members = set(names)
            missing = [name for name in report_names if name not in members]
            if missing:
                raise ValueError(f"Manifest RDL entry is missing: {missing[0]}")
            actual_rdl = {name for name in names if name.casefold().endswith(".rdl")}
            if actual_rdl != set(report_names):
                raise ValueError("ZIP RDL members do not match the manifest")
            return len(report_names), manifest
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise ValueError(f"Archive verification failed: {exc}") from exc


def create_rdl_archive(
    source_directory: Path,
    archive_directory: Path,
    include_manifest: bool = True,
) -> ArchiveResult:
    if not include_manifest:
        raise ValueError("Production archives require a manifest")
    source = source_directory.resolve()
    destination = archive_directory.resolve()
    if source == destination or source in destination.parents:
        raise ValueError("Archive directory must not be inside the RDL source directory")
    destination.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc)
    timestamp = created.astimezone().strftime("%Y%m%d_%H%M%S")
    final_path = destination / f"HRIQ_RDL_{timestamp}.zip"
    counter = 1
    while final_path.exists():
        final_path = destination / f"HRIQ_RDL_{timestamp}_{counter}.zip"
        counter += 1

    reports: list[dict] = []
    valid_files: list[tuple[Path, str]] = []
    total = 0
    for path in sorted(source.rglob("*.rdl"), key=lambda item: str(item).casefold()):
        if not path.is_file() or path.name.startswith("~") or path.suffix.casefold() != ".rdl":
            continue
        content = path.read_bytes()
        digest, size = validate_rdl(content)
        relative = path.relative_to(source).as_posix()
        if not _safe_member(relative):
            raise ValueError(f"Unsafe source path: {relative}")
        valid_files.append((path, relative))
        total += size
        reports.append({
            "relative_path": relative,
            "size_bytes": size,
            "sha256": digest,
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        })
    if not valid_files:
        raise ValueError("The RDL source directory contains no valid RDL files")

    manifest = {
        "created_at": created.isoformat(),
        "source_root": str(source),
        "report_count": len(reports),
        "total_uncompressed_bytes": total,
        "archive_sha256": None,
        "reports": reports,
    }
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination, prefix=".hriq_archive_", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for path, relative in valid_files:
                archive.write(path, relative)
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        count, _ = verify_rdl_archive(temporary)
        if count != len(reports):
            raise ValueError("Archive report count changed during verification")
        os.replace(temporary, final_path)
        temporary = None
        archive_hash = _file_sha256(final_path)
        sidecar = final_path.with_suffix(final_path.suffix + ".sha256")
        sidecar_temp = sidecar.with_suffix(sidecar.suffix + ".tmp")
        try:
            sidecar_temp.write_text(f"{archive_hash}  {final_path.name}\n", encoding="ascii")
            os.replace(sidecar_temp, sidecar)
        finally:
            if sidecar_temp.exists():
                sidecar_temp.unlink()
        verify_rdl_archive(final_path)
        return ArchiveResult(
            archive_path=final_path,
            report_count=count,
            archive_size=final_path.stat().st_size,
            sha256=archive_hash,
            created_at=created.isoformat(),
            validation_status="Ready",
            sidecar_path=sidecar,
        )
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def stage_uploaded_zip(content: bytes, original_name: str, archive_directory: Path) -> Path:
    archive_directory = archive_directory.resolve()
    archive_directory.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original_name).stem).strip("._") or "uploaded"
    stem = stem[:80]
    digest = hashlib.sha256(content).hexdigest()[:12]
    target = archive_directory / f"{stem}_{digest}.zip"
    if target.exists() and _file_sha256(target) == hashlib.sha256(content).hexdigest():
        return target
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=archive_directory, prefix=".upload_", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        with zipfile.ZipFile(temporary, "r") as archive:
            if archive.testzip():
                raise ValueError("Uploaded ZIP failed integrity validation")
        os.replace(temporary, target)
        temporary = None
        return target
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
