"""Daily TenderBoard scrape -> Gemini relevance classifier -> email digest.

Runs the existing TenderBoard scraper (`TenderScrape.scrape_tenderboard`),
keeps only the tenders that are new since the last run, asks Gemini to sort
them into confirmed / likely / rejected manpower-staffing relevance, and
emails the full breakdown (all three buckets, nothing dropped) via Gmail
SMTP. Designed to be triggered daily by
`.github/workflows/tenderboard-daily.yml`, but `main()` also runs fine
locally (reads a local `.env`, same as the Streamlit page).

GitHub's `schedule` trigger is not guaranteed to fire on time - it has been
observed firing hours late on this repo. To compensate, the workflow ticks
every 10 minutes across a 2-hour window instead of once at the target time,
and `main()` self-guards with a same-day marker file (see
`_already_sent_today`/`_mark_sent_today` below) so only the first tick that
successfully sends actually does anything; every later tick that day is a
fast no-op. `force_full_report` runs bypass the marker entirely (both
checking and writing it) since those are on-demand previews, not the one
daily send.

Every step degrades gracefully rather than raising past the top: a Gemini
failure buckets everything as "likely" (fail open, not silent), a missing
Gemini key does the same. A flaky dependency should never crash the whole
run before we know whether anything was found. Note: `send_email` still
raises on failure, so a bad credential or address surfaces as a failed run
(which is the point of the daily job).

Required environment variables (set as GitHub Actions secrets, never
committed - see the workflow file for the exact secret names):
    TENDERBOARD_USERNAME   - TenderBoard login used by the scraper
    TENDERBOARD_PASSWORD   - TenderBoard login used by the scraper
    GEMINI_API_KEY          - Google GenAI API key
    GMAIL_USER              - Sender Gmail address
    GMAIL_PASS              - Gmail App Password (NOT the account password -
                               see https://support.google.com/accounts/answer/185833)
    RECIPIENT_EMAILS_TEST   - Comma-separated recipient address(es)
"""

from __future__ import annotations

import json
import os
import smtplib
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pandas as pd

try:
    from TenderProcess import DATABASE_PATH
    from TenderScrape import load_local_env, log, scrape_tenderboard
except ModuleNotFoundError:
    from Lance.Tender.TenderProcess import DATABASE_PATH
    from Lance.Tender.TenderScrape import load_local_env, log, scrape_tenderboard

# Singapore has no DST, so a fixed UTC+8 offset is all "today" needs - no
# dependency on the runner having full tzdata installed.
_SGT = timezone(timedelta(hours=8))

# Lives next to Database.xlsx, so it rides along with the same GitHub Actions
# cache (see the workflow's cache/restore and cache/save steps) without any
# extra setup. Holds nothing but an ISO date - the last day the daily digest
# was actually sent.
_SENT_MARKER_PATH = DATABASE_PATH.parent / ".last_sent_date"

# Update this if the pinned google-genai release retires the model.
# gemini-2.5-flash was retired for new users (404 from the API pointing at
# gemini-3.6-flash) - every run since then silently fell back to bucketing
# every tender as "likely" instead of actually classifying them.
GEMINI_MODEL_NAME = "gemini-3.6-flash"

# Gemini intermittently returns a transient 503 ("high demand... try again
# later") - confirmed by re-running the exact same request a few seconds
# apart and getting a mix of success and 503. A handful of short retries is
# usually enough to ride that out.
_GEMINI_MAX_ATTEMPTS = 3
_GEMINI_RETRY_DELAY_SECONDS = 15

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
    published_date: str
    closing_date: str
    company: str


