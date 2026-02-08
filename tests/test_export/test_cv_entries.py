"""Tests for CV citation formatting."""

from labpubs.export.cv_entries import format_apa, format_chicago
from labpubs.models import Author, Source, Work


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
