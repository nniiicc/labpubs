"""Tests for the funding extension: models, store, dedup, and export."""

from datetime import date, datetime
from pathlib import Path

import orjson
import pytest

from labpubs.dedup import _merge_awards, _merge_funders, merge_works
from labpubs.export.grant_report import (
    export_grant_report,
    export_grant_report_csv,
    export_grant_report_json,
    export_grant_report_markdown,
)
from labpubs.models import (
    Author,
    Award,
    Funder,
    Investigator,
    Source,
    Work,
    WorkType,
)
from labpubs.sources.openalex import _parse_awards, _parse_funders
from labpubs.store import Store

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def nsf_funder() -> Funder:
    """National Science Foundation funder fixture."""
    return Funder(
        openalex_id="https://openalex.org/F4320306076",
        name="National Science Foundation",
        ror_id="https://ror.org/021nxhr62",
    )


@pytest.fixture
def nih_funder() -> Funder:
    """NIH funder fixture."""
    return Funder(
        openalex_id="https://openalex.org/F4320332161",
        name="National Institutes of Health",
    )


@pytest.fixture
def lead_pi() -> Investigator:
    """Lead PI investigator fixture."""
    return Investigator(
        given_name="Jane",
        family_name="Doe",
        orcid="https://orcid.org/0000-0002-1234-5678",
        affiliation_name="University of Washington",
        affiliation_country="US",
    )


@pytest.fixture
def nsf_award(nsf_funder: Funder, lead_pi: Investigator) -> Award:
    """NSF award fixture."""
    return Award(
        openalex_id="https://openalex.org/G5453342221",
        display_name="Human Networks and Data Science",
        funder_award_id="2043024",
        funder=nsf_funder,
        doi="https://doi.org/10.3030/2043024",
        amount=500_000,
        funding_type="grant",
        start_year=2024,
        lead_investigator=lead_pi,
        investigators=[lead_pi],
        funded_outputs_count=7,
    )


@pytest.fixture
def funded_work(
    nsf_funder: Funder, nsf_award: Award
) -> Work:
    """Work with funding data."""
    return Work(
        doi="10.1234/funded.2025",
        title="Computational Approaches to Federal Rulemaking",
        authors=[
            Author(name="Jane Doe", is_lab_member=True),
            Author(name="John Smith"),
        ],
        publication_date=date(2025, 6, 15),
        year=2025,
        venue="Journal of Policy Analysis",
        work_type=WorkType.JOURNAL_ARTICLE,
        awards=[nsf_award],
        funders=[nsf_funder],
        sources=[Source.OPENALEX],
        first_seen=datetime(2025, 7, 1),
    )


@pytest.fixture
def funded_store(tmp_path: Path) -> Store:
    """Store with funded work data pre-loaded."""
    db_path = tmp_path / "funding_test.db"
    store = Store(db_path)
    yield store
    store.close()


# ── Model Tests ───────────────────────────────────────────────────────


class TestFundingModels:
    """Tests for Funder, Investigator, and Award models."""

    def test_funder_creation(self, nsf_funder: Funder) -> None:
        """Funder model stores all fields."""
        assert nsf_funder.name == "National Science Foundation"
        assert nsf_funder.ror_id == "https://ror.org/021nxhr62"
        assert nsf_funder.alternate_names == []

    def test_funder_alternate_names(self) -> None:
        """Funder stores alternate name list."""
        f = Funder(
            openalex_id="F1",
            name="NSF",
            alternate_names=["National Science Foundation"],
        )
        assert len(f.alternate_names) == 1

    def test_investigator_creation(self, lead_pi: Investigator) -> None:
        """Investigator model stores all fields."""
        assert lead_pi.given_name == "Jane"
        assert lead_pi.family_name == "Doe"
        assert lead_pi.orcid is not None

    def test_award_creation(self, nsf_award: Award) -> None:
        """Award model stores all fields."""
        assert nsf_award.funder_award_id == "2043024"
        assert nsf_award.amount == 500_000
        assert nsf_award.funder is not None
        assert nsf_award.lead_investigator is not None
        assert len(nsf_award.investigators) == 1

    def test_work_with_funding(self, funded_work: Work) -> None:
        """Work model stores awards and funders."""
        assert len(funded_work.awards) == 1
        assert len(funded_work.funders) == 1
        assert (
            funded_work.awards[0].funder_award_id == "2043024"
        )


# ── Store Tests ───────────────────────────────────────────────────────


