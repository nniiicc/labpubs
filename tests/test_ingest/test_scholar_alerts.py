"""Tests for Google Scholar alert email ingestion."""

from pathlib import Path

import pytest

from labpubs.config import LabPubsConfig, ScholarResearcherMap
from labpubs.ingest.scholar_alerts import (
    AlertItem,
    _normalize_text,
    _resolve_scholar_url,
    alert_item_to_work,
    match_email_to_researcher,
    parse_alert_html,
)
from labpubs.models import Source, Work, WorkType
from labpubs.store import Store

_FIXTURE_DIR = Path(__file__).parent


# ── HTML parsing ──────────────────────────────────────────────


class TestParseAlertHtml:
    """Tests for parse_alert_html() with golden HTML fixture."""

    @pytest.fixture
    def golden_html(self) -> str:
        return (_FIXTURE_DIR / "golden_alert.html").read_text()

    def test_parses_correct_number_of_items(self, golden_html: str) -> None:
        items = parse_alert_html(golden_html)
        assert len(items) == 3

    def test_first_item_title(self, golden_html: str) -> None:
        items = parse_alert_html(golden_html)
        assert items[0].title == "Transformer Models for Policy Analysis"

    def test_first_item_authors(self, golden_html: str) -> None:
        items = parse_alert_html(golden_html)
        assert items[0].authors_raw == "J Smith, A Johnson, B Lee"

    def test_first_item_venue_and_year(self, golden_html: str) -> None:
        items = parse_alert_html(golden_html)
        assert items[0].venue == "Nature Machine Intelligence"
        assert items[0].year == 2025

    def test_first_item_resolved_url(self, golden_html: str) -> None:
        items = parse_alert_html(golden_html)
        assert items[0].target_url == "https://example.com/paper1.pdf"

    def test_first_item_scholar_url(self, golden_html: str) -> None:
        items = parse_alert_html(golden_html)
        assert items[0].scholar_url is not None
        assert "scholar.google.com" in items[0].scholar_url

    def test_second_item_year(self, golden_html: str) -> None:
        items = parse_alert_html(golden_html)
        assert items[1].year == 2024
        assert items[1].venue == "Science"

    def test_nbsp_normalized_in_title(self, golden_html: str) -> None:
        items = parse_alert_html(golden_html)
        # NBSP should be replaced with regular spaces
        assert items[2].title == "No Break Spaces in Title"

    def test_ellipsis_author_present(self, golden_html: str) -> None:
        items = parse_alert_html(golden_html)
        # "..." is in the raw authors string
        assert "..." in items[2].authors_raw

    def test_positions_are_sequential(self, golden_html: str) -> None:
        items = parse_alert_html(golden_html)
        positions = [i.position for i in items]
        assert positions == [0, 1, 2]

    def test_direct_url_not_resolved(self, golden_html: str) -> None:
        items = parse_alert_html(golden_html)
        # The third item has a direct link, not a Scholar redirect
        assert items[2].target_url == "https://example.com/direct-link"

    def test_empty_html_returns_empty(self) -> None:
        items = parse_alert_html("<html><body></body></html>")
        assert items == []

    def test_no_title_links_returns_empty(self) -> None:
        html = '<html><body><a href="x">Not a title</a></body></html>'
        items = parse_alert_html(html)
        assert items == []


# ── URL resolution ────────────────────────────────────────────


class TestResolveScholarUrl:
    def test_scholar_redirect_resolved(self) -> None:
        href = "https://scholar.google.com/scholar_url?url=https://example.com/paper.pdf&hl=en"
        assert _resolve_scholar_url(href) == "https://example.com/paper.pdf"

    def test_non_scholar_url_returned_as_is(self) -> None:
        href = "https://example.com/direct-link"
        assert _resolve_scholar_url(href) == "https://example.com/direct-link"

    def test_scholar_url_without_url_param(self) -> None:
        href = "https://scholar.google.com/scholar_url?hl=en"
        assert _resolve_scholar_url(href) == href


# ── Text normalization ────────────────────────────────────────


class TestNormalizeText:
    def test_nbsp_replaced(self) -> None:
        assert _normalize_text("hello\xa0world") == "hello world"

    def test_whitespace_collapsed(self) -> None:
        assert _normalize_text("hello   \t  world") == "hello world"

    def test_strips_edges(self) -> None:
        assert _normalize_text("  hello  ") == "hello"


