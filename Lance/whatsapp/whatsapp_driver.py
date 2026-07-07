from __future__ import annotations

from pathlib import Path

import streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


WHATSAPP_URL = "https://web.whatsapp.com"
ROOT_DIR = Path(__file__).resolve().parents[2]
PROFILE_DIR = ROOT_DIR / "chrome_profiles" / "whatsapp"


@st.cache_resource(show_spinner=False)
def get_whatsapp_driver(profile_dir: str = str(PROFILE_DIR)) -> webdriver.Chrome:
    profile_path = Path(profile_dir)
    profile_path.mkdir(parents=True, exist_ok=True)

    options = Options()
    options.add_argument(f"--user-data-dir={profile_path.resolve()}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1440,1000")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.get(WHATSAPP_URL)
    return driver


def open_whatsapp_web(driver: webdriver.Chrome) -> None:
    if "web.whatsapp.com" not in driver.current_url:
        driver.get(WHATSAPP_URL)


def is_whatsapp_logged_in(driver: webdriver.Chrome) -> bool:
    selectors = [
        "div[role='grid']",
        "div[role='application']",
        "div[aria-label='Chat list']",
        "div[aria-label='Search']",
        "div[aria-label='Search input textbox']",
        "div[aria-label='Search or start new chat']",
        "div[role='textbox'][contenteditable='true']",
        "div[contenteditable='true'][data-tab]",
        "header span[title]",
    ]
    return any(driver.find_elements("css selector", selector) for selector in selectors)


def has_qr_login(driver: webdriver.Chrome) -> bool:
    selectors = [
        "canvas[aria-label*='Scan']",
        "canvas",
        "div[data-ref]",
    ]
    return any(driver.find_elements("css selector", selector) for selector in selectors)
