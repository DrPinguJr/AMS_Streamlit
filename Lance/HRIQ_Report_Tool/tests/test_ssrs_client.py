import json
from pathlib import Path

import pytest
import requests

from Lance.HRIQ_Report_Tool.scraper.downloader import save_rdl_atomic, validate_rdl
from Lance.HRIQ_Report_Tool.scraper.ssrs_client import SSRSClient, SSRSClientError, normalize_catalog_item


FIXTURES = Path(__file__).parent / "fixtures"


class Response:
    def __init__(self, status=200, payload=None, content=None, content_type="application/json", headers=None):
        self.status_code = status
        self._payload = payload
        self.content = content if content is not None else json.dumps(payload).encode()
        self.headers = {"Content-Type": content_type, **(headers or {})}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class Session(requests.Session):
    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.responses.pop(0)


def test_catalog_normalisation_and_report_url() -> None:
    data = json.loads((FIXTURES / "ssrs_catalog_response.json").read_text(encoding="utf-8"))
    item = normalize_catalog_item(data["value"][1])
    assert item.item_id == "22222222-2222-2222-2222-222222222222"
    assert item.is_report
    client = SSRSClient("https://server/Reports/", Session([]))
    assert client.report_content_url(item.item_id).endswith(
        "/Reports/api/v2.0/Reports(22222222-2222-2222-2222-222222222222)/Content/$value"
    )


@pytest.mark.parametrize("status,message", [(401, "Authentication"), (403, "permitted")])
def test_api_auth_statuses(status: int, message: str) -> None:
    result = SSRSClient("https://server/Reports", Session([Response(status=status)])).test_api()
    assert not result.available and result.status_code == status and message in result.message


def test_api_rejects_html_and_malformed_json() -> None:
    html = Response(payload=None, content=b"<html>login</html>", content_type="text/html")
    malformed = Response(payload=ValueError("bad"), content=b"{", content_type="application/json")
    assert "HTML" in SSRSClient("https://server/Reports", Session([html])).test_api().message
    assert "malformed" in SSRSClient("https://server/Reports", Session([malformed])).test_api().message


def test_catalog_enumeration_and_content_validation(sample_rdl: str) -> None:
    payload = json.loads((FIXTURES / "ssrs_catalog_response.json").read_text(encoding="utf-8"))
    session = Session([Response(payload=payload), Response(content=sample_rdl.encode(), content_type="application/xml")])
    client = SSRSClient("https://server/Reports", session)
    items = client.enumerate_catalog()
    content, _ = client.fetch_report_content(items[1].item_id)
    assert len(items) == 2
    assert validate_rdl(content)[1] == len(content)


def test_report_content_rejects_html_and_malformed_rdl() -> None:
    for content in (b"<html>login</html>", b"<Report>"):
        client = SSRSClient("https://server/Reports", Session([Response(content=content, content_type="text/html")]))
        with pytest.raises(SSRSClientError):
            client.fetch_report_content("known-id")


def test_atomic_replacement_and_unchanged_skip(tmp_path: Path, sample_rdl: str) -> None:
    target = tmp_path / "report.rdl"
    first = save_rdl_atomic(sample_rdl.encode(), target)
    second = save_rdl_atomic(sample_rdl.encode(), target)
    assert first.status == "downloaded" and second.status == "skipped"
    original = target.read_bytes()
    with pytest.raises(ValueError):
        save_rdl_atomic(b"<html>error</html>", target)
    assert target.read_bytes() == original
