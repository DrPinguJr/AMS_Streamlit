import os
import time
from pathlib import Path
from typing import Callable

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

try:
    from SesamiProcess import (
        RawSesamiRow,
        SesamiRow,
        clean_value,
        normalize_sesami_rows,
        save_sesami_results,
    )
except ModuleNotFoundError:
    from Lance.Sesami.SesamiProcess import (
        RawSesamiRow,
        SesamiRow,
        clean_value,
        normalize_sesami_rows,
        save_sesami_results,
    )


LOGIN_URL = "https://swc.sesami.online/login"
ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT_DIR / ".env"

SELECTORS = {
    "close_modal": 'button.close.close-modal[aria-label="Close"]',
    "username_input": 'input.username-tb[name="username-mybiz"]',
    "username_login_button": "button.login-btn-popup",
    "password_input": 'input.password-tb#password[name="password"]',
    "password_login_button": 'button.login-btn[type="submit"]',
    "business_opportunity_link": "a#GoToBusinessOpportunity_link",
    "business_opportunity_table": "table#BusinessOpportunity",
    "business_opportunity_rows": 'table#BusinessOpportunity tr[id^="BusinessOpportunity_"]',
}

COLUMN_SELECTORS = {
    "action_status_text": "td.Action",
    "s_no": "td.SNo",
    "calling_entity": "td.Buyer",
    "ref_no": "td.Rfqno",
    "document_type": "td.Doctype",
    "products_services_category": "td.Catname",
    "description": "td.Description",
    "submission": "td.Submission",
    "starting_date": "td.Opendate",
    "closing_date": "td.Closedate",
}

LogFn = Callable[[str], None]


def log(message: str) -> None:
    print(message, flush=True)


def load_local_env(env_path: Path = ENV_PATH) -> None:
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_driver(headless: bool = False) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1440,1000")

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def close_modal_if_present(
    driver: webdriver.Chrome,
    wait_seconds: int = 5,
    log_fn: LogFn = log,
) -> None:
    try:
        close_button = WebDriverWait(driver, wait_seconds).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTORS["close_modal"]))
        )
    except TimeoutException:
        log_fn("No Sesami modal shown.")
        return

    close_button.click()
    log_fn("Closed Sesami modal.")


def element_exists(driver: webdriver.Chrome, selector: str) -> bool:
    return bool(driver.find_elements(By.CSS_SELECTOR, selector))


def open_business_opportunity(driver: webdriver.Chrome, log_fn: LogFn = log) -> None:
    wait = WebDriverWait(driver, 45)
    link = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTORS["business_opportunity_link"])))
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link)
    driver.execute_script("arguments[0].click();", link)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, SELECTORS["business_opportunity_table"])))
    log_fn("Opened Sesami Business Opportunity page.")


def login_sesami(driver: webdriver.Chrome, username: str, password: str, log_fn: LogFn = log) -> None:
    wait = WebDriverWait(driver, 45)
    driver.get(LOGIN_URL)
    log_fn(f"Opened Sesami login page: {LOGIN_URL}")

    close_modal_if_present(driver, log_fn=log_fn)

    if element_exists(driver, SELECTORS["business_opportunity_link"]):
        log_fn("Sesami session is already logged in.")
        open_business_opportunity(driver, log_fn=log_fn)
        return

    username_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTORS["username_input"])))
    username_input.clear()
    username_input.send_keys(username)

    username_button = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTORS["username_login_button"]))
    )
    username_button.click()
    log_fn("Submitted Sesami username.")

    password_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTORS["password_input"])))
    password_input.clear()
    password_input.send_keys(password)

    password_button = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, SELECTORS["password_login_button"]))
    )
    password_button.click()
    log_fn("Submitted Sesami password.")

    open_business_opportunity(driver, log_fn=log_fn)


def cell_text(row: WebElement, selector: str) -> str:
    try:
        return clean_value(row.find_element(By.CSS_SELECTOR, selector).text)
    except (NoSuchElementException, StaleElementReferenceException):
        return ""


