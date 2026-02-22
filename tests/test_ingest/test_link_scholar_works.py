"""Tests for scholar-alert orphan linking."""

import sqlite3

import pytest

from labpubs.ingest.link_scholar_works import (
    link_scholar_works,
    match_alert_name_to_researcher,
    matches_author_initials,
)

SCHEMA = """
CREATE TABLE researchers (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL
);
CREATE TABLE works (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL
);
CREATE TABLE work_authors (
    work_id INTEGER REFERENCES works(id),
    author_name TEXT NOT NULL,
    author_position INTEGER NOT NULL,
    PRIMARY KEY (work_id, author_position)
);
CREATE TABLE researcher_works (
    researcher_id INTEGER REFERENCES researchers(id),
    work_id INTEGER REFERENCES works(id),
    PRIMARY KEY (researcher_id, work_id)
);
CREATE TABLE scholar_alert_emails (
    message_id TEXT PRIMARY KEY, subject TEXT
);
CREATE TABLE scholar_alert_items (
    id INTEGER PRIMARY KEY,
    message_id TEXT REFERENCES scholar_alert_emails(message_id),
    work_id INTEGER REFERENCES works(id),
    position INTEGER
);
"""


@pytest.fixture
def db(tmp_path: "pytest.TempPathFactory") -> str:
    """Create a temporary database with test schema and seed data.

    Returns:
        Path to the SQLite database file.
    """
    from pathlib import Path

    db_path = str(Path(tmp_path) / "test.db")  # type: ignore[arg-type]
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)

    # Seed researchers
    conn.executemany(
        "INSERT INTO researchers (id, name) VALUES (?, ?)",
        [
            (1, "Chirag Shah"),
            (2, "Emma Spiro"),
            (3, "Tanu Mitra"),
            (4, "Benjamin Charles Germain Lee"),
        ],
    )

    # Seed a work with its author
    conn.execute("INSERT INTO works (id, title) VALUES (1, 'Test Paper')")
    conn.execute(
        "INSERT INTO work_authors (work_id, author_name, author_position) "
        "VALUES (1, 'C Shah', 0)"
    )

    # Seed scholar alert linking the work
    conn.execute(
        "INSERT INTO scholar_alert_emails (message_id, subject) "
        "VALUES ('msg1', 'Chirag Shah - new articles')"
    )
    conn.execute(
        "INSERT INTO scholar_alert_items "
        "(id, message_id, work_id, position) "
        "VALUES (1, 'msg1', 1, 0)"
    )

    conn.commit()
    conn.close()
    return db_path


class TestMatchAlertName:
    """Tests for alert name to researcher matching."""

    researchers = [
        "Chirag Shah",
        "Emma Spiro",
        "Tanu Mitra",
        "Benjamin Charles Germain Lee",
    ]

    def test_exact_match(self) -> None:
        """Exact name matches."""
        assert (
            match_alert_name_to_researcher("Chirag Shah", self.researchers)
            == "Chirag Shah"
        )

    def test_middle_initial(self) -> None:
        """Name with middle initial matches."""
        assert (
            match_alert_name_to_researcher("Emma S. Spiro", self.researchers)
            == "Emma Spiro"
        )

    def test_nickname(self) -> None:
        """Nickname maps to canonical name."""
        assert (
            match_alert_name_to_researcher("Tanushree Mitra", self.researchers)
            == "Tanu Mitra"
        )

    def test_no_match(self) -> None:
        """Unknown name returns None."""
        assert (
            match_alert_name_to_researcher("Unknown Person", self.researchers) is None
        )

    def test_single_token_returns_none(self) -> None:
        """Single-word name returns None."""
        assert match_alert_name_to_researcher("Chirag", self.researchers) is None

    def test_hyphenated_first_name(self) -> None:
        """Hyphenated first name matches via prefix."""
        researchers = ["Anna Gueorguieva"]
        assert (
            match_alert_name_to_researcher("Anna-Maria Gueorguieva", researchers)
            == "Anna Gueorguieva"
        )

    def test_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        assert (
            match_alert_name_to_researcher("chirag shah", self.researchers)
            == "Chirag Shah"
        )


