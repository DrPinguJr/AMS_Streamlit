"""Daily TenderBoard scrape -> Gemini relevance classifier -> Slack digest.

Runs the existing TenderBoard scraper (`TenderScrape.scrape_tenderboard`),
keeps only the tenders that are new since the last run, asks Gemini to sort
them into confirmed / likely / rejected manpower-staffing relevance, and
posts the full breakdown (all three buckets, nothing dropped) to a Slack
Workflow Builder webhook. Designed to be triggered daily by
`.github/workflows/tenderboard-daily.yml`, but `main()` also runs fine
locally (reads a local `.env`, same as the Streamlit page).

Every step degrades gracefully rather than raising past the top: a Gemini
failure buckets everything as "likely" (fail open, not silent), a missing
Gemini key does the same. A flaky dependency should never crash the whole
run before we know whether anything was found. Note: `send_slack_digest`
still raises on failure, so a broken webhook surfaces as a failed run
(which is the point of the daily job).

Required environment variables (set as GitHub Actions secrets, never
committed - see the workflow file for the exact secret names):
    TENDERBOARD_USERNAME   - TenderBoard login used by the scraper
    TENDERBOARD_PASSWORD   - TenderBoard login used by the scraper
    GEMINI_API_KEY          - Google GenAI API key
    SLACK_WEBHOOK_URL       - Slack Workflow Builder webhook trigger URL

The Slack webhook is a Workflow Builder trigger (hooks.slack.com/triggers/...),
not a classic Incoming Webhook, so the POST body must match the workflow's
own input variable name rather than the classic `{"text": ...}` shape. This
workflow's trigger expects a single variable called `message`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import pandas as pd
import requests

try:
    from TenderScrape import load_local_env, log, scrape_tenderboard
except ModuleNotFoundError:
    from Lance.Tender.TenderScrape import load_local_env, log, scrape_tenderboard

# Update this if the pinned google-genai release retires the model.
GEMINI_MODEL_NAME = "gemini-2.5-flash"

_SYSTEM_INSTRUCTION = (
    "You are screening daily tender titles for a manpower/staffing agency "
    "(temp staffing, recruitment, outsourced labour, and facilities/security/"
    "cleaning/healthcare manpower and HR services contracts). Classify EVERY "
    "title in the input into exactly one category:\n"
    '  "confirmed" - clearly a manpower/staffing/recruitment/outsourced-labour '
    "contract, or facilities/security/cleaning/healthcare manpower and HR "
    "services.\n"
    '  "likely" - plausibly involves a manpower/staffing component but the '
    "title is ambiguous or mixes in other scope (e.g. a facilities-management "
    "contract that may include manpower).\n"
    '  "rejected" - clearly unrelated (e.g. construction works, IT hardware, '
    "pure goods supply).\n"
    "Return ONLY a JSON array of objects, one per input title, each with the "
    'exact keys "title" (unchanged from the input) and "category" (one of '
    '"confirmed", "likely", "rejected"). Include every input title exactly once.'
)

_CATEGORIES = ("confirmed", "likely", "rejected")


@dataclass(frozen=True)
class DigestTender:
    title: str
    link: str
    closing_date: str
    company: str


def scrape_tenders(headless: bool = True) -> list[DigestTender]:
    """Run the TenderBoard scraper and return only tenders new since the last run.

    Reuses `scrape_tenderboard`'s own dedupe against the saved database, so
    on a normal day (nothing new) this returns an empty list rather than
    re-reporting everything already seen.
    """

    _, save_summary = scrape_tenderboard(headless=headless, log_fn=log)
    if save_summary.new_output_path is None:
        return []

    dataframe = pd.read_excel(save_summary.new_output_path)
    tenders: list[DigestTender] = []
    for row in dataframe.to_dict("records"):
        tenders.append(
            DigestTender(
                title=str(row.get("tender_title", "") or "").strip(),
                link=str(row.get("tender_link", "") or "").strip(),
                closing_date=str(row.get("closing_date", "") or "").strip(),
                company=str(row.get("company_organisation_name", "") or "").strip(),
            )
        )
    return tenders


def classify_tenders(tenders: list[DigestTender]) -> dict[str, list[DigestTender]]:
    """Ask Gemini to sort `tenders` into confirmed / likely / rejected buckets.

    Unlike a simple keep/drop filter, every tender is kept somewhere - the
    digest reports the full picture (strong matches, borderline ones worth a
    human glance, and what got screened out) rather than silently dropping
    anything. Any failure (missing key, missing dependency, malformed
    response, network error, a title Gemini's response omits) falls back to
    bucketing the affected tenders as "likely" rather than losing or
    wrongly rejecting them - a noisier digest beats a lost tender.
    """

    empty: dict[str, list[DigestTender]] = {category: [] for category in _CATEGORIES}
    if not tenders:
        return empty

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log("GEMINI_API_KEY is not set; skipping relevance classification.")
        return {**empty, "likely": list(tenders)}

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        log("google-genai is not installed; skipping relevance classification.")
        return {**empty, "likely": list(tenders)}

    by_title = {tender.title: tender for tender in tenders}
    titles = [tender.title for tender in tenders]
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=f"Tender titles: {json.dumps(titles)}",
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
            ),
        )
        classifications = json.loads(response.text)
    except Exception as exc:  # noqa: BLE001 - any provider/network failure degrades gracefully
        log(f"Gemini relevance classification failed ({exc}); keeping all tenders as likely.")
        return {**empty, "likely": list(tenders)}

    result: dict[str, list[DigestTender]] = {category: [] for category in _CATEGORIES}
    classified_titles: set[str] = set()
    for item in classifications:
        title = str(item.get("title", "")).strip()
        category = str(item.get("category", "")).strip().lower()
        tender = by_title.get(title)
        if tender is None or category not in result or title in classified_titles:
            continue
        result[category].append(tender)
        classified_titles.add(title)

    # A malformed or partial Gemini response shouldn't lose tenders - anything
    # it didn't classify still needs a human to see it.
    for tender in tenders:
        if tender.title not in classified_titles:
            result["likely"].append(tender)

    return result


def _format_tender_lines(tenders: list[DigestTender]) -> list[str]:
    lines: list[str] = []
    for tender in tenders:
        lines.append(f"• *{tender.title}*")
        if tender.company:
            lines.append(f"  Organisation: {tender.company}")
        if tender.closing_date:
            lines.append(f"  Closing: {tender.closing_date}")
        if tender.link:
            lines.append(f"  Link: {tender.link}")
        lines.append("")
    return lines


def format_digest_body(categorized: dict[str, list[DigestTender]]) -> str:
    confirmed = categorized.get("confirmed", [])
    likely = categorized.get("likely", [])
    rejected = categorized.get("rejected", [])
    total = len(confirmed) + len(likely) + len(rejected)

    if total == 0:
        return "No new tenders were found today."

    lines = [f"*{total} new tender(s) found today.*", ""]

    if confirmed:
        lines.append(f"✅ *Confirmed manpower/staffing match ({len(confirmed)})*")
        lines.extend(_format_tender_lines(confirmed))

    if likely:
        lines.append(f"🟡 *Possibly relevant - worth a look ({len(likely)})*")
        lines.extend(_format_tender_lines(likely))

    if rejected:
        lines.append(f"⚪ *Screened out as not relevant ({len(rejected)})*")
        lines.extend(f"• {tender.title}" for tender in rejected)
        lines.append("")

    return "\n".join(lines).rstrip()


def send_slack_digest(subject: str, body: str) -> None:
    """Post the digest to the Slack Workflow Builder webhook trigger.

    Unlike a classic Slack Incoming Webhook (which accepts a free-form
    `{"text": ...}` payload), a Workflow Builder trigger only accepts the
    exact input variable(s) defined on that trigger - here, a single
    `message` variable. Raises on a non-2xx response so a broken webhook
    fails the run instead of silently dropping the digest.
    """

    webhook_url = os.environ["SLACK_WEBHOOK_URL"]
    message = f"{subject}\n\n{body}"

    response = requests.post(webhook_url, json={"message": message}, timeout=30)
    response.raise_for_status()

    log("Digest posted to Slack.")


def main() -> None:
    load_local_env()

    headless = os.getenv("TENDERBOARD_HEADLESS", "1") != "0"
    tenders = scrape_tenders(headless=headless)
    log(f"Scraper found {len(tenders)} new tender(s) since the last run.")

    categorized = classify_tenders(tenders)
    log(
        f"{len(categorized['confirmed'])} confirmed, {len(categorized['likely'])} likely, "
        f"{len(categorized['rejected'])} rejected after Gemini classification."
    )

    total = sum(len(bucket) for bucket in categorized.values())
    subject = f"TenderFlow Daily Digest - {total} new tender(s)"
    body = format_digest_body(categorized)
    send_slack_digest(subject, body)


if __name__ == "__main__":
    main()
