from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from Lance.HRIQ_Report_Tool.scraper.downloader import save_rdl_atomic, validate_rdl
from Lance.HRIQ_Report_Tool.scraper.models import ApiStatus, CatalogItem, DownloadResult, first_value


LOGGER = logging.getLogger(__name__)


class SSRSClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, permanent: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.permanent = permanent


def normalize_portal_base_url(url: str) -> str:
    value = url.strip()
    if not value:
        raise ValueError("Portal URL is required")
    parts = urlsplit(value if "://" in value else f"https://{value}")
    if not parts.netloc:
        raise ValueError("Portal URL must include a server name")
    segments = [segment for segment in parts.path.split("/") if segment]
    report_index = next((i for i, segment in enumerate(segments) if segment.casefold() == "reports"), None)
    if report_index is None:
        segments.append("Reports")
    else:
        segments = segments[: report_index + 1]
    path = "/" + "/".join(segments) + "/"
    return urlunsplit((parts.scheme.casefold(), parts.netloc, path, "", ""))


def normalize_catalog_item(data: dict[str, Any]) -> CatalogItem:
    item_id = first_value(data, "Id", "ID", "CatalogItemId")
    name = first_value(data, "Name") or ""
    path = first_value(data, "Path") or ""
    raw_type = first_value(data, "Type", "ItemType", "TypeName")
    numeric_types = {1: "Folder", 2: "Report", 4: "LinkedReport"}
    item_type = numeric_types.get(raw_type, str(raw_type or "Unknown"))
    hidden = bool(first_value(data, "Hidden", "IsHidden") or False)
    modified = first_value(data, "ModifiedDate", "ModifiedAt", "DateModified")
    parent = first_value(data, "ParentFolderId", "ParentId")
    linked = first_value(data, "IsLinked", "LinkedReport", "IsLinkedReport")
    etag = first_value(data, "@odata.etag", "ETag")
    return CatalogItem(
        item_id=str(item_id or "").strip("{}"), name=str(name), path=str(path),
        item_type=item_type, hidden=hidden,
        modified_at=None if modified is None else str(modified),
        parent_id=None if parent is None else str(parent).strip("{}"),
        is_linked=None if linked is None else bool(linked),
        etag=None if etag is None else str(etag),
        raw_shape=tuple(sorted(str(key) for key in data)),
    )


