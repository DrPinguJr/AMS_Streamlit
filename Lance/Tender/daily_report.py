"""Daily TenderBoard scrape -> Gemini relevance filter -> Slack digest.

Runs the existing TenderBoard scraper (`TenderScrape.scrape_tenderboard`),
keeps only the tenders that are new since the last run, asks Gemini to
shortlist the ones relevant to a manpower/staffing agency, and posts the
shortlist to a Slack Workflow Builder webhook. Designed to be triggered
daily by `.github/workflows/tenderboard-daily.yml`, but `main()` also runs
fine locally (reads a local `.env`, same as the Streamlit page).

Every step degrades gracefully rather than raising past the top: a Gemini
failure keeps everyone (fail open, not silent), a missing Gemini key just
gets logged. A flaky dependency should never crash the whole run before we
know whether anything was found. Note: `send_slack_digest` still raises on
failure, so a broken webhook surfaces as a failed run (which is the point
of the daily job).

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
    "You are screening tender titles for a manpower/staffing agency (temp "
    "staffing, recruitment, outsourced labour, and facilities/security/"
    "cleaning/healthcare manpower and HR services contracts). Given a JSON "
    "array of tender titles, return ONLY a JSON array containing the exact "
    "titles (unchanged) that are relevant to that business. Drop anything "
    "unrelated (e.g. construction works, IT hardware, pure goods supply). "
    "If none are relevant, return an empty array."
)


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


def analyze_tenders(tenders: list[DigestTender]) -> list[DigestTender]:
    """Ask Gemini which of `tenders` are relevant to a manpower/staffing agency.

    Any failure (missing key, missing dependency, malformed response,
    network error) falls back to keeping every tender rather than dropping
    the run silently - a noisier email beats a lost tender.
    """

    if not tenders:
        return []

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log("GEMINI_API_KEY is not set; skipping relevance filtering.")
        return tenders

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        log("google-genai is not installed; skipping relevance filtering.")
        return tenders

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
        relevant_titles = {str(title).strip() for title in json.loads(response.text)}
    except Exception as exc:  # noqa: BLE001 - any provider/network failure degrades gracefully
        log(f"Gemini relevance filtering failed ({exc}); keeping all tenders.")
        return tenders

    return [tender for tender in tenders if tender.title in relevant_titles]


def format_digest_body(tenders: list[DigestTender]) -> str:
    if not tenders:
        return "No new manpower/staffing-relevant tenders were found today."

    lines = [f"*{len(tenders)} new tender(s) relevant to manpower/staffing:*", ""]
    for tender in tenders:
        lines.append(f"• *{tender.title}*")
        if tender.company:
            lines.append(f"  Organisation: {tender.company}")
        if tender.closing_date:
            lines.append(f"  Closing: {tender.closing_date}")
        if tender.link:
            lines.append(f"  Link: {tender.link}")
        lines.append("")
    return "\n".join(lines)


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

    relevant = analyze_tenders(tenders)
    log(f"{len(relevant)} tender(s) kept as relevant after Gemini filtering.")

    subject = f"TenderFlow Daily Digest - {len(relevant)} relevant tender(s)"
    body = format_digest_body(relevant)
    send_slack_digest(subject, body)


if __name__ == "__main__":
    main()
