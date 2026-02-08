"""Slack webhook notification backend."""

import logging

import httpx

from labpubs.models import Work

logger = logging.getLogger(__name__)


def _format_slack_message(works: list[Work]) -> str:
    """Format new works into a Slack message body.

    Args:
        works: List of new Work objects.

    Returns:
        Formatted message string.
    """
    lines = [f"New publications found ({len(works)}):"]
    for work in works:
        author_names = ", ".join(
            a.name for a in work.authors[:3]
        )
        if len(work.authors) > 3:
            author_names += " et al."

        venue = work.venue or "venue unknown"
        line = f"- *{work.title}* ({work.year}) -- {venue}"
        if author_names:
            line += f"\n  {author_names}"
        if work.doi:
            line += f"\n  DOI: {work.doi}"
        if work.open_access_url:
            line += f"\n  OA: {work.open_access_url}"
        lines.append(line)

    return "\n\n".join(lines)


async def send_slack_notification(
    webhook_url: str,
    works: list[Work],
    channel: str | None = None,
) -> bool:
    """Send a Slack notification about new publications.

    Args:
        webhook_url: Slack incoming webhook URL.
        works: List of new Work objects.
        channel: Optional channel override.

    Returns:
        True if the notification was sent successfully.
    """
    if not works:
        return True

    message = _format_slack_message(works)
    payload: dict[str, str] = {"text": message}
    if channel:
        payload["channel"] = channel

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                webhook_url, json=payload, timeout=10.0
            )
            response.raise_for_status()
            return True
    except httpx.HTTPError:
        logger.exception("Failed to send Slack notification")
        return False