class TestFundingStore:
    """Tests for funding-related store operations."""

    def test_upsert_funder(
        self, funded_store: Store, nsf_funder: Funder
    ) -> None:
        """Upsert inserts a funder and returns its ID."""
        funder_id = funded_store.upsert_funder(nsf_funder)
        assert funder_id is not None
        assert funder_id > 0

    def test_upsert_funder_idempotent(
        self, funded_store: Store, nsf_funder: Funder
    ) -> None:
        """Upserting same funder twice returns same ID."""
        id1 = funded_store.upsert_funder(nsf_funder)
        id2 = funded_store.upsert_funder(nsf_funder)
        assert id1 == id2

    def test_upsert_award(
        self,
        funded_store: Store,
        nsf_award: Award,
        nsf_funder: Funder,
    ) -> None:
        """Upsert inserts an award and returns its ID."""
        funder_id = funded_store.upsert_funder(nsf_funder)
        award_id = funded_store.upsert_award(nsf_award, funder_id)
        assert award_id is not None
        assert award_id > 0

    def test_upsert_award_idempotent(
        self,
        funded_store: Store,
        nsf_award: Award,
        nsf_funder: Funder,
    ) -> None:
        """Upserting same award twice returns same ID."""
        funder_id = funded_store.upsert_funder(nsf_funder)
        id1 = funded_store.upsert_award(nsf_award, funder_id)
        id2 = funded_store.upsert_award(nsf_award, funder_id)
        assert id1 == id2

    def test_insert_work_persists_funding(
        self, funded_store: Store, funded_work: Work
    ) -> None:
        """Inserting a work persists its awards and funders."""
        work_id = funded_store.insert_work(funded_work)
        assert work_id > 0

        # Check awards were linked
        awards = funded_store._load_work_awards(work_id)
        assert len(awards) == 1
        assert awards[0].funder_award_id == "2043024"
        assert awards[0].funder is not None
        assert (
            awards[0].funder.name == "National Science Foundation"
        )

        # Check funders were linked
        funders = funded_store._load_work_funders(work_id)
        assert len(funders) == 1
        assert (
            funders[0].name == "National Science Foundation"
        )

    def test_hydrate_work_includes_funding(
        self, funded_store: Store, funded_work: Work
    ) -> None:
        """Hydrated work includes awards and funders."""
        funded_store.insert_work(funded_work)
        result = funded_store.find_work_by_doi(
            funded_work.doi
        )
        assert result is not None
        _, hydrated = result
        assert len(hydrated.awards) == 1
        assert len(hydrated.funders) == 1

    def test_get_works_by_funder(
        self, funded_store: Store, funded_work: Work
    ) -> None:
        """Query works by funder name."""
        funded_store.insert_work(funded_work)
        works = funded_store.get_works_by_funder("Science Foundation")
        assert len(works) == 1
        assert works[0].title == funded_work.title

    def test_get_works_by_funder_case_insensitive(
        self, funded_store: Store, funded_work: Work
    ) -> None:
        """Funder name search is case-insensitive."""
        funded_store.insert_work(funded_work)
        works = funded_store.get_works_by_funder("nsf")
        # Won't match "National Science Foundation" substring
        assert len(works) == 0
        works = funded_store.get_works_by_funder(
            "national science"
        )
        assert len(works) == 1

    def test_get_works_by_award(
        self, funded_store: Store, funded_work: Work
    ) -> None:
        """Query works by award/grant number."""
        funded_store.insert_work(funded_work)
        works = funded_store.get_works_by_award("2043024")
        assert len(works) == 1
        assert works[0].doi == funded_work.doi

    def test_get_all_funders(
        self, funded_store: Store, funded_work: Work
    ) -> None:
        """List all funders in the database."""
        funded_store.insert_work(funded_work)
        funders = funded_store.get_all_funders()
        assert len(funders) >= 1
        names = [f.name for f in funders]
        assert "National Science Foundation" in names

    def test_get_all_awards(
        self, funded_store: Store, funded_work: Work
    ) -> None:
        """List all awards in the database."""
        funded_store.insert_work(funded_work)
        awards = funded_store.get_all_awards()
        assert len(awards) == 1
        assert awards[0].funder_award_id == "2043024"

    def test_get_all_awards_filtered(
        self,
        funded_store: Store,
        funded_work: Work,
    ) -> None:
        """Filter awards by funder name."""
        funded_store.insert_work(funded_work)
        awards = funded_store.get_all_awards("Science")
        assert len(awards) == 1
        awards = funded_store.get_all_awards("nonexistent")
        assert len(awards) == 0

    def test_get_award_by_funder_award_id(
        self, funded_store: Store, funded_work: Work
    ) -> None:
        """Look up award by grant number."""
        funded_store.insert_work(funded_work)
        award = funded_store.get_award_by_funder_award_id(
            "2043024"
        )
        assert award is not None
        assert award.display_name == "Human Networks and Data Science"
        assert award.funder is not None

    def test_get_award_not_found(
        self, funded_store: Store
    ) -> None:
        """Missing award returns None."""
        assert (
            funded_store.get_award_by_funder_award_id("9999999")
            is None
        )

    def test_funder_publication_counts(
        self, funded_store: Store, funded_work: Work
    ) -> None:
        """Get funder publication counts."""
        funded_store.insert_work(funded_work)
        counts = funded_store.get_funder_publication_counts()
        assert len(counts) >= 1
        funder, count = counts[0]
        assert count >= 1
        assert funder.name == "National Science Foundation"

    def test_update_work_preserves_funding(
        self, funded_store: Store, funded_work: Work
    ) -> None:
        """Updating a work re-persists funding data."""
        work_id = funded_store.insert_work(funded_work)
        funded_work_copy = funded_work.model_copy(
            update={"citation_count": 99}
        )
        funded_store.update_work(work_id, funded_work_copy)

        awards = funded_store._load_work_awards(work_id)
        assert len(awards) == 1
        funders = funded_store._load_work_funders(work_id)
        assert len(funders) == 1

    def test_award_investigators_persisted(
        self,
        funded_store: Store,
        nsf_award: Award,
        nsf_funder: Funder,
    ) -> None:
        """Award investigators are stored and loaded."""
        funder_id = funded_store.upsert_funder(nsf_funder)
        award_id = funded_store.upsert_award(
            nsf_award, funder_id
        )
        investigators = funded_store._load_award_investigators(
            award_id
        )
        assert len(investigators) == 1
        assert investigators[0].given_name == "Jane"
        assert investigators[0].family_name == "Doe"


