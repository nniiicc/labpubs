"""Tests for Slack Block Kit notification formatting."""

import pytest

from labpubs.models import Author, Work, WorkType
from labpubs.notify.slack import (
    _MAX_WORKS_IN_BLOCKS,
    _build_blocks,
    _format_authors,
    _format_fallback_text,
    _format_work_section,
    send_slack_notification,
)

# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def work_full() -> Work:
    """Work with all fields populated."""
    return Work(
        doi="10.1038/s42256-025-00123-4",
        title="Transformer Models for Policy Analysis",
        authors=[
            Author(name="J Smith"),
            Author(name="A Johnson"),
            Author(name="B Lee"),
        ],
        year=2025,
        venue="Nature Machine Intelligence",
        work_type=WorkType.JOURNAL_ARTICLE,
        open_access_url="https://example.com/paper.pdf",
    )


@pytest.fixture
def work_minimal() -> Work:
    """Work with only required fields."""
    return Work(title="A Minimal Paper", work_type=WorkType.OTHER)


@pytest.fixture
def work_many_authors() -> Work:
    """Work with more than 3 authors."""
    return Work(
        title="Big Collaboration Paper",
        authors=[
            Author(name="A Smith"),
            Author(name="B Jones"),
            Author(name="C Lee"),
            Author(name="D Park"),
            Author(name="E Kim"),
        ],
        year=2025,
        venue="Science",
        work_type=WorkType.JOURNAL_ARTICLE,
    )


# ── _format_authors ──────────────────────────────────────────


class TestFormatAuthors:
    def test_three_or_fewer(self, work_full: Work) -> None:
        result = _format_authors(work_full)
        assert result == "J Smith, A Johnson, B Lee"

    def test_more_than_three(self, work_many_authors: Work) -> None:
        result = _format_authors(work_many_authors)
        assert result == "A Smith, B Jones, C Lee + 2 more"

    def test_single_author(self) -> None:
        work = Work(
            title="Solo",
            authors=[Author(name="A Smith")],
            work_type=WorkType.OTHER,
        )
        assert _format_authors(work) == "A Smith"


# ── _format_work_section ─────────────────────────────────────


class TestFormatWorkSection:
    def test_full_work_has_section_type(self, work_full: Work) -> None:
        block = _format_work_section(work_full)
        assert block["type"] == "section"
        assert block["text"]["type"] == "mrkdwn"

    def test_title_linked_to_doi(self, work_full: Work) -> None:
        block = _format_work_section(work_full)
        text = block["text"]["text"]
        assert "<https://doi.org/10.1038/s42256-025-00123-4|*Transformer Models" in text

    def test_title_not_linked_without_doi(self, work_minimal: Work) -> None:
        block = _format_work_section(work_minimal)
        text = block["text"]["text"]
        assert "*A Minimal Paper*" in text
        assert "<" not in text  # no link wrapper

    def test_venue_and_year(self, work_full: Work) -> None:
        block = _format_work_section(work_full)
        text = block["text"]["text"]
        assert "Nature Machine Intelligence \u00b7 2025" in text

    def test_doi_link_present(self, work_full: Work) -> None:
        block = _format_work_section(work_full)
        text = block["text"]["text"]
        assert "<https://doi.org/10.1038/s42256-025-00123-4|DOI>" in text

    def test_pdf_link_present(self, work_full: Work) -> None:
        block = _format_work_section(work_full)
        text = block["text"]["text"]
        assert "<https://example.com/paper.pdf|PDF>" in text

    def test_minimal_work_no_crash(self, work_minimal: Work) -> None:
        block = _format_work_section(work_minimal)
        assert "*A Minimal Paper*" in block["text"]["text"]

    def test_no_venue_no_year(self, work_minimal: Work) -> None:
        block = _format_work_section(work_minimal)
        text = block["text"]["text"]
        # Should only have the title, nothing else
        assert text == "*A Minimal Paper*"


# ── _build_blocks ────────────────────────────────────────────


class TestBuildBlocks:
    def test_header_block(self, work_full: Work) -> None:
        blocks = _build_blocks([work_full])
        assert blocks[0]["type"] == "header"
        assert "1 New Publication" in blocks[0]["text"]["text"]

    def test_plural_header(self, work_full: Work, work_minimal: Work) -> None:
        blocks = _build_blocks([work_full, work_minimal])
        assert "2 New Publications" in blocks[0]["text"]["text"]

    def test_single_work_no_divider(self, work_full: Work) -> None:
        blocks = _build_blocks([work_full])
        types = [b["type"] for b in blocks]
        assert "divider" not in types

    def test_two_works_have_divider(self, work_full: Work, work_minimal: Work) -> None:
        blocks = _build_blocks([work_full, work_minimal])
        types = [b["type"] for b in blocks]
        assert types == ["header", "section", "divider", "section"]

    def test_overflow_message(self) -> None:
        works = [
            Work(title=f"Paper {i}", work_type=WorkType.OTHER)
            for i in range(_MAX_WORKS_IN_BLOCKS + 3)
        ]
        blocks = _build_blocks(works)
        # Last block should be the overflow context
        assert blocks[-1]["type"] == "context"
        assert "3 more" in blocks[-1]["elements"][0]["text"]

    def test_no_overflow_at_limit(self) -> None:
        works = [
            Work(title=f"Paper {i}", work_type=WorkType.OTHER)
            for i in range(_MAX_WORKS_IN_BLOCKS)
        ]
        blocks = _build_blocks(works)
        types = [b["type"] for b in blocks]
        assert "context" not in types


# ── _format_fallback_text ────────────────────────────────────


class TestFormatFallbackText:
    def test_includes_count(self, work_full: Work) -> None:
        text = _format_fallback_text([work_full])
        assert "New publications found (1):" in text

    def test_includes_title_and_venue(self, work_full: Work) -> None:
        text = _format_fallback_text([work_full])
        assert "Transformer Models for Policy Analysis" in text
        assert "Nature Machine Intelligence" in text

    def test_venue_unknown_fallback(self, work_minimal: Work) -> None:
        text = _format_fallback_text([work_minimal])
        assert "venue unknown" in text


# ── send_slack_notification ──────────────────────────────────


class TestSendSlackNotification:
    async def test_empty_works_returns_true(self) -> None:
        result = await send_slack_notification("https://hooks.slack.com/test", [])
        assert result is True

    async def test_failed_request_returns_false(self, work_full: Work) -> None:
        # Unreachable URL should fail
        result = await send_slack_notification(
            "https://127.0.0.1:1/nonexistent", [work_full]
        )
        assert result is False
