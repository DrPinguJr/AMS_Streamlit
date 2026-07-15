from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CatalogItem:
    item_id: str
    name: str
    path: str
    item_type: str
    hidden: bool = False
    modified_at: str | None = None
    parent_id: str | None = None
    is_linked: bool | None = None
    etag: str | None = None
    raw_shape: tuple[str, ...] = ()

    @property
    def is_folder(self) -> bool:
        value = self.item_type.casefold()
        return value == "1" or value.endswith("folder")

    @property
    def is_report(self) -> bool:
        value = self.item_type.casefold()
        return value == "2" or (value.endswith("report") and not self.is_folder)


@dataclass(frozen=True)
class DownloadResult:
    status: str
    path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ApiStatus:
    available: bool
    status_code: int | None
    message: str
    rest_base_url: str


@dataclass(frozen=True)
class CrawlDiagnostics:
    portal_detected: bool = False
    ssrs_version_marker: str = "SQL Server Reporting Services"
    authentication_mode: str = "automatic"
    rest_status: str = "Not tested"
    rest_base_url: str = ""
    catalog_access: bool = False
    report_content_access: bool = False


def first_value(data: dict[str, Any], *names: str) -> Any:
    folded = {str(key).casefold(): value for key, value in data.items()}
    for name in names:
        if name.casefold() in folded:
            return folded[name.casefold()]
    return None
