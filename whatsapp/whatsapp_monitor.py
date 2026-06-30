from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from typing import Any

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

try:
    from .whatsapp_storage import make_record_id, save_image_from_base64, save_message_record
except ImportError:
    from whatsapp_storage import make_record_id, save_image_from_base64, save_message_record


SEARCH_BOX_SELECTORS = [
    "div[aria-label='Search input textbox'][contenteditable='true']",
    "div[aria-label='Search or start new chat'][contenteditable='true']",
    "div[aria-label='Search'][contenteditable='true']",
    "div[title='Search input textbox'][contenteditable='true']",
    "div[role='textbox'][contenteditable='true'][aria-label*='Search']",
    "div[contenteditable='true'][data-tab='3']",
]
CHAT_TITLE_SELECTORS = [
    "header span[title]",
    "div[role='button'] span[title]",
]
MESSAGE_SELECTORS = [
    "div[data-id][class*='message-']",
    "div.message-in, div.message-out",
]


def _first_present(driver: Chrome, selectors: list[str], wait_seconds: int = 30) -> WebElement:
    wait = WebDriverWait(driver, wait_seconds)
    last_error: Exception | None = None
    for selector in selectors:
        try:
            return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
        except TimeoutException as exc:
            last_error = exc
    raise TimeoutException(f"Could not find any selector: {selectors}") from last_error


def _first_clickable(driver: Chrome, selectors: list[str], wait_seconds: int = 30) -> WebElement:
    wait = WebDriverWait(driver, wait_seconds)
    last_error: Exception | None = None
    for selector in selectors:
        try:
            return wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        except TimeoutException as exc:
            last_error = exc
    raise TimeoutException(f"Could not click any selector: {selectors}") from last_error


def wait_for_whatsapp_ready(driver: Chrome, wait_seconds: int = 60) -> None:
    wait = WebDriverWait(driver, wait_seconds)
    wait.until(
        lambda d: any(d.find_elements(By.CSS_SELECTOR, selector) for selector in SEARCH_BOX_SELECTORS)
        or any(d.find_elements(By.CSS_SELECTOR, selector) for selector in CHAT_TITLE_SELECTORS)
    )


def _current_chat_title(driver: Chrome) -> str:
    for selector in ["header span[title]", "header [title]"]:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            title = (element.get_attribute("title") or "").strip()
            if title:
                return title
    return ""


def _set_contenteditable_text(driver: Chrome, element: WebElement, text: str) -> None:
    driver.execute_script(
        """
        const element = arguments[0];
        const text = arguments[1];
        element.focus();
        document.execCommand('selectAll', false, null);
        document.execCommand('delete', false, null);
        element.textContent = text;
        element.dispatchEvent(new InputEvent('input', {
            bubbles: true,
            cancelable: true,
            inputType: 'insertText',
            data: text
        }));
        """,
        element,
        text,
    )


def _click_exact_chat_result(driver: Chrome, target: str) -> bool:
    return bool(
        driver.execute_script(
            """
            const target = arguments[0].trim();
            const candidates = [...document.querySelectorAll('span[title]')]
                .filter((node) => (node.getAttribute('title') || '').trim() === target)
                .filter((node) => !node.closest('header'));

            for (const candidate of candidates) {
                const clickable = candidate.closest(
                    "div[role='button'], div[tabindex='0'], div[role='row'], [aria-selected]"
                );
                if (clickable) {
                    clickable.scrollIntoView({ block: 'center' });
                    clickable.click();
                    return true;
                }
            }
            return false;
            """,
            target,
        )
    )


def _xpath_literal(value: str) -> str:
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    parts = value.split('"')
    return "concat(" + ', \'"\', '.join(f'"{part}"' for part in parts) + ")"


def select_whatsapp_chat(driver: Chrome, chat_name: str) -> tuple[bool, str]:
    target = chat_name.strip()
    if not target:
        return False, "Enter an exact WhatsApp group or chat name."

    try:
        wait_for_whatsapp_ready(driver)
        if _current_chat_title(driver).casefold() == target.casefold():
            return True, f"Already opened WhatsApp chat: {target}"

        search_box = _first_clickable(driver, SEARCH_BOX_SELECTORS, wait_seconds=30)
        search_box.click()
        _set_contenteditable_text(driver, search_box, "")
        search_box.send_keys(target)

        result_xpath = (
            "//span[@title="
            + _xpath_literal(target)
            + " and not(ancestor::header)]/ancestor::*[@role='button' or @tabindex='0' or @role='row'][1]"
        )
        try:
            result = WebDriverWait(driver, 12).until(EC.element_to_be_clickable((By.XPATH, result_xpath)))
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", result)
            driver.execute_script("arguments[0].click();", result)
        except TimeoutException:
            clicked = WebDriverWait(driver, 8).until(lambda d: _click_exact_chat_result(d, target))
            if not clicked:
                raise TimeoutException(f"No exact result named {target}.")

        try:
            WebDriverWait(driver, 15).until(lambda d: _current_chat_title(d).casefold() == target.casefold())
        except TimeoutException:
            search_box.send_keys(Keys.ENTER)
            WebDriverWait(driver, 15).until(lambda d: _current_chat_title(d).casefold() == target.casefold())

        return True, f"Opened WhatsApp chat: {target}"
    except TimeoutException:
        current_title = _current_chat_title(driver)
        if current_title:
            return False, f"Could not open exact chat '{target}'. Current chat is '{current_title}'. Check the spelling exactly as shown in WhatsApp."
        return False, f"Could not find an exact chat result named '{target}'. Scan the QR code if needed, then check the spelling."
    except Exception as exc:
        return False, f"Could not select WhatsApp chat: {exc}"


