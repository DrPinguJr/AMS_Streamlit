from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from Lance.HRIQ_Report_Tool.parser.rdl_parser import parse_rdl_content
from Lance.HRIQ_Report_Tool.parser.sources import DirectoryRdlSource, RdlSource, ZipRdlSource
from Lance.HRIQ_Report_Tool.services.report_library import ReportLibrary


@dataclass
class ParseSummary:
    found: int = 0
    parsed: int = 0
    skipped: int = 0
    removed: int = 0
    errors: list[str] = field(default_factory=list)


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or "dataset"


def parse_source(source: RdlSource, parsed_root: Path, library: ReportLibrary) -> ParseSummary:
    parsed_root.mkdir(parents=True, exist_ok=True)
    try:
        entries = list(source.iter_rdl_entries())
    except Exception as exc:
        return ParseSummary(errors=[str(exc)])
    summary = ParseSummary(found=len(entries))
    current_sources = {entry.logical_path for entry in entries}

    for entry in entries:
        stored = library.stored_record(entry.logical_path)
        if stored and stored["source_type"] == "directory" and entry.source_type == "zip":
            # The mutable directory is always the active source of truth.
            summary.skipped += 1
            continue
        if (
            stored and stored["file_hash"] == entry.content_sha256
            and not (entry.source_type == "directory" and stored["source_type"] == "zip")
        ):
            summary.skipped += 1
            continue
        try:
            with source.open_entry(entry) as stream:
                content = stream.read()
            parsed = parse_rdl_content(
                content, entry.logical_path, entry.modified_at,
                source_type=entry.source_type, source_archive=entry.source_archive,
            )
            relative = Path(*PurePosixPath(entry.logical_path).parts)
            output_dir = parsed_root / relative.parent
            output_dir.mkdir(parents=True, exist_ok=True)
            for dataset in parsed["datasets"]:
                command = dataset.get("command_text", "")
                if not command.strip():
                    dataset["sql_path"] = ""
                    continue
                sql_path = output_dir / f"{safe_name(relative.stem)}_{safe_name(dataset['name'])}.sql"
                header = f"-- Source: {entry.logical_path}\n-- Dataset: {dataset['name']}\n\n"
                sql_path.write_text(header + command, encoding="utf-8")
                dataset["sql_path"] = sql_path.relative_to(parsed_root).as_posix()

            parsed_at = datetime.now(timezone.utc).isoformat()
            parsed["file_hash"] = entry.content_sha256
            parsed["source_modified"] = entry.modified_at.timestamp() if entry.modified_at else 0.0
            parsed["parsed_at"] = parsed_at
            schema_path = output_dir / f"{safe_name(relative.stem)}_schema.json"
            schema_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
            library.upsert(
                parsed, file_hash=entry.content_sha256, modified=parsed["source_modified"],
                schema_path=schema_path.relative_to(parsed_root).as_posix(), parsed_at=parsed_at,
            )
            summary.parsed += 1
        except Exception as exc:
            summary.errors.append(f"{entry.logical_path}: {exc}")

    summary.removed = library.prune_missing(current_sources, source.source_type)
    return summary


def parse_new_or_changed(raw_root: Path, parsed_root: Path, library: ReportLibrary) -> ParseSummary:
    return parse_source(DirectoryRdlSource(raw_root), parsed_root, library)


def parse_zip_new_or_changed(archive_path: Path, parsed_root: Path, library: ReportLibrary, *, limits=None) -> ParseSummary:
    return parse_source(ZipRdlSource(archive_path, limits), parsed_root, library)
