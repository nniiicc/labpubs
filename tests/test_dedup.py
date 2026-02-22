"""Tests for deduplication logic."""

from labpubs.dedup import (
    _pick_richer_authors,
    _pick_richer_str,
    find_match,
    merge_works,
)
from labpubs.models import Author, Source, Work
from labpubs.normalize import normalize_doi, normalize_title


class TestNormalizeDoi:
    """Tests for DOI normalization."""

    def test_strips_url_prefix(self) -> None:
        """DOI URL prefixes are removed."""
        assert normalize_doi("https://doi.org/10.1234/test") == "10.1234/test"

    def test_lowercases(self) -> None:
        """DOIs are lowercased."""
        assert normalize_doi("10.1234/TEST") == "10.1234/test"

    def test_none_passthrough(self) -> None:
        """None input returns None."""
        assert normalize_doi(None) is None

    def test_empty_string(self) -> None:
        """Empty string returns None."""
        assert normalize_doi("") is None


class TestNormalizeTitle:
    """Tests for title normalization."""

    def test_lowercases_and_strips_punctuation(self) -> None:
        """Titles are lowercased with punctuation removed."""
        result = normalize_title("Hello, World!")
        assert result == "hello world"

    def test_collapses_whitespace(self) -> None:
        """Multiple spaces are collapsed."""
        result = normalize_title("hello   world")
        assert result == "hello world"

    def test_strips_accents(self) -> None:
        """Diacritical marks are removed."""
        result = normalize_title("cafe\u0301")
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

    def test_preserves_longer_venue(self) -> None:
        """Longer venue string is preferred."""
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
        # Equal length: existing wins
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

    def test_prefers_richer_title(self) -> None:
        """Longer non-truncated title replaces shorter one."""
        existing = Work(
            title="Comp. approaches to...",
            sources=[Source.GOOGLE_SCHOLAR_ALERT],
        )
        new = Work(
            title="Computational Approaches to Federal Rulemaking",
            sources=[Source.OPENALEX],
        )
        merged = merge_works(existing, new)
        assert merged.title == new.title

    def test_prefers_richer_venue(self) -> None:
        """Full venue name replaces abbreviated one."""
        existing = Work(
            title="Test",
            venue="J. Pol.",
            sources=[Source.GOOGLE_SCHOLAR_ALERT],
        )
        new = Work(
            title="Test",
            venue="Journal of Policy Analysis and Management",
            sources=[Source.OPENALEX],
        )
        merged = merge_works(existing, new)
        assert merged.venue == new.venue

    def test_prefers_richer_authors(self) -> None:
        """Full author names replace abbreviated initials."""
        existing = Work(
            title="Test",
            authors=[Author(name="C Shah")],
            sources=[Source.GOOGLE_SCHOLAR_ALERT],
        )
        new = Work(
            title="Test",
            authors=[
                Author(name="Chirag Shah", openalex_id="A123"),
            ],
            sources=[Source.OPENALEX],
        )
        merged = merge_works(existing, new)
        assert merged.authors[0].name == "Chirag Shah"

    def test_prefers_more_authors(self) -> None:
        """Author list with more entries is preferred."""
        existing = Work(
            title="Test",
            authors=[Author(name="J Doe")],
            sources=[Source.GOOGLE_SCHOLAR_ALERT],
        )
        new = Work(
            title="Test",
            authors=[
                Author(name="Jane Doe"),
                Author(name="John Smith"),
            ],
            sources=[Source.OPENALEX],
        )
        merged = merge_works(existing, new)
        assert len(merged.authors) == 2


class TestPickRicherStr:
    """Tests for _pick_richer_str helper."""

    def test_none_a(self) -> None:
        """None first returns second."""
        assert _pick_richer_str(None, "hello") == "hello"

    def test_none_b(self) -> None:
        """None second returns first."""
        assert _pick_richer_str("hello", None) == "hello"

    def test_both_none(self) -> None:
        """Both None returns None."""
        assert _pick_richer_str(None, None) is None

    def test_empty_a(self) -> None:
        """Empty first returns second."""
        assert _pick_richer_str("", "hello") == "hello"

    def test_prefers_longer(self) -> None:
        """Longer string wins."""
        assert _pick_richer_str("ab", "abc") == "abc"

    def test_equal_length_prefers_first(self) -> None:
        """Equal length prefers first argument."""
        assert _pick_richer_str("abc", "xyz") == "abc"

    def test_truncated_ellipsis_loses(self) -> None:
        """String with trailing ellipsis loses to non-truncated."""
        assert _pick_richer_str("hello...", "hi") == "hi"

    def test_truncated_unicode_ellipsis_loses(self) -> None:
        """String with trailing unicode ellipsis loses."""
        assert _pick_richer_str("hello\u2026", "hi") == "hi"

    def test_both_truncated_prefers_longer(self) -> None:
        """When both truncated, longer wins."""
        assert _pick_richer_str("abc...", "abcdef...") == "abcdef..."


class TestPickRicherAuthors:
    """Tests for _pick_richer_authors helper."""

    def test_empty_a(self) -> None:
        """Empty first returns second."""
        b = [Author(name="Jane Doe")]
        assert _pick_richer_authors([], b) == b

    def test_empty_b(self) -> None:
        """Empty second returns first."""
        a = [Author(name="Jane Doe")]
        assert _pick_richer_authors(a, []) == a

    def test_more_authors_wins(self) -> None:
        """List with more entries wins."""
        a = [Author(name="J Doe")]
        b = [Author(name="Jane Doe"), Author(name="John Smith")]
        assert _pick_richer_authors(a, b) == b

    def test_same_count_prefers_longer_names(self) -> None:
        """Same count: longer total name length wins."""
        a = [Author(name="C Shah")]
        b = [Author(name="Chirag Shah")]
        assert _pick_richer_authors(a, b) == b

    def test_same_count_same_length_prefers_first(self) -> None:
        """Same count and length: first argument wins."""
        a = [Author(name="Jane Doe")]
        b = [Author(name="John Doe")]
        assert _pick_richer_authors(a, b) == a
