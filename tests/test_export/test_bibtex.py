"""Tests for BibTeX export."""

from labpubs.export.bibtex import (
    _format_authors,
    _make_bibtex_key,
    work_to_bibtex_entry,
    works_to_bibtex,
)
from labpubs.models import Author, Source, Work, WorkType


class TestBibtexKey:
    """Tests for BibTeX key generation."""

    def test_basic_key(self) -> None:
        """Key follows {surname}{year}{word} format."""
        work = Work(
            title="Computational Approaches to Policy",
            year=2025,
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        key = _make_bibtex_key(work)
        assert key == "doe2025computational"

    def test_no_authors(self) -> None:
        """Missing authors produce 'unknown' surname."""
        work = Work(
            title="Test Paper",
            year=2025,
            sources=[Source.OPENALEX],
        )
        key = _make_bibtex_key(work)
        assert key.startswith("unknown")

    def test_no_year(self) -> None:
        """Missing year uses 'nd'."""
        work = Work(
            title="Test Paper",
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        key = _make_bibtex_key(work)
        assert "nd" in key

    def test_skips_stop_words(self) -> None:
        """Title stop words are skipped for the key."""
        work = Work(
            title="The Art of Programming",
            year=2025,
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        key = _make_bibtex_key(work)
        assert key == "doe2025art"


class TestFormatAuthors:
    """Tests for _format_authors()."""

    def test_single_author(self) -> None:
        """Single author: 'Family, Given'."""
        work = Work(
            title="Test",
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        assert _format_authors(work) == "Doe, Jane"

    def test_two_authors(self) -> None:
        """Two authors joined with ' and '."""
        work = Work(
            title="Test",
            authors=[
                Author(name="Jane Doe"),
                Author(name="John Smith"),
            ],
            sources=[Source.OPENALEX],
        )
        result = _format_authors(work)
        assert result == "Doe, Jane and Smith, John"

    def test_three_authors(self) -> None:
        """Three authors all included."""
        work = Work(
            title="Test",
            authors=[
                Author(name="Jane Doe"),
                Author(name="John Smith"),
                Author(name="Alice Bob"),
            ],
            sources=[Source.OPENALEX],
        )
        result = _format_authors(work)
        assert "Doe, Jane" in result
        assert "Smith, John" in result
        assert "Bob, Alice" in result
        assert " and " in result

    def test_single_name_author(self) -> None:
        """Author with only one name (no given name)."""
        work = Work(
            title="Test",
            authors=[Author(name="Aristotle")],
            sources=[Source.OPENALEX],
        )
        assert _format_authors(work) == "Aristotle"


class TestWorkToBibtexEntry:
    """Tests for work_to_bibtex_entry()."""

    def test_journal_article(self) -> None:
        """Journal article uses 'article' type and 'journal' field."""
        work = Work(
            title="Test Paper",
            work_type=WorkType.JOURNAL_ARTICLE,
            venue="Nature",
            year=2025,
            doi="10.1234/test",
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        entry = work_to_bibtex_entry(work)
        assert entry["ENTRYTYPE"] == "article"
        assert entry["journal"] == "Nature"
        assert entry["year"] == "2025"
        assert entry["doi"] == "10.1234/test"

    def test_conference_paper(self) -> None:
        """Conference paper uses 'inproceedings' and 'booktitle'."""
        work = Work(
            title="Test Paper",
            work_type=WorkType.CONFERENCE_PAPER,
            venue="SIGMOD 2025",
            sources=[Source.OPENALEX],
        )
        entry = work_to_bibtex_entry(work)
        assert entry["ENTRYTYPE"] == "inproceedings"
        assert entry["booktitle"] == "SIGMOD 2025"

    def test_preprint(self) -> None:
        """Preprint maps to 'misc'."""
        work = Work(
            title="Test",
            work_type=WorkType.PREPRINT,
            sources=[Source.OPENALEX],
        )
        entry = work_to_bibtex_entry(work)
        assert entry["ENTRYTYPE"] == "misc"

    def test_open_access_url(self) -> None:
        """Open access URL is included."""
        work = Work(
            title="Test",
            open_access_url="https://arxiv.org/abs/1234",
            sources=[Source.OPENALEX],
        )
        entry = work_to_bibtex_entry(work)
        assert entry["url"] == "https://arxiv.org/abs/1234"

    def test_title_braced(self) -> None:
        """Title is wrapped in braces for case preservation."""
        work = Work(title="My Title", sources=[Source.OPENALEX])
        entry = work_to_bibtex_entry(work)
        assert entry["title"] == "{My Title}"


class TestBibtexExport:
    """Tests for full BibTeX export."""

    def test_exports_nonempty(self, sample_work: Work) -> None:
        """BibTeX export produces non-empty output."""
        result = works_to_bibtex([sample_work])
        assert len(result) > 0
        assert "@article" in result.lower() or "@" in result

    def test_empty_list(self) -> None:
        """Empty input produces minimal output."""
        result = works_to_bibtex([])
        # bibtexparser may return empty or minimal string
        assert isinstance(result, str)