def extract_raw_sesami_row(row: WebElement) -> RawSesamiRow:
    values = {field: cell_text(row, selector) for field, selector in COLUMN_SELECTORS.items()}
    return RawSesamiRow(**values)


def visible_sesami_rows(driver: webdriver.Chrome) -> list[WebElement]:
    return driver.find_elements(By.CSS_SELECTOR, SELECTORS["business_opportunity_rows"])


def scroll_container(driver: webdriver.Chrome) -> WebElement:
    return driver.execute_script(
        """
        const table = document.querySelector(arguments[0]);
        let node = table ? table.parentElement : null;
        while (node && node !== document.body) {
            const style = window.getComputedStyle(node);
            const scrollable = ['auto', 'scroll'].includes(style.overflowY);
            if (scrollable && node.scrollHeight > node.clientHeight) {
                return node;
            }
            node = node.parentElement;
        }
        return document.scrollingElement || document.documentElement;
        """,
        SELECTORS["business_opportunity_table"],
    )


def scroll_to_load_all_rows(driver: webdriver.Chrome, log_fn: LogFn = log) -> list[RawSesamiRow]:
    wait = WebDriverWait(driver, 30)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, SELECTORS["business_opportunity_table"])))

    container = scroll_container(driver)
    raw_rows_by_key: dict[str, RawSesamiRow] = {}
    stable_rounds = 0
    previous_scroll_top = -1

    while stable_rounds < 4:
        rows = visible_sesami_rows(driver)
        before_count = len(raw_rows_by_key)

        for index, row in enumerate(rows):
            raw_row = extract_raw_sesami_row(row)
            key = "|".join(
                [
                    clean_value(raw_row.ref_no).lower(),
                    clean_value(raw_row.calling_entity).lower(),
                    clean_value(raw_row.closing_date).lower(),
                ]
            )
            if not key.strip("|"):
                key = clean_value(row.get_attribute("id") or row.text or str(index)).lower()
            raw_rows_by_key[key] = raw_row

        current_count = len(raw_rows_by_key)
        log_fn(f"Sesami visible rows: {len(rows)}. Unique rows collected: {current_count}.")

        scroll_state = driver.execute_script(
            """
            const container = arguments[0];
            const beforeTop = container.scrollTop;
            container.scrollTop = container.scrollHeight;
            container.dispatchEvent(new Event('scroll', { bubbles: true }));
            return {
                beforeTop,
                afterTop: container.scrollTop,
                scrollHeight: container.scrollHeight,
                clientHeight: container.clientHeight
            };
            """,
            container,
        )

        time.sleep(1)

        after_top = int(scroll_state.get("afterTop") or 0)
        no_new_rows = current_count == before_count
        no_scroll_movement = after_top == previous_scroll_top
        at_bottom = after_top + int(scroll_state.get("clientHeight") or 0) >= int(
            scroll_state.get("scrollHeight") or 0
        ) - 2

        if no_new_rows and (no_scroll_movement or at_bottom):
            stable_rounds += 1
        else:
            stable_rounds = 0

        previous_scroll_top = after_top

    return list(raw_rows_by_key.values())


def scrape_sesami_business_opportunities(
    headless: bool = False,
    log_fn: LogFn = log,
) -> tuple[list[SesamiRow], Path]:
    load_local_env()

    username = os.getenv("SESAMI_USERNAME")
    password = os.getenv("SESAMI_PASSWORD")

    if not username or not password:
        raise RuntimeError("Set SESAMI_USERNAME and SESAMI_PASSWORD in the local .env file before running.")

    driver = build_driver(headless=headless)
    try:
        login_sesami(driver, username, password, log_fn=log_fn)
        raw_rows = scroll_to_load_all_rows(driver, log_fn=log_fn)
        if not raw_rows:
            log_fn("Sesami Business Opportunity table loaded, but no rows were found.")

        normalized_rows = normalize_sesami_rows(raw_rows)
        saved_path = save_sesami_results(normalized_rows)
        log_fn(f"Saved {len(normalized_rows)} Sesami rows to {saved_path.resolve()}")
        return normalized_rows, saved_path
    finally:
        driver.quit()
        log_fn("Sesami browser closed.")
