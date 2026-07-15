from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=128)
def _read_json(path: str, modified_ns: int) -> dict[str, Any]:
    del modified_ns
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_json_cached(path: Path) -> dict[str, Any]:
    return _read_json(str(path.resolve()), path.stat().st_mtime_ns)


def clear_file_cache() -> None:
    _read_json.cache_clear()
