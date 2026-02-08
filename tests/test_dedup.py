"""Tests for deduplication logic."""

from labpubs.dedup import (
    _normalize_doi,
    _normalize_title,
    find_match,
    merge_works,
)
from labpubs.models import Author, Source, Work


class TestNormalizeDoi:
    """Tests for DOI normalization."""

    def test_strips_url_prefix(self) -> None:
        """DOI URL prefixes are removed."""
        assert _normalize_doi("https://doi.org/10.1234/test") == "10.1234/test"

    def test_lowercases(self) -> None:
        """DOIs are lowercased."""
        assert _normalize_doi("10.1234/TEST") == "10.1234/test"

    def test_none_passthrough(self) -> None:
        """None input returns None."""
        assert _normalize_doi(None) is None

    def test_empty_string(self) -> None:
        """Empty string returns None."""
        assert _normalize_doi("") is None


class TestNormalizeTitle:
    """Tests for title normalization."""

    def test_lowercases_and_strips_punctuation(self) -> None:
        """Titles are lowercased with punctuation removed."""
        result = _normalize_title("Hello, World!")
        assert result == "hello world"

    def test_collapses_whitespace(self) -> None:
        """Multiple spaces are collapsed."""
        result = _normalize_title("hello   world")
        assert result == "hello world"

    def test_strips_accents(self) -> None:
        """Diacritical marks are removed."""
        result = _normalize_title("cafe\u0301")
        assert result == "cafe"


class TestFindMatch:
    """Tests for tiered matching."""

    def test_doi_exact_match(self) -> None:
        """Tier 1: exact DOI match."""
        candidate = Work(
            title="Test Paper",
            doi="10.1234/test",
            sources=[Source.OPENALEX],
        )
        existing = [
            (1, "test paper", "10.1234/test", 2025, ["doe"]),
        ]
        assert find_match(candidate, existing) == 1

    def test_fuzzy_title_match(self) -> None:
        """Tier 2: fuzzy title match above threshold."""
        candidate = Work(
            title="Computational Approaches to Federal Rulemaking",
            sources=[Source.OPENALEX],
        )
        existing = [
            (
                1,
                "computational approaches to federal rulemaking",
                None,
                2025,
                ["doe"],
            ),
        ]
        assert find_match(candidate, existing) == 1

    def test_no_match(self) -> None:
        """No match returns None."""
        candidate = Work(
            title="Completely Different Paper",
            sources=[Source.OPENALEX],
        )
        existing = [
            (1, "unrelated work on biology", None, 2020, ["smith"]),
        ]
        assert find_match(candidate, existing) is None

    def test_author_year_fallback(self) -> None:
        """Tier 3: short title + author overlap + same year."""
        candidate = Work(
            title="A Survey",
            year=2025,
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        existing = [
            (1, "a survey", None, 2025, ["doe"]),
        ]
        assert find_match(candidate, existing) == 1


class TestMergeWorks:
    """Tests for metadata merging."""

    def test_fills_missing_fields(self) -> None:
        """New source data fills in gaps."""
        existing = Work(
            title="Test Paper",
            doi="10.1234/test",
            year=2025,
            sources=[Source.OPENALEX],
        )
        new = Work(
            title="Test Paper",
            doi="10.1234/test",
            year=2025,
            tldr="A great paper.",
            semantic_scholar_id="abc123",
            sources=[Source.SEMANTIC_SCHOLAR],
        )
        merged = merge_works(existing, new)
        assert merged.tldr == "A great paper."
        assert merged.semantic_scholar_id == "abc123"
        assert Source.OPENALEX in merged.sources
        assert Source.SEMANTIC_SCHOLAR in merged.sources

    def test_preserves_existing_data(self) -> None:
        """Existing data is not overwritten."""
        existing = Work(
            title="Test Paper",
            venue="Journal A",
            sources=[Source.OPENALEX],
        )
        new = Work(
            title="Test Paper",
            venue="Journal B",
            sources=[Source.SEMANTIC_SCHOLAR],
        )
        merged = merge_works(existing, new)
        assert merged.venue == "Journal A"

    def test_takes_higher_citation_count(self) -> None:
        """Higher citation count is preferred."""
        existing = Work(
            title="Test",
            citation_count=10,
            sources=[Source.OPENALEX],
        )
        new = Work(
            title="Test",
            citation_count=15,
            sources=[Source.SEMANTIC_SCHOLAR],
        )
        merged = merge_works(existing, new)
        assert merged.citation_count == 15
