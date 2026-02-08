"""Tests for BibTeX export."""

from labpubs.export.bibtex import _make_bibtex_key, works_to_bibtex
from labpubs.models import Author, Source, Work


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
