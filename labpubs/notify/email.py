"""Email notification backend using SMTP."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from labpubs.models import Work

logger = logging.getLogger(__name__)


def _format_html_digest(works: list[Work]) -> str:
    """Format new works into an HTML email body.

    Args:
        works: List of new Work objects.

    Returns:
        HTML-formatted email body.
    """
    items: list[str] = []
    for work in works:
        author_names = ", ".join(a.name for a in work.authors[:5])
        if len(work.authors) > 5:
            author_names += " et al."

        venue = work.venue or "venue unknown"
        doi_link = ""
        if work.doi:
            doi_link = f' | <a href="https://doi.org/{work.doi}">DOI</a>'

        items.append(
            f"<li><strong>{work.title}</strong> ({work.year})"
            f"<br>{author_names}"
            f"<br><em>{venue}</em>{doi_link}</li>"
        )

    body = f"<h2>New publications ({len(works)})</h2><ul>{''.join(items)}</ul>"
    return body


def _format_text_digest(works: list[Work]) -> str:
    """Format new works into a plain-text email body.

    Args:
        works: List of new Work objects.

    Returns:
        Plain-text email body.
    """
    lines = [f"New publications ({len(works)})", ""]
    for work in works:
        author_names = ", ".join(a.name for a in work.authors[:5])
        if len(work.authors) > 5:
            author_names += " et al."
        venue = work.venue or "venue unknown"
        lines.append(f"- {work.title} ({work.year})")
        lines.append(f"  {author_names}")
        lines.append(f"  {venue}")
        if work.doi:
            lines.append(f"  https://doi.org/{work.doi}")
        lines.append("")
    return "\n".join(lines)


def send_email_notification(
    smtp_host: str,
    smtp_port: int,
    from_address: str,
    to_addresses: list[str],
    works: list[Work],
) -> bool:
    """Send an email digest of new publications.

    Args:
        smtp_host: SMTP server hostname.
        smtp_port: SMTP server port.
        from_address: Sender email address.
        to_addresses: List of recipient email addresses.
        works: List of new Work objects.

    Returns:
        True if the email was sent successfully.
    """
    if not works:
        return True

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"labpubs: {len(works)} new publication(s)"
    msg["From"] = from_address
    msg["To"] = ", ".join(to_addresses)

    text_body = _format_text_digest(works)
    html_body = _format_html_digest(works)

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.send_message(msg)
        return True
    except smtplib.SMTPException:
        logger.exception("Failed to send email notification")
        return False