# ── Work conversion ──────────────────────────────────────────


class TestAlertItemToWork:
    def test_basic_conversion(self) -> None:
        item = AlertItem(
            title="Test Paper",
            authors_raw="A Smith, B Jones",
            venue="Nature",
            year=2025,
            target_url="https://example.com/paper.pdf",
            scholar_url="https://scholar.google.com/...",
            position=0,
        )
        work = alert_item_to_work(item)
        assert work.title == "Test Paper"
        assert work.year == 2025
        assert work.venue == "Nature"
        assert work.work_type == WorkType.OTHER
        assert work.open_access_url == "https://example.com/paper.pdf"
        assert Source.GOOGLE_SCHOLAR_ALERT in work.sources

    def test_authors_parsed(self) -> None:
        item = AlertItem(
            title="Test Paper",
            authors_raw="A Smith, B Jones",
            venue=None,
            year=None,
            target_url=None,
            scholar_url=None,
            position=0,
        )
        work = alert_item_to_work(item)
        assert len(work.authors) == 2
        # split_author_name splits "A Smith" → given="A", family="Smith"
        names = [a.name for a in work.authors]
        assert "A Smith" in names
        assert "B Jones" in names

    def test_ellipsis_filtered(self) -> None:
        item = AlertItem(
            title="Test",
            authors_raw="A Smith, ..., B Jones",
            venue=None,
            year=None,
            target_url=None,
            scholar_url=None,
            position=0,
        )
        work = alert_item_to_work(item)
        names = [a.name for a in work.authors]
        assert "..." not in names
        assert len(work.authors) == 2

    def test_empty_authors(self) -> None:
        item = AlertItem(
            title="Test",
            authors_raw="",
            venue=None,
            year=None,
            target_url=None,
            scholar_url=None,
            position=0,
        )
        work = alert_item_to_work(item)
        assert work.authors == []


# ── Researcher matching ──────────────────────────────────────


class TestMatchEmailToResearcher:
    def test_subject_prefix_match(self) -> None:
        researcher_map = [
            ScholarResearcherMap(
                researcher_name="Jane Doe",
                alert_subject_prefix="Jane Doe",
            ),
        ]
        result = match_email_to_researcher(
            email_subject="Scholar Alert - new articles for Jane Doe",
            email_html="<html></html>",
            researcher_map=researcher_map,
        )
        assert result == "Jane Doe"

    def test_profile_user_id_match(self) -> None:
        researcher_map = [
            ScholarResearcherMap(
                researcher_name="John Smith",
                scholar_profile_user="abc123XYZ",
            ),
        ]
        html = '<html><a href="https://scholar.google.com/citations?user=abc123XYZ">Profile</a></html>'
        result = match_email_to_researcher(
            email_subject="Scholar Alert",
            email_html=html,
            researcher_map=researcher_map,
        )
        assert result == "John Smith"

    def test_no_match_returns_none(self) -> None:
        researcher_map = [
            ScholarResearcherMap(
                researcher_name="Unknown",
                alert_subject_prefix="Unknown Person",
            ),
        ]
        result = match_email_to_researcher(
            email_subject="Scholar Alert - new articles",
            email_html="<html></html>",
            researcher_map=researcher_map,
        )
        assert result is None

    def test_empty_map_returns_none(self) -> None:
        result = match_email_to_researcher(
            email_subject="Scholar Alert",
            email_html="<html></html>",
            researcher_map=[],
        )
        assert result is None

    def test_subject_takes_priority_over_user_id(self) -> None:
        researcher_map = [
            ScholarResearcherMap(
                researcher_name="Jane Doe",
                alert_subject_prefix="Jane Doe",
            ),
            ScholarResearcherMap(
                researcher_name="John Smith",
                scholar_profile_user="abc123XYZ",
            ),
        ]
        html = '<html><a href="?user=abc123XYZ">Profile</a></html>'
        result = match_email_to_researcher(
            email_subject="new articles for Jane Doe",
            email_html=html,
            researcher_map=researcher_map,
        )
        # Subject prefix should match first
        assert result == "Jane Doe"


# ── Store integration ─────────────────────────────────────────


