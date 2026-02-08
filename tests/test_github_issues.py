"""Tests for GitHub issues integration."""

from datetime import date, datetime
from pathlib import Path

import pytest

from labpubs.config import (
    GitHubIntegrationConfig,
    GitHubLabelsConfig,
)
from labpubs.github_issues import (
    enrichments_to_linked_resources,
    extract_publication_id,
    get_issue_assignees,
    get_issue_labels,
    parse_issue_enrichments,
    render_issue_body,
    render_issue_title,
)
from labpubs.models import (
    Author,
    LinkedResource,
    Source,
    Work,
    WorkType,
)
from labpubs.store import Store

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def gh_config() -> GitHubIntegrationConfig:
    """GitHub integration config fixture."""
    return GitHubIntegrationConfig(
        repo="mylab/publications",
        author_github_map={
            "Jane Doe": "janedoe",
            "John Smith": "jsmith42",
        },
        labels=GitHubLabelsConfig(),
        year_labels=True,
        author_labels=True,
    )


@pytest.fixture
def review_work() -> Work:
    """Work fixture for verification testing."""
    return Work(
        doi="10.1234/example.2025",
        title="Computational Approaches to Federal Rulemaking",
        authors=[
            Author(
                name="Jane Doe",
                openalex_id="A5023888391",
                is_lab_member=True,
            ),
            Author(name="John Smith"),
            Author(name="Alice Johnson"),
        ],
        publication_date=date(2025, 6, 15),
        year=2025,
        venue="Journal of Policy Analysis",
        work_type=WorkType.JOURNAL_ARTICLE,
        abstract="This paper examines computational methods...",
        openalex_id="W1234567890",
        open_access=True,
        open_access_url="https://example.com/paper.pdf",
        citation_count=42,
        sources=[Source.OPENALEX],
        first_seen=datetime(2025, 7, 1, 12, 0, 0),
    )


@pytest.fixture
def gh_store(tmp_path: Path) -> Store:
    """Temporary Store for GitHub issues tests."""
    db_path = tmp_path / "gh_test.db"
    store = Store(db_path)
    yield store
    store.close()


# ── Model Tests ───────────────────────────────────────────────────────


class TestLinkedResourceModel:
    """Tests for LinkedResource model."""

    def test_create_code_resource(self) -> None:
        """Code resource can be created."""
        res = LinkedResource(
            url="https://github.com/mylab/analysis",
            resource_type="code",
        )
        assert res.url == "https://github.com/mylab/analysis"
        assert res.resource_type == "code"
        assert res.name is None

    def test_create_dataset_resource(self) -> None:
        """Dataset resource with all fields."""
        res = LinkedResource(
            url="https://zenodo.org/record/123",
            resource_type="dataset",
            name="Survey Data",
            description="Raw survey responses",
        )
        assert res.resource_type == "dataset"
        assert res.name == "Survey Data"


class TestWorkVerificationFields:
    """Tests for Work verification defaults."""

    def test_defaults(self) -> None:
        """Work has correct verification defaults."""
        w = Work(title="Test")
        assert w.verified is False
        assert w.verified_by is None
        assert w.verified_at is None
        assert w.verification_issue_url is None
        assert w.notes is None
        assert w.linked_resources == []


# ── Issue Template Tests ──────────────────────────────────────────────