class TestMatchesAuthorInitials:
    """Tests for author initial matching."""

    def test_single_initial(self) -> None:
        """Single initial matches first name."""
        assert matches_author_initials("C Shah", "Chirag Shah") is True

    def test_multi_initial(self) -> None:
        """Multi-character initial block matches."""
        assert (
            matches_author_initials("BCG Lee", "Benjamin Charles Germain Lee") is True
        )

    def test_full_name(self) -> None:
        """Full name matches."""
        assert matches_author_initials("Chirag Shah", "Chirag Shah") is True

    def test_trailing_ellipsis(self) -> None:
        """Trailing ellipsis is stripped."""
        assert matches_author_initials("B Wen\u2026", "Bingbing Wen") is True

    def test_wrong_surname(self) -> None:
        """Different surname does not match."""
        assert matches_author_initials("C Jones", "Chirag Shah") is False

    def test_wrong_initial(self) -> None:
        """Wrong initial does not match."""
        assert matches_author_initials("Z Shah", "Chirag Shah") is False

    def test_single_token(self) -> None:
        """Single-token name returns False."""
        assert matches_author_initials("Shah", "Chirag Shah") is False

    def test_three_part_name(self) -> None:
        """Three-part full name matches."""
        assert matches_author_initials("Shahan Ali Memon", "Shahan Ali Memon") is True

    def test_extra_middle_initials(self) -> None:
        """Author initials with extra middle names still match."""
        assert matches_author_initials("JD West", "Jevin West") is True

    def test_trailing_dots(self) -> None:
        """Trailing dots are stripped."""
        assert matches_author_initials("B Wen...", "Bingbing Wen") is True


class TestLinkScholarWorks:
    """End-to-end tests for link_scholar_works."""

    def test_links_orphaned_work(self, db: str) -> None:
        """Orphaned work gets linked to researcher."""
        count = link_scholar_works(db)
        assert count == 1

        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT researcher_id, work_id FROM researcher_works"
        ).fetchall()
        conn.close()
        assert rows == [(1, 1)]

    def test_idempotent(self, db: str) -> None:
        """Running twice produces same result."""
        link_scholar_works(db)
        count = link_scholar_works(db)
        assert count == 0

    def test_already_linked_skipped(self, db: str) -> None:
        """Works with existing linkages are skipped."""
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO researcher_works (researcher_id, work_id) VALUES (1, 1)"
        )
        conn.commit()
        conn.close()

        count = link_scholar_works(db)
        assert count == 0

    def test_author_validation_prevents_bad_link(self, db: str) -> None:
        """Work not authored by the researcher is not linked."""
        conn = sqlite3.connect(db)
        # Replace author with someone else
        conn.execute("DELETE FROM work_authors WHERE work_id = 1")
        conn.execute(
            "INSERT INTO work_authors (work_id, author_name, author_position) "
            "VALUES (1, 'J Doe', 0)"
        )
        conn.commit()
        conn.close()

        count = link_scholar_works(db)
        assert count == 0

    def test_no_orphans_returns_zero(self, db: str) -> None:
        """No orphaned works returns zero."""
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO researcher_works (researcher_id, work_id) VALUES (1, 1)"
        )
        conn.commit()
        conn.close()

        count = link_scholar_works(db)
        assert count == 0

    def test_multi_alert_multi_researcher(self, db: str) -> None:
        """Work appearing in multiple alerts gets multiple linkages."""
        conn = sqlite3.connect(db)
        # Add Emma Spiro as co-author
        conn.execute(
            "INSERT INTO work_authors (work_id, author_name, author_position) "
            "VALUES (1, 'E Spiro', 1)"
        )
        # Add alert from Emma's feed
        conn.execute(
            "INSERT INTO scholar_alert_emails (message_id, subject) "
            "VALUES ('msg2', 'Emma Spiro - new articles')"
        )
        conn.execute(
            "INSERT INTO scholar_alert_items "
            "(id, message_id, work_id, position) "
            "VALUES (2, 'msg2', 1, 0)"
        )
        conn.commit()
        conn.close()

        count = link_scholar_works(db)
        assert count == 2

    def test_unmatched_alert_name_skipped(self, db: str) -> None:
        """Alert from unknown researcher is skipped."""
        conn = sqlite3.connect(db)
        # Change alert subject to unknown researcher
        conn.execute(
            "UPDATE scholar_alert_emails "
            "SET subject = 'Unknown Person - new articles' "
            "WHERE message_id = 'msg1'"
        )
        conn.commit()
        conn.close()

        count = link_scholar_works(db)
        assert count == 0