class TestStoreAlertTables:
    def test_insert_and_check_alert_email(self, tmp_db: Store) -> None:
        msg_id = "<test-123@example.com>"
        assert not tmp_db.is_alert_email_processed(msg_id)

        tmp_db.insert_alert_email(
            message_id=msg_id,
            internal_date="2025-01-15",
            gmail_uid="12345",
            subject="Scholar Alert",
            from_addr="scholar@google.com",
            to_addr="user@example.com",
            raw_html="<html>test</html>",
        )

        assert tmp_db.is_alert_email_processed(msg_id)

    def test_duplicate_email_ignored(self, tmp_db: Store) -> None:
        msg_id = "<dup-123@example.com>"
        tmp_db.insert_alert_email(
            message_id=msg_id,
            internal_date="2025-01-15",
            gmail_uid=None,
            subject="Alert",
            from_addr="scholar@google.com",
            to_addr="user@example.com",
            raw_html=None,
        )
        # INSERT OR IGNORE should not raise
        tmp_db.insert_alert_email(
            message_id=msg_id,
            internal_date="2025-01-16",
            gmail_uid=None,
            subject="Alert 2",
            from_addr="scholar@google.com",
            to_addr="user@example.com",
            raw_html=None,
        )
        assert tmp_db.is_alert_email_processed(msg_id)

    def test_insert_alert_item(self, tmp_db: Store) -> None:
        msg_id = "<item-test@example.com>"
        tmp_db.insert_alert_email(
            message_id=msg_id,
            internal_date="2025-01-15",
            gmail_uid=None,
            subject="Alert",
            from_addr="scholar@google.com",
            to_addr="user@example.com",
            raw_html=None,
        )

        item_id = tmp_db.insert_alert_item(
            message_id=msg_id,
            position=0,
            title="Test Paper",
            authors="A Smith, B Jones",
            venue="Nature",
            year=2025,
            target_url="https://example.com/paper.pdf",
            scholar_url="https://scholar.google.com/...",
        )
        assert item_id is not None
        assert isinstance(item_id, int)

    def test_update_alert_item_work_id(self, tmp_db: Store, sample_work: Work) -> None:
        msg_id = "<work-link@example.com>"
        tmp_db.insert_alert_email(
            message_id=msg_id,
            internal_date="2025-01-15",
            gmail_uid=None,
            subject="Alert",
            from_addr="scholar@google.com",
            to_addr="user@example.com",
            raw_html=None,
        )

        item_id = tmp_db.insert_alert_item(
            message_id=msg_id,
            position=0,
            title="Test Paper",
            authors="A Smith",
            venue=None,
            year=None,
            target_url=None,
            scholar_url=None,
        )

        # Insert a real work so FK constraint is satisfied
        work_id = tmp_db.insert_work(sample_work)
        tmp_db.update_alert_item_work_id(item_id, work_id)


# ── Config integration ────────────────────────────────────────


class TestScholarAlertConfig:
    def test_default_config(self) -> None:
        config = LabPubsConfig()
        assert config.scholar_alerts.enabled is False
        assert config.scholar_alerts.imap_server == "imap.gmail.com"

    def test_config_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = f"""
database_path: "{tmp_path / "test.db"}"
scholar_alerts:
  enabled: true
  imap_server: imap.gmail.com
  search:
    from_addr: "scholaralerts-noreply@google.com"
    unseen_only: false
  auth:
    username_env: MY_EMAIL
    app_password_env: MY_PASSWORD
  researcher_map:
    - researcher_name: "Jane Doe"
      scholar_profile_user: "abc123"
    - researcher_name: "John Smith"
      alert_subject_prefix: "John Smith"
"""
        config_path = tmp_path / "labpubs.yaml"
        config_path.write_text(yaml_content)

        from labpubs.config import load_config

        config = load_config(config_path)
        assert config.scholar_alerts.enabled is True
        assert config.scholar_alerts.auth.username_env == "MY_EMAIL"
        assert len(config.scholar_alerts.researcher_map) == 2
        assert config.scholar_alerts.researcher_map[0].scholar_profile_user == "abc123"
        assert (
            config.scholar_alerts.researcher_map[1].alert_subject_prefix == "John Smith"
        )

    def test_config_defaults_without_scholar_section(self, tmp_path: Path) -> None:
        yaml_content = f"""
database_path: "{tmp_path / "test.db"}"
researchers:
  - name: "Jane Doe"
"""
        config_path = tmp_path / "labpubs.yaml"
        config_path.write_text(yaml_content)

        from labpubs.config import load_config

        config = load_config(config_path)
        assert config.scholar_alerts.enabled is False
        assert config.scholar_alerts.researcher_map == []
