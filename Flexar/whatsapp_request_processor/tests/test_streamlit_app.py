from __future__ import annotations

from pathlib import Path

import pytest


def test_streamlit_page_loads_without_tabs(tmp_path, monkeypatch) -> None:
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "streamlit.db"))
    app_path = Path("Flexar/whatsapp_request_processor/app.py")
    at = AppTest.from_file(str(app_path), default_timeout=15)
    at.run()
    assert not at.exception
    page_text = "\n".join([*(str(item.value) for item in at.title), *(str(item.value) for item in at.markdown)])
    assert "Flexar WhatsApp Request Processor" in page_text
    assert "SIMULATION MODE" in page_text
    assert "AUTOMATION ON" in page_text
    assert len(at.tabs) == 0
    assert not [button for button in at.button if "Approve and Queue Both Actions" in button.label]


def test_duplicate_button_does_not_crash(tmp_path, monkeypatch) -> None:
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "streamlit_duplicate.db"))
    at = AppTest.from_file("Flexar/whatsapp_request_processor/app.py", default_timeout=15)
    at.run()
    duplicate_buttons = [button for button in at.button if "Payload F" in button.label]
    assert duplicate_buttons
    duplicate_buttons[0].click().run()
    assert not at.exception