class TestIssueTemplate:
    """Tests for issue rendering functions."""

    def test_render_title(self, review_work: Work) -> None:
        """Issue title includes paper title."""
        title = render_issue_title(review_work)
        assert title == (
            "New publication: Computational Approaches "
            "to Federal Rulemaking"
        )

    def test_render_body_contains_metadata(
        self, review_work: Work, gh_config: GitHubIntegrationConfig
    ) -> None:
        """Issue body has metadata sections."""
        body = render_issue_body(review_work, gh_config)
        assert "**Title:** Computational" in body
        assert "**Authors:** Jane Doe, John Smith" in body
        assert "**Venue:** Journal of Policy Analysis" in body
        assert "**Year:** 2025" in body
        assert "10.1234/example.2025" in body

    def test_render_body_contains_checklist(
        self, review_work: Work, gh_config: GitHubIntegrationConfig
    ) -> None:
        """Issue body includes verification checklist."""
        body = render_issue_body(review_work, gh_config)
        assert "- [ ] Metadata is correct" in body
        assert "- [ ] This is actually a lab publication" in body
        assert "- [ ] Not a duplicate" in body

    def test_render_body_contains_resource_sections(
        self, review_work: Work, gh_config: GitHubIntegrationConfig
    ) -> None:
        """Issue body has resource placeholders."""
        body = render_issue_body(review_work, gh_config)
        assert "**Code repositories:**" in body
        assert "**Datasets:**" in body
        assert "**Other resources:**" in body

    def test_render_body_contains_publication_id(
        self, review_work: Work, gh_config: GitHubIntegrationConfig
    ) -> None:
        """Issue body has hidden publication ID comment."""
        body = render_issue_body(review_work, gh_config)
        assert "<!-- labpubs:publication_id:" in body
        assert "W1234567890" in body

    def test_render_body_contains_raw_json(
        self, review_work: Work, gh_config: GitHubIntegrationConfig
    ) -> None:
        """Issue body has raw metadata details section."""
        body = render_issue_body(review_work, gh_config)
        assert "Raw metadata (for debugging)" in body
        assert '"doi"' in body

    def test_get_labels(
        self, review_work: Work, gh_config: GitHubIntegrationConfig
    ) -> None:
        """Labels include needs-review, author, year."""
        labels = get_issue_labels(review_work, gh_config)
        assert "needs-review" in labels
        assert "author-jane-doe" in labels
        assert "2025" in labels

    def test_get_labels_no_author_labels(
        self, review_work: Work, gh_config: GitHubIntegrationConfig
    ) -> None:
        """Author labels omitted when disabled."""
        gh_config.author_labels = False
        labels = get_issue_labels(review_work, gh_config)
        assert not any(
            lbl.startswith("author-") for lbl in labels
        )

    def test_get_labels_no_year_labels(
        self, review_work: Work, gh_config: GitHubIntegrationConfig
    ) -> None:
        """Year labels omitted when disabled."""
        gh_config.year_labels = False
        labels = get_issue_labels(review_work, gh_config)
        assert "2025" not in labels

    def test_get_assignees(
        self, review_work: Work, gh_config: GitHubIntegrationConfig
    ) -> None:
        """Assignees mapped from author names."""
        assignees = get_issue_assignees(review_work, gh_config)
        assert "janedoe" in assignees
        assert "jsmith42" in assignees
        # Alice Johnson not in map
        assert len(assignees) == 2

    def test_get_assignees_no_mapping(
        self, review_work: Work, gh_config: GitHubIntegrationConfig
    ) -> None:
        """No assignees when map is empty."""
        gh_config.author_github_map = {}
        assignees = get_issue_assignees(review_work, gh_config)
        assert assignees == []


# ── Enrichment Parsing Tests ─────────────────────────────────────────


class TestEnrichmentParsing:
    """Tests for parsing enrichments from closed issues."""

    def test_extract_publication_id(self) -> None:
        """Publication ID extracted from hidden comment."""
        body = "some text\n<!-- labpubs:publication_id:W1234567890 -->\n"
        assert extract_publication_id(body) == "W1234567890"

    def test_extract_publication_id_missing(self) -> None:
        """None when no publication ID comment."""
        assert extract_publication_id("no comment here") is None

    def test_parse_code_repos(self) -> None:
        """GitHub URLs extracted from code section."""
        body = """## Associated Resources

**Code repositories:**
https://github.com/mylab/analysis-code
https://github.com/mylab/data-pipeline

**Datasets:**

**Other resources:**

---
"""
        enrichments = parse_issue_enrichments(body)
        assert len(enrichments["code_repos"]) == 2
        assert (
            "https://github.com/mylab/analysis-code"
            in enrichments["code_repos"]
        )

    def test_parse_datasets(self) -> None:
        """Dataset URLs extracted from datasets section."""
        body = """## Associated Resources

**Code repositories:**

**Datasets:**
https://zenodo.org/record/12345
https://osf.io/abcde

**Other resources:**

---
"""
        enrichments = parse_issue_enrichments(body)
        assert len(enrichments["datasets"]) == 2
        assert (
            "https://zenodo.org/record/12345"
            in enrichments["datasets"]
        )

    def test_parse_empty_sections(self) -> None:
        """Empty sections return empty lists."""
        body = """## Associated Resources

**Code repositories:**
<!-- Add GitHub/GitLab links, one per line -->

**Datasets:**
<!-- Add Zenodo/OSF/Dataverse links, one per line -->

**Other resources:**
<!-- Slides, videos, blog posts, etc. -->

---
"""
        enrichments = parse_issue_enrichments(body)
        assert enrichments["code_repos"] == []
        assert enrichments["datasets"] == []
        assert enrichments["other_resources"] == []

    def test_parse_not_lab_paper(self) -> None:
        """is_valid False when lab publication unchecked."""
        body = """## Verification Checklist

- [x] Metadata is correct (title, authors, venue, year)
- [ ] This is actually a lab publication (not a disambiguation error)
- [x] Not a duplicate of an existing entry
"""
        enrichments = parse_issue_enrichments(body)
        assert enrichments["is_valid"] is False

    def test_parse_verified(self) -> None:
        """verified True when metadata box checked."""
        body = """## Verification Checklist

- [x] Metadata is correct (title, authors, venue, year)
- [x] This is actually a lab publication (not a disambiguation error)
- [x] Not a duplicate of an existing entry
"""
        enrichments = parse_issue_enrichments(body)
        assert enrichments["verified"] is True
        assert enrichments["is_valid"] is True

    def test_parse_notes(self) -> None:
        """Notes extracted from notes section."""
        body = """## Notes

This paper was a collaboration with the other lab.
The analysis used their HPC cluster.

---

<details>
"""
        enrichments = parse_issue_enrichments(body)
        assert enrichments["notes"] is not None
        assert "collaboration" in enrichments["notes"]

    def test_enrichments_to_linked_resources(self) -> None:
        """Enrichments dict converted to LinkedResource list."""
        enrichments = {
            "code_repos": [
                "https://github.com/mylab/analysis"
            ],
            "datasets": ["https://zenodo.org/record/123"],
            "other_resources": [
                "https://example.com/slides.pdf"
            ],
        }
        resources = enrichments_to_linked_resources(enrichments)
        assert len(resources) == 3
        assert resources[0].resource_type == "code"
        assert resources[1].resource_type == "dataset"
        assert resources[2].resource_type == "other"

    def test_parse_gitlab_url(self) -> None:
        """GitLab URLs recognized as code repos."""
        body = """## Associated Resources

**Code repositories:**
https://gitlab.com/mylab/toolkit

**Datasets:**

**Other resources:**

---
"""
        enrichments = parse_issue_enrichments(body)
        assert len(enrichments["code_repos"]) == 1
        assert "gitlab.com" in enrichments["code_repos"][0]


