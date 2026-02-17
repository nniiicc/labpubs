"""Tests for Crossref message-to-model conversion."""

from datetime import date

from labpubs.models import Source, WorkType
from labpubs.sources.crossref import _crossref_to_work


def _make_message(**overrides):
    """Build a complete Crossref message dict with sensible defaults."""
    base = {
        "DOI": "10.1234/test",
        "title": ["Test Paper Title"],
        "author": [
            {
                "given": "Jane",
                "family": "Doe",
                "affiliation": [{"name": "University of Washington"}],
            }
        ],
        "published-print": {"date-parts": [[2025, 6, 15]]},
        "type": "journal-article",
        "container-title": ["Nature"],
        "is-referenced-by-count": 42,
    }
    base.update(overrides)
    return base


class TestCrossrefToWork:
    """Tests for _crossref_to_work()."""

    def test_complete_message(self) -> None:
        """All fields are populated from a complete dict."""
        msg = _make_message()
        work = _crossref_to_work(msg)

        assert work.doi == "10.1234/test"
        assert work.title == "Test Paper Title"
        assert work.year == 2025
        assert work.publication_date == date(2025, 6, 15)
        assert work.work_type == WorkType.JOURNAL_ARTICLE
        assert work.venue == "Nature"
        assert work.citation_count == 42
        assert Source.CROSSREF in work.sources

    def test_author_fields(self) -> None:
        """Author name and affiliation are extracted."""
        msg = _make_message()
        work = _crossref_to_work(msg)

        assert len(work.authors) == 1
        author = work.authors[0]
        assert author.name == "Jane Doe"
        assert author.affiliation == "University of Washington"

    def test_multiple_authors(self) -> None:
        """Multiple authors are all parsed."""
        msg = _make_message(
            author=[
                {"given": "Alice", "family": "Smith", "affiliation": []},
                {"given": "Bob", "family": "Jones", "affiliation": []},
            ]
        )
        work = _crossref_to_work(msg)
        assert len(work.authors) == 2
        assert work.authors[0].name == "Alice Smith"
        assert work.authors[1].name == "Bob Jones"

    def test_author_family_only(self) -> None:
        """Author with only family name."""
        msg = _make_message(
            author=[{"family": "Mono", "affiliation": []}]
        )
        work = _crossref_to_work(msg)
        assert work.authors[0].name == "Mono"

    def test_no_authors(self) -> None:
        """Missing author key produces empty list."""
        msg = _make_message()
        del msg["author"]
        work = _crossref_to_work(msg)
        assert work.authors == []

    def test_doi_lowercased(self) -> None:
        """DOI is lowercased."""
        msg = _make_message(DOI="10.5555/UPPER")
        work = _crossref_to_work(msg)
        assert work.doi == "10.5555/upper"

    def test_doi_none(self) -> None:
        """Missing DOI results in None."""
        msg = _make_message()
        del msg["DOI"]
        work = _crossref_to_work(msg)
        assert work.doi is None

    def test_year_only_date(self) -> None:
        """Date-parts with only year still works."""
        msg = _make_message(**{"published-print": {"date-parts": [[2024]]}})
        work = _crossref_to_work(msg)
        assert work.year == 2024
        assert work.publication_date == date(2024, 1, 1)

    def test_year_month_date(self) -> None:
        """Date-parts with year and month (no day)."""
        msg = _make_message(**{"published-print": {"date-parts": [[2024, 3]]}})
        work = _crossref_to_work(msg)
        assert work.year == 2024
        assert work.publication_date == date(2024, 3, 1)

    def test_no_date(self) -> None:
        """Missing date-parts results in None year and date."""
        msg = _make_message(**{"published-print": {"date-parts": [[]]}})
        # Also remove published-online
        work = _crossref_to_work(msg)
        assert work.year is None
        assert work.publication_date is None

    def test_falls_back_to_online_date(self) -> None:
        """Falls back to published-online when published-print is empty."""
        msg = _make_message(
            **{
                "published-print": {"date-parts": [[]]},
                "published-online": {"date-parts": [[2025, 1, 10]]},
            }
        )
        work = _crossref_to_work(msg)
        assert work.year == 2025
        assert work.publication_date == date(2025, 1, 10)

    def test_conference_paper_type(self) -> None:
        """proceedings-article maps to CONFERENCE_PAPER."""
        msg = _make_message(type="proceedings-article")
        work = _crossref_to_work(msg)
        assert work.work_type == WorkType.CONFERENCE_PAPER

    def test_preprint_type(self) -> None:
        """posted-content maps to PREPRINT."""
        msg = _make_message(type="posted-content")
        work = _crossref_to_work(msg)
        assert work.work_type == WorkType.PREPRINT

    def test_unknown_type(self) -> None:
        """Unmapped type falls back to OTHER."""
        msg = _make_message(type="component")
        work = _crossref_to_work(msg)
        assert work.work_type == WorkType.OTHER

    def test_missing_title(self) -> None:
        """Empty title list defaults to 'Untitled'."""
        msg = _make_message(title=[])
        work = _crossref_to_work(msg)
        assert work.title == "Untitled"

    def test_no_venue(self) -> None:
        """Missing container-title produces None venue."""
        msg = _make_message(**{"container-title": []})
        work = _crossref_to_work(msg)
        assert work.venue is None

    def test_author_no_affiliation(self) -> None:
        """Author with empty affiliation list gets None."""
        msg = _make_message(
            author=[{"given": "Solo", "family": "Act", "affiliation": []}]
        )
        work = _crossref_to_work(msg)
        assert work.authors[0].affiliation is None
