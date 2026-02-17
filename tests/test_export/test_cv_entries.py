"""Tests for CV citation formatting."""

import pytest

from labpubs.export.cv_entries import (
    _format_authors_apa,
    _format_authors_chicago,
    format_apa,
    format_chicago,
    format_work,
)
from labpubs.models import Author, Source, Work


class TestFormatAuthorsApa:
    """Tests for APA author formatting."""

    def test_single_author(self) -> None:
        """Single author: 'Family, I.'."""
        work = Work(
            title="Test",
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        result = _format_authors_apa(work)
        assert result == "Doe, J."

    def test_two_authors(self) -> None:
        """Two authors joined with &."""
        work = Work(
            title="Test",
            authors=[
                Author(name="Jane Doe"),
                Author(name="John Smith"),
            ],
            sources=[Source.OPENALEX],
        )
        result = _format_authors_apa(work)
        assert result == "Doe, J. & Smith, J."

    def test_three_authors(self) -> None:
        """Three authors: commas, then ', &' before last."""
        work = Work(
            title="Test",
            authors=[
                Author(name="Jane Doe"),
                Author(name="John Smith"),
                Author(name="Alice Bob"),
            ],
            sources=[Source.OPENALEX],
        )
        result = _format_authors_apa(work)
        assert result == "Doe, J., Smith, J., & Bob, A."

    def test_no_authors(self) -> None:
        """Empty authors returns empty string."""
        work = Work(title="Test", sources=[Source.OPENALEX])
        assert _format_authors_apa(work) == ""

    def test_single_name_author(self) -> None:
        """Author with only family name."""
        work = Work(
            title="Test",
            authors=[Author(name="Aristotle")],
            sources=[Source.OPENALEX],
        )
        result = _format_authors_apa(work)
        assert result == "Aristotle"


class TestFormatAuthorsChicago:
    """Tests for Chicago author formatting."""

    def test_single_author(self) -> None:
        """Single author: 'Family, Given'."""
        work = Work(
            title="Test",
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        result = _format_authors_chicago(work)
        assert result == "Doe, Jane"

    def test_two_authors(self) -> None:
        """Two authors joined with 'and'."""
        work = Work(
            title="Test",
            authors=[
                Author(name="Jane Doe"),
                Author(name="John Smith"),
            ],
            sources=[Source.OPENALEX],
        )
        result = _format_authors_chicago(work)
        assert result == "Doe, Jane and John Smith"

    def test_three_authors(self) -> None:
        """Three authors: commas, then ', and' before last."""
        work = Work(
            title="Test",
            authors=[
                Author(name="Jane Doe"),
                Author(name="John Smith"),
                Author(name="Alice Bob"),
            ],
            sources=[Source.OPENALEX],
        )
        result = _format_authors_chicago(work)
        assert result == "Doe, Jane, John Smith, and Alice Bob"

    def test_no_authors(self) -> None:
        """Empty authors returns empty string."""
        work = Work(title="Test", sources=[Source.OPENALEX])
        assert _format_authors_chicago(work) == ""


class TestApaFormat:
    """Tests for APA citation formatting."""

    def test_basic_format(self) -> None:
        """APA format includes author, year, title."""
        work = Work(
            title="Test Paper",
            year=2025,
            authors=[Author(name="Jane Doe")],
            venue="Test Journal",
            doi="10.1234/test",
            sources=[Source.OPENALEX],
        )
        result = format_apa(work)
        assert "Doe" in result
        assert "(2025)" in result
        assert "Test Paper" in result
        assert "Test Journal" in result

    def test_multiple_authors(self) -> None:
        """Multiple authors joined with &."""
        work = Work(
            title="Test",
            year=2025,
            authors=[
                Author(name="Jane Doe"),
                Author(name="John Smith"),
            ],
            sources=[Source.OPENALEX],
        )
        result = format_apa(work)
        assert "&" in result

    def test_no_year(self) -> None:
        """No year shows (n.d.)."""
        work = Work(
            title="Test",
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        result = format_apa(work)
        assert "(n.d.)" in result

    def test_doi_included(self) -> None:
        """DOI URL is included in output."""
        work = Work(
            title="Test",
            doi="10.1234/test",
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        result = format_apa(work)
        assert "https://doi.org/10.1234/test" in result


class TestChicagoFormat:
    """Tests for Chicago citation formatting."""

    def test_basic_format(self) -> None:
        """Chicago format includes author, year, title."""
        work = Work(
            title="Test Paper",
            year=2025,
            authors=[Author(name="Jane Doe")],
            venue="Test Journal",
            sources=[Source.OPENALEX],
        )
        result = format_chicago(work)
        assert "Doe" in result
        assert "2025" in result
        assert "Test Paper" in result

    def test_no_year(self) -> None:
        """No year shows 'n.d.'."""
        work = Work(
            title="Test",
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        result = format_chicago(work)
        assert "n.d." in result

    def test_doi_included(self) -> None:
        """DOI URL is included in output."""
        work = Work(
            title="Test",
            doi="10.1234/test",
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        result = format_chicago(work)
        assert "https://doi.org/10.1234/test" in result


class TestFormatWork:
    """Tests for format_work() dispatcher."""

    def test_invalid_style_raises(self) -> None:
        """Unsupported style raises ValueError."""
        work = Work(title="Test", sources=[Source.OPENALEX])
        with pytest.raises(ValueError, match="Unsupported style"):
            format_work(work, style="mla")

    def test_apa_style(self) -> None:
        """APA style dispatches correctly."""
        work = Work(
            title="Test",
            year=2025,
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        result = format_work(work, style="apa")
        assert "(2025)" in result

    def test_chicago_style(self) -> None:
        """Chicago style dispatches correctly."""
        work = Work(
            title="Test",
            year=2025,
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        result = format_work(work, style="chicago")
        assert "2025" in result
