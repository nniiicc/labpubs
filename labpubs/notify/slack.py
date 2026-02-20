"""Slack webhook notification backend."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from labpubs.models import Work

logger = logging.getLogger(__name__)

# Slack limits messages to 50 blocks.  Header + dividers + per-work sections
# means we can safely show ~15 works before hitting the cap.
_MAX_WORKS_IN_BLOCKS = 15


def _format_authors(work: Work) -> str:
    """Format an author list, truncating after 3 names."""
    names = [a.name for a in work.authors[:3]]
    suffix = f" + {len(work.authors) - 3} more" if len(work.authors) > 3 else ""
    return ", ".join(names) + suffix


def _format_work_section(work: Work) -> dict[str, Any]:
    """Build a Slack section block for a single publication."""
    # Title — link to DOI when available
    doi_url = f"https://doi.org/{work.doi}" if work.doi else None
    title = f"<{doi_url}|*{work.title}*>" if doi_url else f"*{work.title}*"

    # Metadata line: venue · year
    parts: list[str] = []
    if work.venue:
        parts.append(work.venue)
    if work.year:
        parts.append(str(work.year))
    meta = " \u00b7 ".join(parts) if parts else ""

    # Authors
    authors = _format_authors(work) if work.authors else ""

    # Assemble the mrkdwn text
    lines = [title]
    if authors:
        lines.append(authors)
    if meta:
        lines.append(meta)

    # Links line: DOI and OA URL as separate links
    links: list[str] = []
    if work.doi:
        links.append(f"<https://doi.org/{work.doi}|DOI>")
    if work.open_access_url:
        links.append(f"<{work.open_access_url}|PDF>")
    if links:
        lines.append(" | ".join(links))

    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(lines)},
    }


def _build_blocks(works: list[Work]) -> list[dict[str, Any]]:
    """Build Slack Block Kit blocks for a list of publications.

    Args:
        works: List of new Work objects.

    Returns:
        List of Slack block dicts.
    """
    shown = works[:_MAX_WORKS_IN_BLOCKS]
    overflow = len(works) - len(shown)

    suffix = "s" if len(works) != 1 else ""
    header_text = f"\U0001f4da {len(works)} New Publication{suffix}"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text},
        },
    ]

    for i, work in enumerate(shown):
        blocks.append(_format_work_section(work))
        # Divider between works, not after the last one
        if i < len(shown) - 1:
            blocks.append({"type": "divider"})

    if overflow:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"_+ {overflow} more "
                            f"publication{'s' if overflow != 1 else ''}"
                            " not shown_"
                        ),
                    }
                ],
            }
        )

    return blocks


def _format_fallback_text(works: list[Work]) -> str:
    """Plain-text fallback shown in notifications and clients without Block Kit."""
    lines = [f"New publications found ({len(works)}):"]
    for work in works:
        venue = work.venue or "venue unknown"
        lines.append(f"- {work.title} ({work.year}) -- {venue}")
    return "\n".join(lines)


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

    payload: dict[str, Any] = {
        "text": _format_fallback_text(works),
        "blocks": _build_blocks(works),
    }
    if channel:
        payload["channel"] = channel

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, timeout=10.0)
            response.raise_for_status()
            return True
    except httpx.HTTPError:
        logger.exception("Failed to send Slack notification")
        return False
