from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, Protocol


@dataclass(frozen=True)
class RdlEntry:
    logical_path: str
    size_bytes: int
    modified_at: datetime | None
    fingerprint: str
    content_sha256: str
    source_type: str
    source_archive: str | None = None
    crc: int | None = None


class RdlSource(Protocol):
    source_type: str

    def iter_rdl_entries(self) -> Iterable[RdlEntry]: ...
    def open_entry(self, entry: RdlEntry) -> BinaryIO: ...


@dataclass(frozen=True)
class ZipLimits:
    max_entries: int = 20_000
    max_rdl_size_bytes: int = 100 * 1024 * 1024
    max_total_uncompressed_bytes: int = 5_000 * 1024 * 1024
    max_compression_ratio: int = 200


@dataclass(frozen=True)
class ZipInspection:
    archive_name: str
    rdl_count: int
    folder_count: int
    total_uncompressed_bytes: int
    manifest_present: bool
    valid: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_logical_path(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Archive member contains a null byte")
    normalized = value.replace("\\", "/")
    if normalized.startswith(("/", "//")) or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"Unsafe absolute archive member: {value!r}")
    parts = PurePosixPath(normalized).parts
    if any(part in {"..", ""} for part in parts):
        raise ValueError(f"Unsafe archive member traversal: {value!r}")
    return PurePosixPath(*parts).as_posix()


class DirectoryRdlSource:
    source_type = "directory"

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def iter_rdl_entries(self) -> Iterable[RdlEntry]:
        for path in sorted(self.root.rglob("*.rdl"), key=lambda item: str(item).casefold()):
            if not path.is_file():
                continue
            content = path.read_bytes()
            stat = path.stat()
            yield RdlEntry(
                logical_path=path.relative_to(self.root).as_posix(),
                size_bytes=len(content),
                modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                fingerprint=_sha256(
                    f"{path.relative_to(self.root).as_posix()}\0{len(content)}\0{stat.st_mtime_ns}\0{_sha256(content)}".encode()
                ),
                content_sha256=_sha256(content),
                source_type=self.source_type,
            )

    def open_entry(self, entry: RdlEntry) -> BinaryIO:
        path = self.root.joinpath(*PurePosixPath(entry.logical_path).parts).resolve()
        if self.root not in path.parents:
            raise ValueError("Unsafe directory entry")
        return path.open("rb")


class ZipRdlSource:
    source_type = "zip"

    def __init__(self, archive_path: Path, limits: ZipLimits | None = None):
        self.archive_path = archive_path.resolve()
        self.limits = limits or ZipLimits()
        self._entries: list[RdlEntry] | None = None
        self._warnings: list[str] = []
        self._manifest_present = False

    def _scan(self) -> list[RdlEntry]:
        if self._entries is not None:
            return self._entries
        entries: list[RdlEntry] = []
        seen: set[str] = set()
        total = 0
        folders: set[str] = set()
        try:
            archive = zipfile.ZipFile(self.archive_path, "r")
        except (OSError, zipfile.BadZipFile) as exc:
            raise ValueError(f"Invalid ZIP archive: {exc}") from exc
        with archive:
            infos = archive.infolist()
            if len(infos) > self.limits.max_entries:
                raise ValueError(f"ZIP contains more than {self.limits.max_entries} entries")
            for info in infos:
                logical = _safe_logical_path(info.filename)
                key = logical.casefold()
                if key in seen:
                    raise ValueError(f"Duplicate archive member path: {logical}")
                seen.add(key)
                if info.is_dir():
                    continue
                if info.flag_bits & 0x1:
                    raise ValueError(f"Encrypted archive member is not supported: {logical}")
                if logical.casefold() == "manifest.json":
                    self._manifest_present = True
                    continue
                if not logical.casefold().endswith(".rdl"):
                    self._warnings.append(f"Ignored non-RDL member: {logical}")
                    continue
                if info.file_size > self.limits.max_rdl_size_bytes:
                    raise ValueError(f"RDL member exceeds size limit: {logical}")
                total += info.file_size
                if total > self.limits.max_total_uncompressed_bytes:
                    raise ValueError("ZIP total uncompressed RDL size exceeds configured limit")
                compressed = max(info.compress_size, 1)
                if info.file_size / compressed > self.limits.max_compression_ratio:
                    raise ValueError(f"Suspicious compression ratio for: {logical}")
                try:
                    content = archive.read(info)
                except (RuntimeError, zipfile.BadZipFile) as exc:
                    raise ValueError(f"Cannot safely read archive member {logical}: {exc}") from exc
                if len(content) != info.file_size:
                    raise ValueError(f"Archive member size mismatch: {logical}")
                try:
                    modified = datetime(*info.date_time, tzinfo=timezone.utc)
                except ValueError:
                    modified = None
                # The content hash is authoritative; the remaining ZIP metadata makes
                # the provenance stable and inspectable without trusting archive mtime.
                digest = _sha256(content)
                fingerprint_data = (
                    f"{logical}\0{info.file_size}\0{info.CRC}\0{info.date_time!r}\0{digest}".encode("utf-8")
                )
                entries.append(RdlEntry(
                    logical_path=logical,
                    size_bytes=info.file_size,
                    modified_at=modified,
                    fingerprint=_sha256(fingerprint_data),
                    content_sha256=digest,
                    source_type=self.source_type,
                    source_archive=str(self.archive_path),
                    crc=info.CRC,
                ))
                parent = PurePosixPath(logical).parent
                while parent != PurePosixPath("."):
                    folders.add(parent.as_posix())
                    parent = parent.parent
        self._folder_count = len(folders)
        self._total_uncompressed = total
        self._entries = entries
        return entries

    def iter_rdl_entries(self) -> Iterable[RdlEntry]:
        return iter(self._scan())

    def open_entry(self, entry: RdlEntry) -> BinaryIO:
        logical = _safe_logical_path(entry.logical_path)
        with zipfile.ZipFile(self.archive_path, "r") as archive:
            content = archive.read(logical)
        if _sha256(content) != entry.content_sha256:
            raise ValueError(f"ZIP member changed while being read: {logical}")
        return io.BytesIO(content)

    def inspect(self) -> ZipInspection:
        entries = self._scan()
        return ZipInspection(
            archive_name=self.archive_path.name,
            rdl_count=len(entries),
            folder_count=getattr(self, "_folder_count", 0),
            total_uncompressed_bytes=getattr(self, "_total_uncompressed", 0),
            manifest_present=self._manifest_present,
            valid=bool(entries),
            warnings=tuple(self._warnings),
        )
