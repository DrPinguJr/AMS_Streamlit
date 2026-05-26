import os
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

try:
    from TenderProcess import (
        RawTenderResult,
        SaveSummary,
        TenderResult,
        clean_value,
        process_raw_results,
        save_results_to_database,
    )
except ModuleNotFoundError:
    from Tender.TenderProcess import (
        RawTenderResult,
        SaveSummary,
        TenderResult,
        clean_value,
        process_raw_results,
        save_results_to_database,
    )


LOGIN_URL = "https://www.tenderboard.biz/login?destination=tenders"
TENDERS_URL = "https://www.tenderboard.biz/tenders"
ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"

ROW_SELECTOR = "[class*='tenders__resultRow']"
TITLE_LINK_SELECTOR = "[class*='tenders__viewLink']"

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


def close_status_dialog_if_present(
    driver: webdriver.Chrome,
    wait_seconds: int = 5,
    log_fn: LogFn = log,
) -> None:
    try:
        dialog = WebDriverWait(driver, wait_seconds).until(
            EC.visibility_of_element_located((By.ID, "message-dialog"))
        )
    except TimeoutException:
        log_fn("No status dialog shown.")
        return

    close_selectors = [
        "button[aria-label='Close']",
        ".ui-dialog-titlebar-close",
        "button",
        "input[type='button']",
        "input[type='submit']",
        "a",
    ]
    for selector in close_selectors:
        for candidate in dialog.find_elements(By.CSS_SELECTOR, selector):
            label = " ".join(
                filter(
                    None,
                    [
                        candidate.text,
                        candidate.get_attribute("value"),
                        candidate.get_attribute("aria-label"),
                        candidate.get_attribute("title"),
                    ],
                )
            ).strip()
            if "close" in label.lower() or selector == ".ui-dialog-titlebar-close":
                candidate.click()
                WebDriverWait(driver, wait_seconds).until(EC.invisibility_of_element(dialog))
                log_fn("Closed status dialog.")
                return

    log_fn("Status dialog appeared, but no close control was found.")


def login(driver: webdriver.Chrome, username: str, password: str, log_fn: LogFn = log) -> None:
    wait = WebDriverWait(driver, 30)
    driver.get(LOGIN_URL)
    log_fn(f"Opened login page: {LOGIN_URL}")

    close_status_dialog_if_present(driver, log_fn=log_fn)

    username_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#edit-name")))
    password_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#edit-pass")))

    username_input.clear()
    username_input.send_keys(username)
    password_input.clear()
    password_input.send_keys(password)

    submit = wait.until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[type="submit"][value="Log in"]'))
    )
    submit.click()

    wait.until(
        lambda d: "/login" not in d.current_url
        or bool(d.find_elements(By.CSS_SELECTOR, "#search-your-keywords"))
        or bool(d.find_elements(By.CSS_SELECTOR, ROW_SELECTOR))
    )
    log_fn("Login submitted successfully.")


def open_tenders_page(driver: webdriver.Chrome, log_fn: LogFn = log) -> None:
    wait = WebDriverWait(driver, 30)
    if "/tenders" not in driver.current_url:
        driver.get(TENDERS_URL)
        log_fn(f"Opened tenders page: {TENDERS_URL}")

    wait.until(
        EC.any_of(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#search-your-keywords")),
            EC.presence_of_element_located((By.CSS_SELECTOR, ROW_SELECTOR)),
        )
    )


def click_keyword_search(driver: webdriver.Chrome, log_fn: LogFn = log) -> None:
    wait = WebDriverWait(driver, 30)
    search_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#search-your-keywords")))
    search_button.click()
    log_fn("Search button clicked.")


def wait_for_results(driver: webdriver.Chrome, log_fn: LogFn = log) -> list[WebElement]:
    wait = WebDriverWait(driver, 45)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ROW_SELECTOR)))
    wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, ROW_SELECTOR)) > 0)
    rows = driver.find_elements(By.CSS_SELECTOR, ROW_SELECTOR)
    log_fn(f"Tender rows loaded: {len(rows)}")
    return rows


