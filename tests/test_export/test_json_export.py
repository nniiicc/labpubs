"""Tests for native JSON export."""

from datetime import date

from labpubs.export.json_export import works_to_json
from labpubs.models import Author, Source, Work, WorkType


class TestWorksToJson:
    """Tests for works_to_json()."""

    def test_empty_list(self) -> None:
        """Empty input returns empty list."""
        assert works_to_json([]) == []

    def test_returns_dicts(self) -> None:
        """Each work is exported as a dict."""
        works = [Work(title="Test", sources=[Source.OPENALEX])]
        result = works_to_json(works)
        assert len(result) == 1
        assert isinstance(result[0], dict)

    def test_contains_expected_keys(self) -> None:
        """Exported dict has standard Work field keys."""
        work = Work(
            title="Test Paper",
            doi="10.1234/test",
            year=2025,
            sources=[Source.OPENALEX],
        )
        result = works_to_json([work])[0]
        assert result["title"] == "Test Paper"
        assert result["doi"] == "10.1234/test"
        assert result["year"] == 2025
        assert "openalex" in result["sources"]

    def test_author_serialization(self) -> None:
        """Authors are serialized correctly."""
        work = Work(
            title="Test",
            authors=[
                Author(name="Jane Doe", orcid="0000-0001-2345-6789")
            ],
            sources=[Source.OPENALEX],
        )
        result = works_to_json([work])[0]
        assert len(result["authors"]) == 1
        assert result["authors"][0]["name"] == "Jane Doe"
        assert result["authors"][0]["orcid"] == "0000-0001-2345-6789"

    def test_date_serialization(self) -> None:
        """Dates are serialized as ISO strings."""
        work = Work(
            title="Test",
            publication_date=date(2025, 6, 15),
            sources=[Source.OPENALEX],
        )
        result = works_to_json([work])[0]
        assert result["publication_date"] == "2025-06-15"

    def test_work_type_serialization(self) -> None:
        """WorkType enum is serialized as string value."""
        work = Work(
            title="Test",
            work_type=WorkType.JOURNAL_ARTICLE,
            sources=[Source.OPENALEX],
        )
        result = works_to_json([work])[0]
        assert result["work_type"] == "journal-article"

    def test_multiple_works(self) -> None:
        """Multiple works are all exported."""
        works = [
            Work(title="Paper A", sources=[Source.OPENALEX]),
            Work(title="Paper B", sources=[Source.CROSSREF]),
        ]
        result = works_to_json(works)
        assert len(result) == 2

    def test_none_fields_included(self) -> None:
        """None fields are present in the output."""
        work = Work(title="Test", sources=[Source.OPENALEX])
        result = works_to_json([work])[0]
        assert result["doi"] is None
        assert result["abstract"] is None
