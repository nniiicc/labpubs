"""Google Scholar alert email ingestion.

Connects to an IMAP mailbox, parses Google Scholar alert emails,
and converts each alert item into a labpubs Work object.
"""

from __future__ import annotations

import email
import imaplib
import logging
import os
import re
from dataclasses import dataclass
from email.header import decode_header
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from labpubs.config import ScholarAlertConfig, ScholarResearcherMap
from labpubs.models import Author, Source, Work, WorkType
from labpubs.normalize import split_author_name

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────


@dataclass
class AlertEmail:
    """A fetched Scholar alert email."""

    message_id: str
    gmail_uid: str | None
    subject: str
    internal_date: str
    from_addr: str
    to_addr: str
    html_body: str


@dataclass
class AlertItem:
    """A single publication parsed from a Scholar alert email."""

    title: str
    authors_raw: str
    venue: str | None
    year: int | None
    target_url: str | None
    scholar_url: str | None
    position: int


# ── IMAP fetching ─────────────────────────────────────────────


def _decode_header_value(raw: str | None) -> str:
    """Decode a MIME-encoded email header value."""
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded: list[str] = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _extract_html_body(msg: email.message.Message) -> str:
    """Extract the HTML body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        ct = msg.get_content_type()
        if ct == "text/html":
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    return ""


def fetch_alert_emails_sync(config: ScholarAlertConfig) -> list[AlertEmail]:
    """Fetch Scholar alert emails from IMAP (synchronous).

    Connect, search, fetch, and return parsed email metadata.
    Designed to be wrapped in ``run_in_executor()`` from async code.

    Args:
        config: Scholar alert configuration.

    Returns:
        List of AlertEmail objects.

    Raises:
        RuntimeError: If credentials are missing from environment.
    """
    username = os.environ.get(config.auth.username_env)
    password = os.environ.get(config.auth.app_password_env)
    if not username or not password:
        raise RuntimeError(
            f"Set {config.auth.username_env} and "
            f"{config.auth.app_password_env} environment variables"
        )

    conn: imaplib.IMAP4_SSL | None = None
    try:
        logger.info("Connecting to %s ...", config.imap_server)
        conn = imaplib.IMAP4_SSL(config.imap_server, 993, timeout=30)
        conn.login(username, password)
        conn.select(config.mailbox, readonly=True)

        # Build IMAP search criteria
        criteria: list[str] = []
        criteria.append(f'FROM "{config.search.from_addr}"')
        if config.search.subject_contains:
            criteria.append(f'SUBJECT "{config.search.subject_contains}"')
        if config.search.unseen_only:
            criteria.append("UNSEEN")

        search_str = " ".join(criteria)
        logger.debug("IMAP SEARCH %s", search_str)
        _status, data = conn.search(None, f"({search_str})")

        msg_nums = data[0].split() if data[0] else []
        logger.info("Found %d matching emails", len(msg_nums))

        results: list[AlertEmail] = []
        for num in msg_nums:
            _status, msg_data = conn.fetch(num, "(RFC822 UID)")
            if not msg_data or not msg_data[0]:
                continue

            # Extract UID from fetch response
            uid: str | None = None
            if isinstance(msg_data[0], tuple) and len(msg_data) > 1:
                tail = msg_data[1] if isinstance(msg_data[1], bytes) else b""
                uid_match = re.search(rb"UID (\d+)", tail)
                if uid_match:
                    uid = uid_match.group(1).decode()

            raw_email = (
                msg_data[0][1] if isinstance(msg_data[0], tuple) else msg_data[0]
            )
            if not isinstance(raw_email, bytes):
                continue

            msg = email.message_from_bytes(raw_email)

            message_id = msg.get("Message-ID", f"<unknown-{num.decode()}>")
            subject = _decode_header_value(msg.get("Subject"))
            from_addr = _decode_header_value(msg.get("From"))
            to_addr = _decode_header_value(msg.get("To"))
            date_str = msg.get("Date", "")
            html_body = _extract_html_body(msg)

            if html_body:
                results.append(
                    AlertEmail(
                        message_id=message_id,
                        gmail_uid=uid,
                        subject=subject,
                        internal_date=date_str,
                        from_addr=from_addr,
                        to_addr=to_addr,
                        html_body=html_body,
                    )
                )

        return results

    except imaplib.IMAP4.error as exc:
        logger.error("IMAP error: %s", exc)
        raise
    except TimeoutError as exc:
        logger.error("IMAP connection timed out: %s", exc)
        raise
    finally:
        if conn is not None:
            try:
                conn.logout()
            except Exception:
                pass


# ── HTML parsing ──────────────────────────────────────────────

_YEAR_RE = re.compile(r"(?:,|\s)\s*(\d{4})\s*$")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    """Replace NBSP and collapse whitespace."""
    text = text.replace("\xa0", " ")
    return _WHITESPACE_RE.sub(" ", text).strip()


def parse_alert_html(html: str) -> list[AlertItem]:
    """Parse a Google Scholar alert email's HTML into AlertItems.

    Args:
        html: Raw HTML body of the alert email.

    Returns:
        List of AlertItem objects, one per publication in the email.
    """
    soup = BeautifulSoup(html, "html.parser")
    items: list[AlertItem] = []

    title_links = soup.find_all("a", class_="gse_alrt_title")

    for position, link in enumerate(title_links):
        title = _normalize_text(link.get_text())
        href = link.get("href", "")
        target_url = _resolve_scholar_url(href) if href else None
        scholar_url = href if href else None

        # The author/venue line is the next sibling <div>
        authors_raw = ""
        venue: str | None = None
        year: int | None = None

        next_div = link.find_next("div")
        if next_div:
            raw_text = _normalize_text(next_div.get_text())
            parts = re.split(r"\s*-\s*", raw_text, maxsplit=1)

            if parts:
                authors_raw = parts[0].strip()

            if len(parts) > 1:
                venue_year = parts[1].strip()
                year_match = _YEAR_RE.search(venue_year)
                if year_match:
                    year = int(year_match.group(1))
                    venue = venue_year[: year_match.start()].strip().rstrip(",").strip()
                else:
                    venue = venue_year

                if not venue:
                    venue = None

        if not title:
            logger.warning(
                "Skipping alert item with empty title at position %d",
                position,
            )
            continue

        item = AlertItem(
            title=title,
            authors_raw=authors_raw,
            venue=venue,
            year=year,
            target_url=target_url,
            scholar_url=scholar_url,
            position=position,
        )
        logger.debug("Parsed alert item: %s (%s)", item.title, item.year)
        items.append(item)

    return items


def _resolve_scholar_url(href: str) -> str:
    """Extract the actual article URL from a Scholar redirect link.

    Scholar alert links look like:
    ``https://scholar.google.com/scholar_url?url=<actual>&...``

    Args:
        href: Raw href from the alert email.

    Returns:
        Resolved URL or the original href if not a redirect.
    """
    parsed = urlparse(href)
    if "scholar.google" in parsed.netloc and parsed.path.startswith("/scholar_url"):
        qs = parse_qs(parsed.query)
        targets = qs.get("url", [])
        if targets:
            return targets[0]
    return href


# ── Work conversion ───────────────────────────────────────────


def alert_item_to_work(item: AlertItem) -> Work:
    """Convert a parsed AlertItem into a Work model.

    Args:
        item: Parsed alert item.

    Returns:
        Work object with minimal metadata from the alert.
    """
    authors: list[Author] = []
    if item.authors_raw:
        for raw_name in item.authors_raw.split(","):
            name = raw_name.strip()
            if name and name != "...":
                given, family = split_author_name(name)
                full = f"{given} {family}" if given and family else (family or name)
                authors.append(Author(name=full))

    return Work(
        title=item.title,
        authors=authors,
        venue=item.venue,
        year=item.year,
        work_type=WorkType.OTHER,
        open_access_url=item.target_url,
        sources=[Source.GOOGLE_SCHOLAR_ALERT],
    )


# ── Researcher association ────────────────────────────────────

_USER_RE = re.compile(r"[?&]user=([A-Za-z0-9_-]+)")


def match_email_to_researcher(
    email_subject: str,
    email_html: str,
    researcher_map: list[ScholarResearcherMap],
) -> str | None:
    """Determine which researcher an alert email belongs to.

    Uses a three-tier strategy:
    1. Subject prefix match from researcher_map
    2. Scholar profile ``user=`` ID match
    3. (Future) Name extraction from email footer

    Args:
        email_subject: Email subject line.
        email_html: Raw HTML body.
        researcher_map: Configured researcher mappings.

    Returns:
        Researcher name (matching ResearcherConfig.name) or None.
    """
    # Tier 1: subject prefix
    for mapping in researcher_map:
        prefix = mapping.alert_subject_prefix
        if prefix and prefix in email_subject:
            logger.debug(
                "Matched researcher '%s' via subject prefix",
                mapping.researcher_name,
            )
            return mapping.researcher_name

    # Tier 2: profile user ID in HTML
    user_ids = _USER_RE.findall(email_html)
    if user_ids:
        for mapping in researcher_map:
            uid = mapping.scholar_profile_user
            if uid and uid in user_ids:
                logger.debug(
                    "Matched researcher '%s' via profile user ID",
                    mapping.researcher_name,
                )
                return mapping.researcher_name

    logger.debug("No researcher match found for subject: %s", email_subject)
    return None
