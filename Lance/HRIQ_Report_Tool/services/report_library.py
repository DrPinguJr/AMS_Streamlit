from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    source_path TEXT PRIMARY KEY,
    report_name TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    source_modified REAL NOT NULL,
    schema_path TEXT NOT NULL,
    namespace TEXT,
    description TEXT,
    report_parameters_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL,
    parsed_at TEXT NOT NULL
    ,source_type TEXT NOT NULL DEFAULT 'directory'
    ,source_archive TEXT
    ,source_member TEXT
);
CREATE TABLE IF NOT EXISTS datasets (
    source_path TEXT NOT NULL,
    dataset_name TEXT NOT NULL,
    data_source_name TEXT,
    command_type TEXT,
    fields_json TEXT NOT NULL,
    query_parameters_json TEXT NOT NULL,
    sql_path TEXT,
    PRIMARY KEY (source_path, dataset_name),
    FOREIGN KEY (source_path) REFERENCES reports(source_path) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reports_name ON reports(report_name);
CREATE INDEX IF NOT EXISTS idx_datasets_name ON datasets(dataset_name);
"""


class ReportLibrary:
    def __init__(self, index_path: Path):
        self.index_path = index_path
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(reports)")}
            for name, declaration in (
                ("source_type", "TEXT NOT NULL DEFAULT 'directory'"),
                ("source_archive", "TEXT"),
                ("source_member", "TEXT"),
            ):
                if name not in columns:
                    connection.execute(f"ALTER TABLE reports ADD COLUMN {name} {declaration}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.index_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def stored_hash(self, source_path: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT file_hash FROM reports WHERE source_path = ?", (source_path,)
            ).fetchone()
        return None if row is None else str(row["file_hash"])

    def stored_record(self, source_path: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT source_path, file_hash, source_type, source_archive FROM reports WHERE source_path = ?",
                (source_path,),
            ).fetchone()
        return None if row is None else dict(row)

    def upsert(self, parsed: dict[str, Any], *, file_hash: str, modified: float,
               schema_path: str, parsed_at: str) -> None:
        source_path = parsed["source_path"]
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reports (
                    source_path, report_name, file_hash, source_modified, schema_path,
                    namespace, description, report_parameters_json, warnings_json, parsed_at,
                    source_type, source_archive, source_member
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    report_name=excluded.report_name,
                    file_hash=excluded.file_hash,
                    source_modified=excluded.source_modified,
                    schema_path=excluded.schema_path,
                    namespace=excluded.namespace,
                    description=excluded.description,
                    report_parameters_json=excluded.report_parameters_json,
                    warnings_json=excluded.warnings_json,
                    parsed_at=excluded.parsed_at,
                    source_type=excluded.source_type,
                    source_archive=excluded.source_archive,
                    source_member=excluded.source_member
                """,
                (
                    source_path, parsed["report_name"], file_hash, modified, schema_path,
                    parsed.get("namespace", ""), parsed.get("description", ""),
                    json.dumps(parsed.get("report_parameters", [])),
                    json.dumps(parsed.get("warnings", [])), parsed_at,
                    parsed.get("source_type", "directory"), parsed.get("source_archive"),
                    parsed.get("source_member"),
                ),
            )
            connection.execute("DELETE FROM datasets WHERE source_path = ?", (source_path,))
            connection.executemany(
                """
                INSERT INTO datasets (
                    source_path, dataset_name, data_source_name, command_type,
                    fields_json, query_parameters_json, sql_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        source_path, dataset["name"], dataset.get("data_source_name", ""),
                        dataset.get("command_type", ""), json.dumps(dataset.get("fields", [])),
                        json.dumps(dataset.get("query_parameters", [])), dataset.get("sql_path", ""),
                    )
                    for dataset in parsed.get("datasets", [])
                ],
            )

    def prune_missing(self, source_paths: set[str], source_type: str = "directory") -> int:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT source_path FROM reports WHERE source_type = ?", (source_type,)
            ).fetchall()
            missing = [row["source_path"] for row in rows if row["source_path"] not in source_paths]
            connection.executemany("DELETE FROM reports WHERE source_path = ?", [(p,) for p in missing])
        return len(missing)

    def search(self, query: str = "") -> list[dict[str, Any]]:
        term = f"%{query.strip()}%"
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.*, COUNT(d.dataset_name) AS dataset_count,
                       COALESCE(SUM(json_array_length(d.fields_json)), 0) AS field_count
                FROM reports r
                LEFT JOIN datasets d ON d.source_path = r.source_path
                WHERE r.report_name LIKE ? OR r.source_path LIKE ?
                GROUP BY r.source_path
                ORDER BY r.report_name COLLATE NOCASE, r.source_path COLLATE NOCASE
                """,
                (term, term),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_report(self, source_path: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            report = connection.execute(
                "SELECT * FROM reports WHERE source_path = ?", (source_path,)
            ).fetchone()
            if report is None:
                return None
            datasets = connection.execute(
                "SELECT * FROM datasets WHERE source_path = ? ORDER BY dataset_name COLLATE NOCASE",
                (source_path,),
            ).fetchall()
        result = dict(report)
        result["report_parameters"] = json.loads(result.pop("report_parameters_json"))
        result["warnings"] = json.loads(result.pop("warnings_json"))
        result["datasets"] = []
        for row in datasets:
            dataset = dict(row)
            dataset["fields"] = json.loads(dataset.pop("fields_json"))
            dataset["query_parameters"] = json.loads(dataset.pop("query_parameters_json"))
            result["datasets"].append(dataset)
        return result

    def sql_entries(self) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT r.report_name, r.source_path, d.dataset_name, d.sql_path
                FROM datasets d JOIN reports r ON r.source_path = d.source_path
                WHERE d.sql_path IS NOT NULL AND d.sql_path <> ''
                ORDER BY r.report_name COLLATE NOCASE, d.dataset_name COLLATE NOCASE
                """
            ).fetchall()
        return [dict(row) for row in rows]