def scrape_tenders(headless: bool = True, force_full: bool = False) -> list[DigestTender]:
    """Run the TenderBoard scraper and return the tenders to report.

    By default, reuses `scrape_tenderboard`'s own dedupe against the saved
    database, so on a normal day (nothing new) this returns an empty list
    rather than re-reporting everything already seen. When `force_full` is
    set, the scrape still runs and still updates the dedupe database as
    normal (so the daily schedule's "new since last run" behaviour is
    unaffected), but this returns every tender currently on the board
    instead of just the ones new since the last run - useful for previewing
    or verifying the digest on demand.
    """

    _, save_summary = scrape_tenderboard(headless=headless, log_fn=log)
    source_path = save_summary.database_path if force_full else save_summary.new_output_path
    if source_path is None or not source_path.exists():
        return []

    dataframe = pd.read_excel(source_path)
    tenders: list[DigestTender] = []
    for row in dataframe.to_dict("records"):
        tenders.append(
            DigestTender(
                title=str(row.get("tender_title", "") or "").strip(),
                link=str(row.get("tender_link", "") or "").strip(),
                published_date=str(row.get("published_date", "") or "").strip(),
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
    client = genai.Client(api_key=api_key)

    # Gemini returns a transient 503 ("high demand... try again later") often
    # enough that hitting it once used to blank out the whole day's
    # classification - the marker file (see _mark_sent_today) means there is
    # only one real attempt per day now, so a short retry here is what
    # actually stands between a blip and a fully unfiltered digest.
    classifications = None
    last_exc: Exception | None = None
    for attempt in range(1, _GEMINI_MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL_NAME,
                contents=f"Tender titles: {json.dumps(titles)}",
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                ),
            )
            classifications = json.loads(response.text)
            break
        except Exception as exc:  # noqa: BLE001 - any provider/network failure degrades gracefully
            last_exc = exc
            log(f"Gemini relevance classification attempt {attempt} failed ({exc}).")
            if attempt < _GEMINI_MAX_ATTEMPTS:
                time.sleep(_GEMINI_RETRY_DELAY_SECONDS)

    if classifications is None:
        log(
            f"Gemini relevance classification failed after {_GEMINI_MAX_ATTEMPTS} attempts "
            f"({last_exc}); keeping all tenders as likely."
        )
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


def _format_tender_block(
    tenders: list[DigestTender], *, include_organisation: bool = True
) -> list[str]:
    """One multi-line block per tender: title, [organisation,] published/closing dates, link.

    Unlike the old Slack-oriented formatting, email has no practical message
    size limit, so every tender in the bucket is listed in full rather than
    capped at a handful of entries.

    `published_date` is TenderBoard's own posting date for the listing (day/
    month/year, as scraped) - TenderBoard doesn't expose a time of day, so
    there's no posting time to show, only the date.

    `include_organisation` is off for the screened-out bucket, which can run
    much longer than confirmed/likely - title, dates and link are enough to
    catch a false positive without stretching every entry an extra line.
    """

    lines: list[str] = []
    for tender in tenders:
        lines.append(f"- {tender.title or '(untitled)'}")
        if include_organisation and tender.company:
            lines.append(f"  Organisation: {tender.company}")
        if tender.published_date:
            lines.append(f"  Published: {tender.published_date}")
        if tender.closing_date:
            lines.append(f"  Closing: {tender.closing_date}")
        if tender.link:
            lines.append(f"  Link: {tender.link}")
        lines.append("")
    return lines


def format_digest_body(
    categorized: dict[str, list[DigestTender]], *, full_snapshot: bool = False
) -> str:
    confirmed = categorized.get("confirmed", [])
    likely = categorized.get("likely", [])
    rejected = categorized.get("rejected", [])
    total = len(confirmed) + len(likely) + len(rejected)

    if total == 0:
        return (
            "No tenders are currently on the board."
            if full_snapshot
            else "No new tenders were found today."
        )

    headline = (
        f"{total} tender(s) currently on the board."
        if full_snapshot
        else f"{total} new tender(s) found today."
    )
    lines = [headline, ""]

    if confirmed:
        lines.append(f"CONFIRMED ({len(confirmed)})")
        lines.append("-" * 40)
        lines.extend(_format_tender_block(confirmed))

    if likely:
        lines.append(f"POSSIBLY RELEVANT ({len(likely)})")
        lines.append("-" * 40)
        lines.extend(_format_tender_block(likely))

    if rejected:
        # Listed in full (not just a count) so a false positive - a good
        # tender Gemini wrongly screened out - is still catchable on a
        # glance, instead of being silently lost. Unlike the old Slack
        # digest, email has no practical size limit, and this bucket sits
        # last so the buckets worth acting on first aren't buried under it.
        lines.append(f"SCREENED OUT AS NOT RELEVANT ({len(rejected)})")
        lines.append("-" * 40)
        lines.extend(_format_tender_block(rejected, include_organisation=False))

    return "\n".join(lines).rstrip()


def send_email(subject: str, body: str) -> None:
    """Send `body` from GMAIL_USER to every address in RECIPIENT_EMAILS_TEST.

    Uses an App Password (not the Gmail account password) over STARTTLS, per
    Google's recommendation for SMTP from scripts/CI:
    https://support.google.com/accounts/answer/185833

    RECIPIENT_EMAILS_TEST is a comma-separated list so the digest can go to
    more than one address; raises on a bad/empty list or a failed send so a
    misconfigured credential surfaces as a failed run rather than a silently
    dropped digest.
    """

    sender = os.environ["GMAIL_USER"]
    app_password = os.environ["GMAIL_PASS"]
    recipients = [
        address.strip()
        for address in os.environ["RECIPIENT_EMAILS_TEST"].split(",")
        if address.strip()
    ]
    if not recipients:
        raise ValueError("RECIPIENT_EMAILS_TEST is set but contains no valid email address(es).")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(sender, app_password)
        smtp.send_message(message)

    log(f"Email sent to {', '.join(recipients)}.")


def _today_sgt() -> str:
    return datetime.now(_SGT).date().isoformat()


def _already_sent_today() -> bool:
    """True if `_mark_sent_today` already ran today (SGT), per the marker file."""

    if not _SENT_MARKER_PATH.exists():
        return False
    return _SENT_MARKER_PATH.read_text(encoding="utf-8").strip() == _today_sgt()


def _mark_sent_today() -> None:
    _SENT_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SENT_MARKER_PATH.write_text(_today_sgt(), encoding="utf-8")


def main() -> None:
    load_local_env()

    headless = os.getenv("TENDERBOARD_HEADLESS", "1") != "0"
    force_full = os.getenv("FORCE_FULL_REPORT", "0").strip().lower() in ("1", "true")

    # Only the real daily send is guarded - force_full previews are on-demand
    # and should never be silently skipped just because today's digest
    # already went out.
    if not force_full and _already_sent_today():
        log(f"Daily digest already sent today ({_today_sgt()} SGT); skipping this tick.")
        return

    tenders = scrape_tenders(headless=headless, force_full=force_full)
    if force_full:
        log(f"Scraper found {len(tenders)} tender(s) currently on the board (full snapshot).")
    else:
        log(f"Scraper found {len(tenders)} new tender(s) since the last run.")

    categorized = classify_tenders(tenders)
    log(
        f"{len(categorized['confirmed'])} confirmed, {len(categorized['likely'])} likely, "
        f"{len(categorized['rejected'])} rejected after Gemini classification."
    )

    total = sum(len(bucket) for bucket in categorized.values())
    label = "tender(s) on the board" if force_full else "new tender(s)"
    subject_prefix = "TenderFlow Full Snapshot" if force_full else "TenderFlow Daily Digest"
    subject = f"{subject_prefix} - {total} {label}"
    body = format_digest_body(categorized, full_snapshot=force_full)
    send_email(subject, body)
    if not force_full:
        _mark_sent_today()


if __name__ == "__main__":
    main()
