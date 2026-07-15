from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import requests
from selenium.webdriver.common.by import By

from Lance.HRIQ_Report_Tool.scraper import selectors
from Lance.HRIQ_Report_Tool.scraper.browser import create_browser


LOGGER = logging.getLogger(__name__)
AUTH_MODES = ("automatic", "current windows session", "interactive browser session", "form login")


def _save_development_failure(driver, download_dir: Path) -> None:
    target = download_dir.resolve().parent / "HRIQ_Dev"
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        driver.save_screenshot(str(target / f"auth_failure_{stamp}.png"))
        title = driver.title or ""
        base = driver.find_elements(By.CSS_SELECTOR, "base[href]")
        base_href = base[0].get_attribute("href") if base else ""
        fields = [
            f"<{item.tag_name} type={item.get_attribute('type')!r} name={item.get_attribute('name')!r}>"
            for item in driver.find_elements(By.CSS_SELECTOR, "form input, form button")[:30]
        ]
        fragment = "\n".join([f"title={title!r}", f"base={base_href!r}", *fields])
        (target / f"auth_shape_{stamp}.txt").write_text(fragment, encoding="utf-8")
    except Exception:
        LOGGER.exception("Could not save sanitised development diagnostics")


def windows_session() -> requests.Session:
    session = requests.Session()
    try:
        from requests_negotiate_sspi import HttpNegotiateAuth
    except ImportError as exc:
        raise RuntimeError("Current Windows authentication requires requests-negotiate-sspi") from exc
    session.auth = HttpNegotiateAuth()
    return session


def portal_ready(driver) -> bool:
    try:
        return bool(driver.find_elements(By.CSS_SELECTOR, selectors.PORTAL_MARKERS))
    except Exception:
        return False


def _form_login(driver, username: str, password: str) -> bool:
    user_fields = driver.find_elements(By.CSS_SELECTOR, selectors.USERNAME)
    password_fields = driver.find_elements(By.CSS_SELECTOR, selectors.PASSWORD)
    if not user_fields or not password_fields:
        return False
    user_fields[0].send_keys(username)
    password_fields[0].send_keys(password)
    submit = driver.find_elements(By.CSS_SELECTOR, selectors.SUBMIT)
    if submit:
        submit[0].click()
    return True


def browser_session(
    portal_url: str,
    download_dir,
    mode: str,
    username: str,
    password: str,
    stop_event: Event,
    update,
    *,
    headless: bool,
    development_mode: bool,
):
    interactive = mode == "interactive browser session"
    driver = create_browser(download_dir, headless=False if interactive else headless, capture_network=development_mode)
    driver.get(portal_url)
    for _ in range(5):
        if portal_ready(driver):
            return driver
        sleep(1)
    if mode == "form login":
        if not _form_login(driver, username, password):
            driver.quit()
            raise RuntimeError("No login form was detected on the portal page")
    elif mode == "automatic" and not headless:
        interactive = True
    elif mode == "automatic" and headless:
        driver.quit()
        update(log="Authentication requires an interactive browser; opening visible Chrome.")
        driver = create_browser(download_dir, headless=False, capture_network=development_mode)
        driver.get(portal_url)
        interactive = True
    if interactive:
        update(log="Complete authentication in the Chrome window. No credentials will be saved.")
    deadline = monotonic() + (300 if interactive else 60)
    while monotonic() < deadline and not stop_event.is_set():
        if portal_ready(driver):
            return driver
        sleep(1)
    if development_mode:
        _save_development_failure(driver, Path(download_dir))
    driver.quit()
    raise RuntimeError("SSRS portal authentication was not completed")


def requests_session_from_browser(driver) -> requests.Session:
    session = requests.Session()
    try:
        session.headers["User-Agent"] = driver.execute_script("return navigator.userAgent")
        for cookie in driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"), path=cookie.get("path", "/"))
    except Exception:
        LOGGER.exception("Could not transfer browser session cookies")
    return session
