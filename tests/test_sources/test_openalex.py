"""Tests for OpenAlex work-to-model conversion."""

from datetime import date

from labpubs.models import Source, WorkType
from labpubs.sources.openalex import (
    _openalex_work_to_model,
    _parse_awards,
    _parse_funders,
    _reconstruct_abstract,
)


class TestOpenAlexWorkToModel:
    """Tests for _openalex_work_to_model()."""

    def _make_work(self, **overrides):
        """Build a complete OpenAlex work dict with sensible defaults."""
        base = {
            "id": "https://openalex.org/W1234567890",
            "doi": "https://doi.org/10.1234/test",
            "title": "Test Paper Title",
            "publication_date": "2025-06-15",
            "publication_year": 2025,
            "type": "article",
            "authorships": [
                {
                    "author": {
                        "display_name": "Jane Doe",
                        "id": "https://openalex.org/A111",
                        "orcid": "0000-0001-2345-6789",
                    },
                    "institutions": [{"display_name": "University of Washington"}],
                }
            ],
            "open_access": {"is_oa": True, "oa_url": "https://example.com/paper.pdf"},
            "cited_by_count": 42,
            "abstract_inverted_index": None,
            "primary_location": {"source": {"display_name": "Nature"}},
            "awards": [],
            "funders": [],
        }
        base.update(overrides)
        return base

    def test_complete_work(self) -> None:
        """All fields are populated from a complete dict."""
        raw = self._make_work()
        work = _openalex_work_to_model(raw)

        assert work.doi == "10.1234/test"
        assert work.title == "Test Paper Title"
        assert work.year == 2025
        assert work.publication_date == date(2025, 6, 15)
        assert work.work_type == WorkType.JOURNAL_ARTICLE
        assert work.openalex_id == "https://openalex.org/W1234567890"
        assert work.open_access is True
        assert work.open_access_url == "https://example.com/paper.pdf"
        assert work.citation_count == 42
        assert work.venue == "Nature"
        assert Source.OPENALEX in work.sources

    def test_author_fields(self) -> None:
        """Author name, IDs, and affiliation are extracted."""
        raw = self._make_work()
        work = _openalex_work_to_model(raw)

        assert len(work.authors) == 1
        author = work.authors[0]
        assert author.name == "Jane Doe"
        assert author.openalex_id == "https://openalex.org/A111"
        assert author.orcid == "0000-0001-2345-6789"
        assert author.affiliation == "University of Washington"

    def test_multiple_authors(self) -> None:
        """Multiple authorships are all parsed."""
        raw = self._make_work(
            authorships=[
                {"author": {"display_name": "Alice"}, "institutions": []},
                {"author": {"display_name": "Bob"}, "institutions": []},
                {"author": {"display_name": "Carol"}, "institutions": []},
            ]
        )
        work = _openalex_work_to_model(raw)
        assert len(work.authors) == 3
        assert [a.name for a in work.authors] == ["Alice", "Bob", "Carol"]

    def test_minimal_work(self) -> None:
        """Minimal dict produces valid Work with defaults."""
        raw = {"title": "Minimal", "type": "other"}
        work = _openalex_work_to_model(raw)

        assert work.title == "Minimal"
        assert work.doi is None
        assert work.year is None
        assert work.publication_date is None
        assert work.work_type == WorkType.OTHER
        assert work.authors == []
        assert work.venue is None
        assert Source.OPENALEX in work.sources

    def test_doi_url_prefix_stripped(self) -> None:
        """DOI URL prefix is normalized away."""
        raw = self._make_work(doi="https://doi.org/10.5555/UPPER")
        work = _openalex_work_to_model(raw)
        assert work.doi == "10.5555/upper"

    def test_doi_none(self) -> None:
        """Missing DOI results in None."""
        raw = self._make_work(doi=None)
        work = _openalex_work_to_model(raw)
        assert work.doi is None

    def test_unknown_work_type(self) -> None:
        """Unmapped type falls back to OTHER."""
        raw = self._make_work(type="paratext")
        work = _openalex_work_to_model(raw)
        assert work.work_type == WorkType.OTHER

    def test_conference_paper_type(self) -> None:
        """proceedings-article maps to CONFERENCE_PAPER."""
        raw = self._make_work(type="proceedings-article")
        work = _openalex_work_to_model(raw)
        assert work.work_type == WorkType.CONFERENCE_PAPER

    def test_preprint_type(self) -> None:
        """posted-content maps to PREPRINT."""
        raw = self._make_work(type="posted-content")
        work = _openalex_work_to_model(raw)
        assert work.work_type == WorkType.PREPRINT

    def test_invalid_publication_date(self) -> None:
        """Invalid date string results in None publication_date."""
        raw = self._make_work(publication_date="not-a-date")
        work = _openalex_work_to_model(raw)
        assert work.publication_date is None

    def test_missing_publication_date(self) -> None:
        """Missing publication_date key results in None."""
        raw = self._make_work()
        del raw["publication_date"]
        work = _openalex_work_to_model(raw)
        assert work.publication_date is None

    def test_abstract_inverted_index(self) -> None:
        """Abstract is reconstructed from inverted index."""
        raw = self._make_work(
            abstract_inverted_index={
                "We": [0],
                "study": [1],
                "data": [2],
                "management": [3],
            }
        )
        work = _openalex_work_to_model(raw)
        assert work.abstract == "We study data management"

    def test_no_abstract(self) -> None:
        """No abstract when inverted index is None."""
        raw = self._make_work(abstract_inverted_index=None)
        work = _openalex_work_to_model(raw)
        assert work.abstract is None

    def test_no_venue(self) -> None:
        """Missing primary_location results in None venue."""
        raw = self._make_work(primary_location=None)
        work = _openalex_work_to_model(raw)
        assert work.venue is None

    def test_venue_no_source(self) -> None:
        """primary_location without source results in None venue."""
        raw = self._make_work(primary_location={"source": None})
        work = _openalex_work_to_model(raw)
        assert work.venue is None

    def test_author_no_institutions(self) -> None:
        """Author without institutions gets None affiliation."""
        raw = self._make_work(
            authorships=[{"author": {"display_name": "Solo"}, "institutions": []}]
        )
        work = _openalex_work_to_model(raw)
        assert work.authors[0].affiliation is None

    def test_missing_title_defaults(self) -> None:
        """Missing title defaults to 'Untitled'."""
        raw = self._make_work()
        del raw["title"]
        work = _openalex_work_to_model(raw)
        assert work.title == "Untitled"