# ── Dedup Merge Tests ─────────────────────────────────────────────────


class TestFundingDedup:
    """Tests for funding data deduplication/merging."""

    def test_merge_awards_union(self) -> None:
        """Merge combines awards by openalex_id."""
        a1 = Award(
            openalex_id="G1", display_name="Award 1"
        )
        a2 = Award(
            openalex_id="G2", display_name="Award 2"
        )
        a3 = Award(
            openalex_id="G1", display_name="Award 1 updated"
        )

        merged = _merge_awards([a1], [a2, a3])
        assert len(merged) == 2
        ids = {a.openalex_id for a in merged}
        assert ids == {"G1", "G2"}
        # Existing takes precedence
        g1 = next(a for a in merged if a.openalex_id == "G1")
        assert g1.display_name == "Award 1"

    def test_merge_funders_union(self) -> None:
        """Merge combines funders by openalex_id."""
        f1 = Funder(openalex_id="F1", name="NSF")
        f2 = Funder(openalex_id="F2", name="NIH")
        f3 = Funder(openalex_id="F1", name="NSF updated")

        merged = _merge_funders([f1], [f2, f3])
        assert len(merged) == 2
        ids = {f.openalex_id for f in merged}
        assert ids == {"F1", "F2"}

    def test_merge_works_includes_funding(self) -> None:
        """merge_works combines awards and funders."""
        funder1 = Funder(openalex_id="F1", name="NSF")
        funder2 = Funder(openalex_id="F2", name="NIH")
        award1 = Award(openalex_id="G1", funder=funder1)
        award2 = Award(openalex_id="G2", funder=funder2)

        existing = Work(
            title="Test Paper",
            doi="10.1/test",
            year=2025,
            awards=[award1],
            funders=[funder1],
            sources=[Source.OPENALEX],
        )
        new = Work(
            title="Test Paper",
            doi="10.1/test",
            year=2025,
            awards=[award2],
            funders=[funder2],
            sources=[Source.SEMANTIC_SCHOLAR],
        )

        merged = merge_works(existing, new)
        assert len(merged.awards) == 2
        assert len(merged.funders) == 2

    def test_merge_empty_awards(self) -> None:
        """Merging empty and non-empty awards works."""
        a = Award(openalex_id="G1", display_name="Test")
        assert _merge_awards([], [a]) == [a]
        assert _merge_awards([a], []) == [a]
        assert _merge_awards([], []) == []


# ── OpenAlex Parsing Tests ────────────────────────────────────────────