# ── Store Tests ───────────────────────────────────────────────────────


class TestStoreVerification:
    """Tests for Store verification and linked resource methods."""

    def test_insert_and_hydrate_linked_resources(
        self, gh_store: Store, review_work: Work
    ) -> None:
        """Linked resources persisted and hydrated."""
        review_work.linked_resources = [
            LinkedResource(
                url="https://github.com/mylab/code",
                resource_type="code",
            ),
            LinkedResource(
                url="https://zenodo.org/record/123",
                resource_type="dataset",
                name="Survey Data",
            ),
        ]
        gh_store.insert_work(review_work)
        result = gh_store.find_work_by_doi(review_work.doi)
        assert result is not None
        _, hydrated = result
        assert len(hydrated.linked_resources) == 2
        assert hydrated.linked_resources[0].resource_type == "code"
        assert hydrated.linked_resources[1].name == "Survey Data"

    def test_verification_fields_roundtrip(
        self, gh_store: Store, review_work: Work
    ) -> None:
        """Verification fields stored and retrieved."""
        review_work.verified = True
        review_work.verified_by = "janedoe"
        review_work.verified_at = datetime(2025, 8, 1, 10, 0, 0)
        review_work.verification_issue_url = (
            "https://github.com/mylab/pubs/issues/1"
        )
        review_work.notes = "Confirmed correct"
        gh_store.insert_work(review_work)

        result = gh_store.find_work_by_doi(review_work.doi)
        assert result is not None
        _, hydrated = result
        assert hydrated.verified is True
        assert hydrated.verified_by == "janedoe"
        assert hydrated.verification_issue_url == (
            "https://github.com/mylab/pubs/issues/1"
        )
        assert hydrated.notes == "Confirmed correct"

    def test_get_unverified_works(
        self, gh_store: Store, review_work: Work
    ) -> None:
        """Unverified works returned correctly."""
        gh_store.insert_work(review_work)
        unverified = gh_store.get_unverified_works()
        assert len(unverified) == 1

        # Verify the work
        result = gh_store.find_work_by_doi(review_work.doi)
        assert result is not None
        work_id, _ = result
        gh_store.mark_work_verified(work_id, verified_by="user")
        unverified = gh_store.get_unverified_works()
        assert len(unverified) == 0

    def test_get_works_with_code(
        self, gh_store: Store, review_work: Work
    ) -> None:
        """Works with code repos found."""
        review_work.linked_resources = [
            LinkedResource(
                url="https://github.com/mylab/code",
                resource_type="code",
            ),
        ]
        gh_store.insert_work(review_work)
        code_works = gh_store.get_works_with_code()
        assert len(code_works) == 1
        assert code_works[0].title == review_work.title

    def test_get_works_with_data(
        self, gh_store: Store, review_work: Work
    ) -> None:
        """Works with datasets found."""
        review_work.linked_resources = [
            LinkedResource(
                url="https://zenodo.org/record/123",
                resource_type="dataset",
            ),
        ]
        gh_store.insert_work(review_work)
        data_works = gh_store.get_works_with_data()
        assert len(data_works) == 1

    def test_get_works_no_linked_resources(
        self, gh_store: Store, review_work: Work
    ) -> None:
        """No code/data works when none linked."""
        gh_store.insert_work(review_work)
        assert gh_store.get_works_with_code() == []
        assert gh_store.get_works_with_data() == []

    def test_mark_work_verified(
        self, gh_store: Store, review_work: Work
    ) -> None:
        """mark_work_verified updates fields."""
        work_id = gh_store.insert_work(review_work)
        gh_store.mark_work_verified(
            work_id,
            verified_by="janedoe",
            issue_url="https://github.com/mylab/pubs/issues/1",
            notes="All good",
        )
        result = gh_store.find_work_by_doi(review_work.doi)
        assert result is not None
        _, hydrated = result
        assert hydrated.verified is True
        assert hydrated.verified_by == "janedoe"
        assert hydrated.notes == "All good"

    def test_mark_work_unverified(
        self, gh_store: Store, review_work: Work
    ) -> None:
        """mark_work_unverified resets status."""
        work_id = gh_store.insert_work(review_work)
        gh_store.mark_work_verified(work_id, verified_by="user")

        result = gh_store.find_work_by_doi(review_work.doi)
        assert result is not None
        _, hydrated = result
        assert hydrated.verified is True

        gh_store.mark_work_unverified(work_id)
        result = gh_store.find_work_by_doi(review_work.doi)
        assert result is not None
        _, hydrated = result
        assert hydrated.verified is False
        assert hydrated.verified_by is None

    def test_add_linked_resource(
        self, gh_store: Store, review_work: Work
    ) -> None:
        """Individual linked resource can be added."""
        work_id = gh_store.insert_work(review_work)
        res = LinkedResource(
            url="https://github.com/mylab/new-code",
            resource_type="code",
        )
        gh_store.add_linked_resource(
            work_id, res, added_by="janedoe"
        )
        result = gh_store.find_work_by_doi(review_work.doi)
        assert result is not None
        _, hydrated = result
        assert len(hydrated.linked_resources) == 1
        assert (
            hydrated.linked_resources[0].url
            == "https://github.com/mylab/new-code"
        )

    def test_find_work_by_openalex_id(
        self, gh_store: Store, review_work: Work
    ) -> None:
        """Work found by OpenAlex ID."""
        gh_store.insert_work(review_work)
        result = gh_store.find_work_by_openalex_id(
            "W1234567890"
        )
        assert result is not None
        _, hydrated = result
        assert hydrated.title == review_work.title

    def test_verification_stats(
        self, gh_store: Store, review_work: Work
    ) -> None:
        """Verification stats computed correctly."""
        work_id = gh_store.insert_work(review_work)
        stats = gh_store.get_verification_stats()
        assert stats["total"] == 1
        assert stats["unverified"] == 1
        assert stats["verified"] == 0
        assert stats["has_code"] == 0

        gh_store.mark_work_verified(work_id)
        gh_store.add_linked_resource(
            work_id,
            LinkedResource(
                url="https://github.com/mylab/code",
                resource_type="code",
            ),
        )
        stats = gh_store.get_verification_stats()
        assert stats["verified"] == 1
        assert stats["has_code"] == 1

    def test_update_work_preserves_linked_resources(
        self, gh_store: Store, review_work: Work
    ) -> None:
        """update_work replaces linked resources."""
        review_work.linked_resources = [
            LinkedResource(
                url="https://github.com/old",
                resource_type="code",
            ),
        ]
        work_id = gh_store.insert_work(review_work)

        review_work.linked_resources = [
            LinkedResource(
                url="https://github.com/new",
                resource_type="code",
            ),
            LinkedResource(
                url="https://zenodo.org/record/456",
                resource_type="dataset",
            ),
        ]
        gh_store.update_work(work_id, review_work)

        result = gh_store.find_work_by_doi(review_work.doi)
        assert result is not None
        _, hydrated = result
        assert len(hydrated.linked_resources) == 2
        assert hydrated.linked_resources[0].url == (
            "https://github.com/new"
        )