def parse_pre_plain_text(value: str) -> tuple[str, str]:
    match = re.match(r"^\[(?P<timestamp>[^\]]+)\]\s*(?P<sender>.*?):\s*$", value or "")
    if not match:
        return "", ""
    return match.group("timestamp").strip(), match.group("sender").strip()


def _message_elements(driver: Chrome) -> list[WebElement]:
    elements: list[WebElement] = []
    seen_ids: set[str] = set()
    for selector in MESSAGE_SELECTORS:
        for element in driver.find_elements(By.CSS_SELECTOR, selector):
            try:
                marker = element.id
            except StaleElementReferenceException:
                continue
            if marker not in seen_ids:
                seen_ids.add(marker)
                elements.append(element)
    return elements


def _element_text(element: WebElement) -> str:
    text_parts: list[str] = []
    for selector in ["span.selectable-text", "div.copyable-text span", "span[dir='ltr']", "span[dir='auto']"]:
        try:
            for node in element.find_elements(By.CSS_SELECTOR, selector):
                text = (node.text or "").strip()
                if text and text not in text_parts:
                    text_parts.append(text)
        except StaleElementReferenceException:
            return ""
    if text_parts:
        return "\n".join(text_parts)
    return (element.text or "").strip()


def _extract_image_base64(driver: Chrome, element: WebElement) -> str | None:
    images = element.find_elements(By.CSS_SELECTOR, "img")
    for image in images:
        src = image.get_attribute("src") or ""
        if not src or "data:image" in src:
            return src if src.startswith("data:image") else None
        try:
            return driver.execute_script(
                """
                const img = arguments[0];
                if (!img.complete || !img.naturalWidth || !img.naturalHeight) {
                    return null;
                }
                const canvas = document.createElement('canvas');
                canvas.width = img.naturalWidth;
                canvas.height = img.naturalHeight;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0);
                return canvas.toDataURL('image/png');
                """,
                image,
            )
        except Exception:
            return None
    return None


def extract_message_record(driver: Chrome, element: WebElement, chat_name: str) -> dict[str, Any] | None:
    try:
        classes = element.get_attribute("class") or ""
        direction = "outgoing" if "message-out" in classes else "incoming" if "message-in" in classes else ""
        data_id = element.get_attribute("data-id") or ""

        copyable = None
        try:
            copyable = element.find_element(By.CSS_SELECTOR, "div.copyable-text")
        except NoSuchElementException:
            pass

        metadata = copyable.get_attribute("data-pre-plain-text") if copyable else ""
        timestamp, sender = parse_pre_plain_text(metadata or "")
        text = _element_text(element)
        image_base64 = _extract_image_base64(driver, element)
        image_path = ""
        image_error = ""

        if image_base64:
            try:
                image_path = str(
                    save_image_from_base64(
                        image_base64,
                        {"chat_name": chat_name, "sender": sender or direction, "timestamp": timestamp},
                    )
                )
            except Exception as exc:
                image_error = str(exc)

        if not text and not image_base64 and not metadata and not data_id:
            return None

        raw_metadata = {
            "data_id": data_id,
            "data_pre_plain_text": metadata or "",
            "class": classes,
            "image_error": image_error,
        }
        record = {
            "chat_name": chat_name,
            "sender": sender or ("Me" if direction == "outgoing" else ""),
            "direction": direction,
            "timestamp": timestamp,
            "text": text,
            "has_image": bool(image_base64),
            "image_path": image_path,
            "raw_metadata": raw_metadata,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
        }
        record["id"] = data_id or make_record_id(record)
        return record
    except StaleElementReferenceException:
        return None


class WhatsAppMonitor:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.seen_ids: set[str] = set()
        self.recent_records: list[dict[str, Any]] = []
        self.status = "Stopped"
        self.last_error = ""
        self.chat_name = ""

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, driver: Chrome, chat_name: str, interval_seconds: float = 3.0) -> tuple[bool, str]:
        if self.is_running:
            return False, "WhatsApp monitor is already running."
        self._stop_event.clear()
        self.chat_name = chat_name
        self.status = "Starting"
        self.last_error = ""
        self._thread = threading.Thread(
            target=self._run,
            args=(driver, chat_name, interval_seconds),
            daemon=True,
            name="whatsapp-monitor",
        )
        self._thread.start()
        return True, f"Started monitoring {chat_name}."

    def stop(self) -> str:
        self._stop_event.set()
        self.status = "Stopping"
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if not self.is_running:
            self.status = "Stopped"
        return "WhatsApp monitor stopped."

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "status": self.status,
                "last_error": self.last_error,
                "chat_name": self.chat_name,
                "recent_records": list(self.recent_records),
                "seen_count": len(self.seen_ids),
                "is_running": self.is_running,
            }

    def _run(self, driver: Chrome, chat_name: str, interval_seconds: float) -> None:
        self.status = "Running"
        while not self._stop_event.is_set():
            try:
                captured = 0
                for element in _message_elements(driver):
                    record = extract_message_record(driver, element, chat_name)
                    if not record or record["id"] in self.seen_ids:
                        continue
                    saved = save_message_record(record)
                    self.seen_ids.add(record["id"])
                    if saved:
                        captured += 1
                    with self._lock:
                        self.recent_records.append(record)
                        self.recent_records = self.recent_records[-100:]
                self.status = f"Running - {len(self.seen_ids)} unique messages seen"
                self.last_error = ""
                if captured:
                    self.status = f"Running - captured {captured} new message(s)"
            except Exception as exc:
                self.last_error = str(exc)
                self.status = "Running with errors"
            self._stop_event.wait(interval_seconds)
        self.status = "Stopped"