class SSRSClient:
    def __init__(self, portal_url: str, session: requests.Session | None = None, *, timeout: int = 60):
        self.portal_base_url = normalize_portal_base_url(portal_url)
        self.rest_base_url = urljoin(self.portal_base_url, "api/v2.0/")
        self.timeout = timeout
        self.session = session or requests.Session()
        retry = Retry(
            total=3, connect=3, read=3, backoff_factor=0.5,
            backoff_jitter=0.25,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}), respect_retry_after_header=True,
        )
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.setdefault("Accept", "application/json")

    def clone(self) -> "SSRSClient":
        session = requests.Session()
        session.headers.update(self.session.headers)
        session.cookies.update(self.session.cookies)
        session.auth = self.session.auth
        session.verify = self.session.verify
        return SSRSClient(self.portal_base_url, session, timeout=self.timeout)

    @staticmethod
    def _is_json(response: requests.Response) -> bool:
        content_type = response.headers.get("Content-Type", "").casefold()
        return "json" in content_type and not response.content.lstrip()[:32].lower().startswith(b"<html")

    def test_api(self) -> ApiStatus:
        url = urljoin(self.rest_base_url, "CatalogItems?$top=1")
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.exceptions.SSLError as exc:
            LOGGER.exception("SSRS certificate error")
            return ApiStatus(False, None, "Certificate validation failed.", self.rest_base_url)
        except requests.RequestException:
            LOGGER.exception("SSRS connection error")
            return ApiStatus(False, None, "Could not connect to the SSRS REST API.", self.rest_base_url)
        if response.status_code == 401:
            return ApiStatus(False, 401, "Authentication is required.", self.rest_base_url)
        if response.status_code == 403:
            return ApiStatus(False, 403, "Catalog access is not permitted.", self.rest_base_url)
        if response.status_code == 404:
            return ApiStatus(False, 404, "SSRS REST API v2.0 was not found.", self.rest_base_url)
        if response.status_code != 200:
            return ApiStatus(False, response.status_code, f"SSRS REST API returned HTTP {response.status_code}.", self.rest_base_url)
        if not self._is_json(response):
            return ApiStatus(False, 200, "SSRS returned an HTML login or error page.", self.rest_base_url)
        try:
            response.json()
        except ValueError:
            return ApiStatus(False, 200, "SSRS returned malformed JSON.", self.rest_base_url)
        return ApiStatus(True, 200, "Available", self.rest_base_url)

    def enumerate_catalog(self) -> list[CatalogItem]:
        url = urljoin(self.rest_base_url, "CatalogItems?$top=1000")
        items: list[CatalogItem] = []
        seen_pages: set[str] = set()
        while url:
            if url in seen_pages:
                raise SSRSClientError("SSRS catalog pagination loop detected", permanent=True)
            seen_pages.add(url)
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                raise SSRSClientError("Catalog request failed") from exc
            if response.status_code in {401, 403}:
                raise SSRSClientError(
                    "Catalog authentication failed" if response.status_code == 401 else "Catalog access is forbidden",
                    status_code=response.status_code, permanent=True,
                )
            if response.status_code != 200:
                raise SSRSClientError(f"Catalog request returned HTTP {response.status_code}", status_code=response.status_code)
            if not self._is_json(response):
                raise SSRSClientError("Catalog response was HTML instead of JSON", permanent=True)
            try:
                payload = response.json()
            except ValueError as exc:
                raise SSRSClientError("Catalog response was malformed JSON", permanent=True) from exc
            raw_items = payload.get("value", payload if isinstance(payload, list) else [])
            if not isinstance(raw_items, list):
                raise SSRSClientError("Catalog JSON does not contain an item list", permanent=True)
            items.extend(normalize_catalog_item(item) for item in raw_items if isinstance(item, dict))
            next_url = payload.get("@odata.nextLink") if isinstance(payload, dict) else None
            url = urljoin(self.rest_base_url, str(next_url)) if next_url else ""
        return items

    def report_content_url(self, report_id: str) -> str:
        clean = report_id.strip().strip("{}").strip("'")
        if not clean or not re.fullmatch(r"[A-Za-z0-9._-]+", clean):
            raise ValueError("Invalid SSRS report ID")
        return urljoin(self.rest_base_url, f"Reports({quote(clean, safe='-._')})/Content/$value")

    def fetch_report_content(self, report_id: str) -> tuple[bytes, str | None]:
        url = self.report_content_url(report_id)
        headers = {"Accept": "application/xml, application/octet-stream"}
        try:
            response = self.session.get(url, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise SSRSClientError("Report-content request failed") from exc
        if response.status_code in {401, 403}:
            raise SSRSClientError(
                "Report authentication failed" if response.status_code == 401 else "Report access is forbidden",
                status_code=response.status_code, permanent=True,
            )
        if response.status_code != 200:
            raise SSRSClientError(f"Report-content request returned HTTP {response.status_code}", status_code=response.status_code)
        try:
            validate_rdl(response.content)
        except ValueError as exc:
            raise SSRSClientError(str(exc), status_code=200, permanent=True) from exc
        return response.content, response.headers.get("ETag")

    def download_report(self, item: CatalogItem, target: Path) -> DownloadResult:
        if not item.item_id:
            raise SSRSClientError("Report is missing its catalog ID", permanent=True)
        content, _etag = self.fetch_report_content(item.item_id)
        return save_rdl_atomic(content, target)