class TestOpenAlexFundingParsing:
    """Tests for parsing OpenAlex funding data."""

    def test_parse_awards(self) -> None:
        """Parse raw OpenAlex award dicts."""
        raw = [
            {
                "id": "https://openalex.org/G123",
                "display_name": "Test Award",
                "funder_award_id": "2043024",
                "funder_id": "https://openalex.org/F999",
                "funder_display_name": "NSF",
                "doi": "https://doi.org/10.3030/2043024",
            }
        ]
        awards = _parse_awards(raw)
        assert len(awards) == 1
        assert awards[0].openalex_id == "https://openalex.org/G123"
        assert awards[0].funder_award_id == "2043024"
        assert awards[0].funder is not None
        assert awards[0].funder.name == "NSF"

    def test_parse_awards_skips_missing_id(self) -> None:
        """Awards without an ID are skipped."""
        raw = [{"display_name": "No ID Award"}]
        assert _parse_awards(raw) == []

    def test_parse_funders(self) -> None:
        """Parse raw OpenAlex funder dicts."""
        raw = [
            {
                "id": "https://openalex.org/F123",
                "display_name": "NIH",
                "ror": "https://ror.org/01cwqze88",
            }
        ]
        funders = _parse_funders(raw)
        assert len(funders) == 1
        assert funders[0].name == "NIH"
        assert funders[0].ror_id == "https://ror.org/01cwqze88"

    def test_parse_funders_skips_missing_fields(self) -> None:
        """Funders without id or name are skipped."""
        raw = [{"id": "F1"}]  # missing display_name
        assert _parse_funders(raw) == []
        raw = [{"display_name": "Test"}]  # missing id
        assert _parse_funders(raw) == []


# ── Grant Report Export Tests ─────────────────────────────────────────


class TestGrantReportExport:
    """Tests for grant report generation."""

    @pytest.fixture
    def report_works(self) -> list[Work]:
        """Sample works for report testing."""
        return [
            Work(
                title="Paper One",
                doi="10.1/one",
                year=2025,
                venue="Journal A",
                authors=[
                    Author(name="Jane Doe"),
                    Author(name="John Smith"),
                ],
            ),
            Work(
                title="Paper Two",
                year=2024,
                venue="Conference B",
                authors=[Author(name="Jane Doe")],
            ),
        ]

    @pytest.fixture
    def report_award(self) -> Award:
        """Award for report header."""
        return Award(
            openalex_id="G1",
            display_name="Human Networks and Data Science",
            funder_award_id="2043024",
            funder=Funder(
                openalex_id="F1",
                name="National Science Foundation",
            ),
            start_year=2024,
            lead_investigator=Investigator(
                given_name="Jane",
                family_name="Doe",
                orcid="0000-0002-1234-5678",
            ),
        )

    def test_markdown_with_award(
        self,
        report_works: list[Work],
        report_award: Award,
    ) -> None:
        """Markdown report includes award header and publications."""
        report = export_grant_report_markdown(
            report_works, report_award
        )
        assert "# Grant Report:" in report
        assert "2043024" in report
        assert "National Science Foundation" in report
        assert "Paper One" in report
        assert "Paper Two" in report
        assert "Jane Doe" in report

    def test_markdown_without_award(
        self, report_works: list[Work]
    ) -> None:
        """Markdown report without award uses funder name header."""
        report = export_grant_report_markdown(
            report_works, funder_name="NSF"
        )
        assert "# Grant Report: NSF" in report
        assert "**Publications:** 2" in report

    def test_markdown_includes_abstract(
        self, report_works: list[Work]
    ) -> None:
        """Markdown report with abstracts."""
        report_works[0].abstract = "Test abstract content."
        report = export_grant_report_markdown(
            report_works, include_abstract=True
        )
        assert "Test abstract content." in report

    def test_json_report(
        self,
        report_works: list[Work],
        report_award: Award,
    ) -> None:
        """JSON report is valid and contains expected data."""
        report = export_grant_report_json(
            report_works, report_award
        )
        data = orjson.loads(report)
        assert data["publication_count"] == 2
        assert data["funder"] == "National Science Foundation"
        assert "award" in data

    def test_csv_report(
        self, report_works: list[Work]
    ) -> None:
        """CSV report has header and correct row count."""
        report = export_grant_report_csv(report_works)
        lines = report.strip().split("\n")
        assert lines[0] == "title,year,venue,doi,authors"
        assert len(lines) == 3  # header + 2 works

    def test_export_dispatch(
        self, report_works: list[Work]
    ) -> None:
        """export_grant_report dispatches to correct format."""
        md = export_grant_report(
            report_works, report_format="markdown"
        )
        assert "# Grant Report" in md

        json_str = export_grant_report(
            report_works, report_format="json"
        )
        data = orjson.loads(json_str)
        assert "publication_count" in data

        csv_str = export_grant_report(
            report_works, report_format="csv"
        )
        assert csv_str.startswith("title,year")

    def test_export_invalid_format(
        self, report_works: list[Work]
    ) -> None:
        """Invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported"):
            export_grant_report(
                report_works, report_format="xml"
            )
