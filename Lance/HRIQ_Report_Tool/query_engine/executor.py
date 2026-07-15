from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import pandas as pd

from Lance.HRIQ_Report_Tool.config.settings import Settings
from Lance.HRIQ_Report_Tool.query_engine.connection import get_engine
from Lance.HRIQ_Report_Tool.query_engine.safety import (
    bind_parameters,
    detect_parameters,
    validate_read_only_sql,
)


@dataclass
class QueryResult:
    data: pd.DataFrame
    elapsed_seconds: float
    truncated: bool


def execute_query(sql: str, parameters: dict[str, Any], settings: Settings) -> QueryResult:
    safe_sql = validate_read_only_sql(sql)
    names = detect_parameters(safe_sql)
    missing = [name for name in names if name not in parameters]
    if missing:
        raise ValueError(f"Missing values for: {', '.join(missing)}")
    prepared = bind_parameters(safe_sql, names)
    started = perf_counter()
    try:
        from sqlalchemy import text
    except ImportError as exc:
        raise RuntimeError("SQL support is not installed. Install the project requirements.") from exc
    with get_engine(settings).connect() as connection:
        result = connection.execute(text(prepared), {name: parameters[name] for name in names})
        columns = list(result.keys())
        rows = result.mappings().fetchmany(settings.sql_row_limit + 1)
    truncated = len(rows) > settings.sql_row_limit
    frame = pd.DataFrame(rows[: settings.sql_row_limit], columns=columns)
    return QueryResult(frame, perf_counter() - started, truncated)