def extract_raw_tender(row: WebElement) -> RawTenderResult:
    title = ""
    link = ""

    try:
        title_link = row.find_element(By.CSS_SELECTOR, TITLE_LINK_SELECTOR)
        title = clean_value(title_link.text)
        link = urljoin(TENDERS_URL, title_link.get_attribute("href") or "")
    except NoSuchElementException:
        lines = [clean_value(line) for line in row.text.splitlines() if clean_value(line)]
        title = lines[0] if lines else ""

    return RawTenderResult(
        tender_title=title,
        tender_link=link,
        raw_text=row.text,
    )


def active_page_number(driver: webdriver.Chrome) -> str:
    try:
        return clean_value(driver.find_element(By.CSS_SELECTOR, "li.btn-numbered-page.active a").text)
    except NoSuchElementException:
        return ""


def next_page_button(driver: webdriver.Chrome) -> WebElement | None:
    try:
        item = driver.find_element(By.CSS_SELECTOR, "li.btn-next-page")
    except NoSuchElementException:
        return None

    if "disabled" in (item.get_attribute("class") or "").lower():
        return None

    try:
        return item.find_element(By.CSS_SELECTOR, "a")
    except NoSuchElementException:
        return None


def go_to_next_page(driver: webdriver.Chrome, log_fn: LogFn = log) -> bool:
    button = next_page_button(driver)
    if button is None:
        log_fn("No more pages to scan.")
        return False

    previous_page = active_page_number(driver)
    previous_rows = driver.find_elements(By.CSS_SELECTOR, ROW_SELECTOR)
    first_previous_row = previous_rows[0] if previous_rows else None

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
    driver.execute_script("arguments[0].click();", button)
    log_fn("Clicked next page.")

    wait = WebDriverWait(driver, 45)
    if first_previous_row is not None:
        try:
            wait.until(EC.staleness_of(first_previous_row))
        except TimeoutException:
            wait.until(lambda d: active_page_number(d) != previous_page)
    else:
        wait.until(lambda d: active_page_number(d) != previous_page)

    wait_for_results(driver, log_fn=log_fn)
    return True


def scrape_raw_pages(driver: webdriver.Chrome, log_fn: LogFn = log) -> list[RawTenderResult]:
    raw_results: list[RawTenderResult] = []
    seen_links: set[str] = set()
    page_count = 1

    while True:
        current_page = active_page_number(driver) or str(page_count)
        log_fn(f"Processing page {current_page}...")
        rows = wait_for_results(driver, log_fn=log_fn)

        for index, row in enumerate(rows, start=1):
            log_fn(f"Processing {current_page}.. {index}...")
            result = extract_raw_tender(row)
            unique_key = result.tender_link or f"{result.tender_title}|{result.raw_text}"
            if unique_key in seen_links:
                continue
            seen_links.add(unique_key)
            raw_results.append(result)

        log_fn(f"Page {current_page} scraped. Total raw rows so far: {len(raw_results)}")

        if not go_to_next_page(driver, log_fn=log_fn):
            break

        page_count += 1

    return raw_results


def scrape_tenderboard(headless: bool = False, log_fn: LogFn = log) -> tuple[list[TenderResult], SaveSummary]:
    load_local_env()

    username = os.getenv("TENDERBOARD_USERNAME")
    password = os.getenv("TENDERBOARD_PASSWORD")

    if not username or not password:
        raise RuntimeError(
            "Set TENDERBOARD_USERNAME and TENDERBOARD_PASSWORD in the local .env file before running."
        )

    driver = build_driver(headless=headless)
    try:
        login(driver, username, password, log_fn=log_fn)
        open_tenders_page(driver, log_fn=log_fn)
        click_keyword_search(driver, log_fn=log_fn)

        raw_results = scrape_raw_pages(driver, log_fn=log_fn)
        log_fn(f"Processing {len(raw_results)} raw rows...")
        results = process_raw_results(raw_results)

        save_summary = save_results_to_database(results)
        log_fn(
            f"Database updated at {save_summary.database_path.resolve()} "
            f"({save_summary.new_count} new, {save_summary.updated_count} updated, "
            f"{save_summary.database_count} total rows)."
        )
        if save_summary.new_output_path is not None:
            log_fn(f"Saved new rows to {save_summary.new_output_path.resolve()}")
        else:
            log_fn("No new rows found, so no dated Excel file was created.")
        return results, save_summary
    finally:
        driver.quit()
        log_fn("Browser closed.")
