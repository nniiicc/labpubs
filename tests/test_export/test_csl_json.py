"""Tests for CSL-JSON export."""

from datetime import date

from labpubs.export.csl_json import work_to_csl, works_to_csl_json
from labpubs.models import Author, Source, Work, WorkType


class TestWorkToCsl:
    """Tests for work_to_csl()."""

    def test_basic_structure(self) -> None:
        """CSL entry has required keys."""
        work = Work(
            title="Test Paper",
            year=2025,
            doi="10.1234/test",
            work_type=WorkType.JOURNAL_ARTICLE,
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert csl["title"] == "Test Paper"
        assert csl["type"] == "article-journal"
        assert "id" in csl
        assert "author" in csl

    def test_doi_based_id(self) -> None:
        """ID is generated from DOI when available."""
        work = Work(
            title="Test",
            doi="10.1234/test.paper",
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert csl["DOI"] == "10.1234/test.paper"
        assert csl["id"] == "10-1234_test-paper"

    def test_title_based_id_when_no_doi(self) -> None:
        """ID is generated from title when no DOI."""
        work = Work(
            title="My Paper",
            year=2025,
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert "My_Paper" in csl["id"]
        assert "_2025" in csl["id"]

    def test_title_based_id_no_year(self) -> None:
        """ID uses 'nd' when no DOI and no year."""
        work = Work(
            title="My Paper",
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert csl["id"].endswith("_nd")

    def test_author_two_names(self) -> None:
        """Author with given and family name."""
        work = Work(
            title="Test",
            authors=[Author(name="Jane Doe")],
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert csl["author"] == [{"family": "Doe", "given": "Jane"}]

    def test_author_single_name(self) -> None:
        """Author with only one name uses 'literal'."""
        work = Work(
            title="Test",
            authors=[Author(name="Madonna")],
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert csl["author"] == [{"literal": "Madonna"}]

    def test_date_parts_full_date(self) -> None:
        """Full date produces [year, month, day] date-parts."""
        work = Work(
            title="Test",
            publication_date=date(2025, 6, 15),
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert csl["issued"]["date-parts"] == [[2025, 6, 15]]

    def test_date_parts_year_only(self) -> None:
        """Year-only produces [year] date-parts."""
        work = Work(
            title="Test",
            year=2025,
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert csl["issued"]["date-parts"] == [[2025]]

    def test_no_date(self) -> None:
        """No date or year means no 'issued' key."""
        work = Work(title="Test", sources=[Source.OPENALEX])
        csl = work_to_csl(work)
        assert "issued" not in csl

    def test_journal_article_type(self) -> None:
        """Journal article maps to article-journal."""
        work = Work(
            title="Test",
            work_type=WorkType.JOURNAL_ARTICLE,
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert csl["type"] == "article-journal"

    def test_conference_paper_type(self) -> None:
        """Conference paper maps to paper-conference."""
        work = Work(
            title="Test",
            work_type=WorkType.CONFERENCE_PAPER,
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert csl["type"] == "paper-conference"

    def test_venue_included(self) -> None:
        """Venue is included as container-title."""
        work = Work(
            title="Test",
            venue="Nature",
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert csl["container-title"] == "Nature"

    def test_no_venue(self) -> None:
        """Missing venue means no container-title."""
        work = Work(title="Test", sources=[Source.OPENALEX])
        csl = work_to_csl(work)
        assert "container-title" not in csl

    def test_abstract_included(self) -> None:
        """Abstract is included when present."""
        work = Work(
            title="Test",
            abstract="Summary here.",
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert csl["abstract"] == "Summary here."

    def test_url_included(self) -> None:
        """Open access URL is included."""
        work = Work(
            title="Test",
            open_access_url="https://example.com/paper.pdf",
            sources=[Source.OPENALEX],
        )
        csl = work_to_csl(work)
        assert csl["URL"] == "https://example.com/paper.pdf"


class TestWorksToCslJson:
    """Tests for works_to_csl_json()."""

    def test_empty_list(self) -> None:
        """Empty input returns empty list."""
        assert works_to_csl_json([]) == []

    def test_multiple_works(self) -> None:
        """Multiple works produce multiple CSL entries."""
        works = [
            Work(title="Paper A", sources=[Source.OPENALEX]),
            Work(title="Paper B", sources=[Source.OPENALEX]),
        ]
        result = works_to_csl_json(works)
        assert len(result) == 2
        assert result[0]["title"] == "Paper A"
        assert result[1]["title"] == "Paper B"
