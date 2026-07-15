from __future__ import annotations

from pathlib import Path


def create_browser(download_dir: Path, *, headless: bool = True, capture_network: bool = False):
    from selenium import webdriver

    download_dir.mkdir(parents=True, exist_ok=True)
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(download_dir.resolve()),
            "download.prompt_for_download": False,
            "safebrowsing.enabled": True,
        },
    )
    if capture_network:
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(options=options)
