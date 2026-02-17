"""Tests for Semantic Scholar paper-to-model conversion."""

from datetime import date
from types import SimpleNamespace

from labpubs.models import Source, WorkType
from labpubs.sources.semantic_scholar import _s2_paper_to_model


def _make_paper(**overrides):
    """Build a mock S2 paper object with sensible defaults."""
    defaults = {
        "title": "Test Paper",
        "authors": [
            SimpleNamespace(name="Jane Doe", authorId="12345"),
        ],
        "publicationDate": date(2025, 6, 15),
        "year": 2025,
        "venue": "NeurIPS",
        "journal": None,
        "publicationTypes": ["JournalArticle"],
        "externalIds": {"DOI": "10.1234/test"},
        "abstract": "This paper studies things.",
        "isOpenAccess": True,
        "openAccessPdf": {"url": "https://example.com/paper.pdf"},
        "citationCount": 42,
        "paperId": "abc123def456",
        "tldr": SimpleNamespace(text="A paper about things."),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestS2PaperToModel:
    """Tests for _s2_paper_to_model()."""

    def test_complete_paper(self) -> None:
        """All fields are populated from a complete paper."""
        paper = _make_paper()
        work = _s2_paper_to_model(paper)

        assert work.doi == "10.1234/test"
        assert work.title == "Test Paper"
        assert work.year == 2025
        assert work.publication_date == date(2025, 6, 15)
        assert work.work_type == WorkType.JOURNAL_ARTICLE
        assert work.semantic_scholar_id == "abc123def456"
        assert work.open_access is True
        assert work.open_access_url == "https://example.com/paper.pdf"
        assert work.citation_count == 42
        assert work.venue == "NeurIPS"
        assert work.abstract == "This paper studies things."
        assert work.tldr == "A paper about things."
        assert Source.SEMANTIC_SCHOLAR in work.sources

    def test_author_fields(self) -> None:
        """Author name and S2 ID are extracted."""
        paper = _make_paper()
        work = _s2_paper_to_model(paper)

        assert len(work.authors) == 1
        assert work.authors[0].name == "Jane Doe"
        assert work.authors[0].semantic_scholar_id == "12345"

    def test_multiple_authors(self) -> None:
        """Multiple authors are all parsed."""
        paper = _make_paper(
            authors=[
                SimpleNamespace(name="Alice", authorId="1"),
                SimpleNamespace(name="Bob", authorId="2"),
            ]
        )
        work = _s2_paper_to_model(paper)
        assert len(work.authors) == 2
        assert work.authors[0].name == "Alice"
        assert work.authors[1].name == "Bob"

    def test_no_authors(self) -> None:
        """None authors produces empty list."""
        paper = _make_paper(authors=None)
        work = _s2_paper_to_model(paper)
        assert work.authors == []

    def test_minimal_paper(self) -> None:
        """Minimal paper object with only title."""
        paper = SimpleNamespace(title="Minimal")
        work = _s2_paper_to_model(paper)

        assert work.title == "Minimal"
        assert work.doi is None
        assert work.year is None
        assert work.publication_date is None
        assert work.work_type == WorkType.OTHER
        assert work.authors == []
        assert Source.SEMANTIC_SCHOLAR in work.sources

    def test_doi_lowercased(self) -> None:
        """DOI is lowercased."""
        paper = _make_paper(externalIds={"DOI": "10.5555/UPPER"})
        work = _s2_paper_to_model(paper)
        assert work.doi == "10.5555/upper"

    def test_doi_none_when_no_external_ids(self) -> None:
        """No DOI when externalIds is missing."""
        paper = _make_paper(externalIds=None)
        work = _s2_paper_to_model(paper)
        assert work.doi is None

    def test_doi_none_when_no_doi_key(self) -> None:
        """No DOI when externalIds has no DOI key."""
        paper = _make_paper(externalIds={"ArXiv": "1234.5678"})
        work = _s2_paper_to_model(paper)
        assert work.doi is None

    def test_publication_date_string(self) -> None:
        """String date is parsed correctly."""
        paper = _make_paper(publicationDate="2024-03-20")
        work = _s2_paper_to_model(paper)
        assert work.publication_date == date(2024, 3, 20)
        assert work.year == 2024

    def test_publication_date_invalid_string(self) -> None:
        """Invalid date string falls back to year field."""
        paper = _make_paper(publicationDate="bad-date", year=2023)
        work = _s2_paper_to_model(paper)
        assert work.publication_date is None
        assert work.year == 2023

    def test_no_date_uses_year(self) -> None:
        """When no publicationDate, year field is used."""
        paper = _make_paper(publicationDate=None, year=2022)
        work = _s2_paper_to_model(paper)
        assert work.publication_date is None
        assert work.year == 2022

    def test_conference_type(self) -> None:
        """Conference type maps correctly."""
        paper = _make_paper(publicationTypes=["Conference"])
        work = _s2_paper_to_model(paper)
        assert work.work_type == WorkType.CONFERENCE_PAPER

    def test_unknown_type(self) -> None:
        """Unknown type falls back to OTHER."""
        paper = _make_paper(publicationTypes=["Editorial"])
        work = _s2_paper_to_model(paper)
        assert work.work_type == WorkType.OTHER

    def test_no_publication_types(self) -> None:
        """None publicationTypes falls back to OTHER."""
        paper = _make_paper(publicationTypes=None)
        work = _s2_paper_to_model(paper)
        assert work.work_type == WorkType.OTHER

    def test_first_matching_type_wins(self) -> None:
        """When multiple types, first match is used."""
        paper = _make_paper(
            publicationTypes=["Review", "JournalArticle"]
        )
        work = _s2_paper_to_model(paper)
        assert work.work_type == WorkType.JOURNAL_ARTICLE

    def test_tldr_as_dict(self) -> None:
        """TLDR as dict with text key."""
        paper = _make_paper(tldr={"text": "Summary text."})
        work = _s2_paper_to_model(paper)
        assert work.tldr == "Summary text."

    def test_tldr_none(self) -> None:
        """None TLDR produces None."""
        paper = _make_paper(tldr=None)
        work = _s2_paper_to_model(paper)
        assert work.tldr is None

    def test_venue_from_journal_object(self) -> None:
        """Venue extracted from journal object with name attr."""
        paper = _make_paper(
            venue=None,
            journal=SimpleNamespace(name="JMLR"),
        )
        work = _s2_paper_to_model(paper)
        assert work.venue == "JMLR"

    def test_venue_string(self) -> None:
        """Venue as plain string."""
        paper = _make_paper(venue="ICML 2025", journal=None)
        work = _s2_paper_to_model(paper)
        assert work.venue == "ICML 2025"

    def test_no_open_access_pdf(self) -> None:
        """None openAccessPdf results in None URL."""
        paper = _make_paper(openAccessPdf=None)
        work = _s2_paper_to_model(paper)
        assert work.open_access_url is None

    def test_title_none_defaults(self) -> None:
        """None title defaults to 'Untitled'."""
        paper = _make_paper(title=None)
        work = _s2_paper_to_model(paper)
        assert work.title == "Untitled"