class TestReconstructAbstract:
    """Tests for _reconstruct_abstract()."""

    def test_normal_reconstruction(self) -> None:
        """Words are placed at their correct positions."""
        index = {"Hello": [0], "world": [1]}
        assert _reconstruct_abstract(index) == "Hello world"

    def test_repeated_word(self) -> None:
        """A word appearing at multiple positions is placed correctly."""
        index = {"the": [0, 2], "cat": [1], "dog": [3]}
        result = _reconstruct_abstract(index)
        assert result == "the cat the dog"

    def test_empty_index(self) -> None:
        """Empty inverted index returns empty string."""
        assert _reconstruct_abstract({}) == ""

    def test_single_word(self) -> None:
        """Single-word abstract."""
        assert _reconstruct_abstract({"Abstract": [0]}) == "Abstract"


class TestParseAwards:
    """Tests for _parse_awards()."""

    def test_parses_award_with_funder(self) -> None:
        """Award with funder data produces Award with Funder."""
        raw = [
            {
                "id": "https://openalex.org/award1",
                "display_name": "Grant ABC",
                "funder_id": "https://openalex.org/F111",
                "funder_display_name": "NSF",
                "funder_award_id": "ABC-123",
                "doi": "10.1234/award",
            }
        ]
        awards = _parse_awards(raw)
        assert len(awards) == 1
        assert awards[0].openalex_id == "https://openalex.org/award1"
        assert awards[0].display_name == "Grant ABC"
        assert awards[0].funder is not None
        assert awards[0].funder.name == "NSF"

    def test_skips_award_without_id(self) -> None:
        """Awards without an id are skipped."""
        raw = [{"display_name": "No ID Award"}]
        assert _parse_awards(raw) == []

    def test_award_without_funder(self) -> None:
        """Award without funder_id still works (funder is None)."""
        raw = [{"id": "https://openalex.org/award2"}]
        awards = _parse_awards(raw)
        assert len(awards) == 1
        assert awards[0].funder is None

    def test_empty_list(self) -> None:
        """Empty list returns empty."""
        assert _parse_awards([]) == []


class TestParseFunders:
    """Tests for _parse_funders()."""

    def test_parses_funder(self) -> None:
        """Funder with name and ID is parsed."""
        raw = [
            {
                "id": "https://openalex.org/F111",
                "display_name": "NSF",
                "ror": "https://ror.org/021nxhr62",
            }
        ]
        funders = _parse_funders(raw)
        assert len(funders) == 1
        assert funders[0].name == "NSF"
        assert funders[0].ror_id == "https://ror.org/021nxhr62"

    def test_skips_funder_without_id(self) -> None:
        """Funders without id are skipped."""
        raw = [{"display_name": "No ID Org"}]
        assert _parse_funders(raw) == []

    def test_skips_funder_without_name(self) -> None:
        """Funders without display_name are skipped."""
        raw = [{"id": "https://openalex.org/F222"}]
        assert _parse_funders(raw) == []

    def test_empty_list(self) -> None:
        """Empty list returns empty."""
        assert _parse_funders([]) == []
