"""Tests for Semantic Scholar multi-profile resolution during sync."""

import asyncio
import logging
from unittest.mock import MagicMock

from labpubs.sources.semantic_scholar import SemanticScholarBackend


def _make_mock_paper(
    paper_id: str,
    title: str,
    pub_date: str = "2026-01-15",
) -> MagicMock:
    """Create a mock S2 paper object."""
    paper = MagicMock()
    paper.paperId = paper_id
    paper.title = title
    paper.authors = []
    paper.publicationDate = pub_date
    paper.year = int(pub_date[:4])
    paper.publicationTypes = ["JournalArticle"]
    paper.externalIds = {"DOI": f"10.1234/{paper_id}"}
    paper.venue = "Test Venue"
    paper.journal = None
    paper.abstract = None
    paper.isOpenAccess = False
    paper.openAccessPdf = None
    paper.citationCount = 0
    paper.tldr = None
    return paper


def _run(coro):
    """Run an async function synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestResolveAndFetchWorks:
    """Tests for SemanticScholarBackend.resolve_and_fetch_works."""

    def setup_method(self):
        self.backend = SemanticScholarBackend.__new__(
            SemanticScholarBackend
        )
        self.backend._client = MagicMock()

    def test_stored_id_only_no_orcid(self):
        """With no ORCID, falls back to fetching from stored ID only."""
        paper = _make_mock_paper("p1", "Paper A")
        self.backend._client.get_author_papers.return_value = [paper]

        works, resolved_id = _run(
            self.backend.resolve_and_fetch_works(
                stored_id="111", orcid=None
            )
        )

        assert len(works) == 1
        assert works[0].title == "Paper A"
        assert resolved_id is None
        self.backend._client.get_author.assert_not_called()

    def test_orcid_discovers_new_id(self):
        """ORCID resolves to a different ID; both profiles are fetched."""
        mock_author = MagicMock()
        mock_author.authorId = "222"
        self.backend._client.get_author.return_value = mock_author

        paper_a = _make_mock_paper("p1", "Paper A")
        paper_b = _make_mock_paper("p2", "Paper B")
        paper_c = _make_mock_paper("p3", "Paper C")
        # First call for stored ID "111", second for resolved ID "222"
        self.backend._client.get_author_papers.side_effect = [
            [paper_a],
            [paper_b, paper_c],
        ]

        works, resolved_id = _run(
            self.backend.resolve_and_fetch_works(
                stored_id="111", orcid="0000-0002-1234-5678"
            )
        )

        assert resolved_id == "222"
        assert len(works) == 3
        titles = {w.title for w in works}
        assert titles == {"Paper A", "Paper B", "Paper C"}

    def test_orcid_same_as_stored(self):
        """ORCID resolves to the same ID; only one fetch call."""
        mock_author = MagicMock()
        mock_author.authorId = "111"
        self.backend._client.get_author.return_value = mock_author

        paper = _make_mock_paper("p1", "Paper A")
        self.backend._client.get_author_papers.return_value = [paper]

        works, resolved_id = _run(
            self.backend.resolve_and_fetch_works(
                stored_id="111", orcid="0000-0002-1234-5678"
            )
        )

        assert resolved_id == "111"
        assert len(works) == 1
        # get_author_papers called only once (IDs are deduplicated)
        assert (
            self.backend._client.get_author_papers.call_count == 1
        )

    def test_no_stored_id_with_orcid(self):
        """No stored ID but ORCID resolves; fetches from resolved ID."""
        mock_author = MagicMock()
        mock_author.authorId = "222"
        self.backend._client.get_author.return_value = mock_author

        paper = _make_mock_paper("p1", "Paper A")
        self.backend._client.get_author_papers.return_value = [paper]

        works, resolved_id = _run(
            self.backend.resolve_and_fetch_works(
                stored_id=None, orcid="0000-0002-1234-5678"
            )
        )

        assert resolved_id == "222"
        assert len(works) == 1

    def test_orcid_lookup_fails(self):
        """ORCID lookup raises exception; falls back to stored ID."""
        self.backend._client.get_author.side_effect = Exception(
            "Not found"
        )

        paper = _make_mock_paper("p1", "Paper A")
        self.backend._client.get_author_papers.return_value = [paper]

        works, resolved_id = _run(
            self.backend.resolve_and_fetch_works(
                stored_id="111", orcid="0000-0002-1234-5678"
            )
        )

        assert resolved_id is None
        assert len(works) == 1

    def test_deduplicates_by_paper_id(self):
        """Papers appearing under both profiles are deduplicated."""
        mock_author = MagicMock()
        mock_author.authorId = "222"
        self.backend._client.get_author.return_value = mock_author

        paper_a1 = _make_mock_paper("p1", "Paper A")
        paper_b = _make_mock_paper("p2", "Paper B")
        paper_a2 = _make_mock_paper("p1", "Paper A")  # duplicate
        paper_c = _make_mock_paper("p3", "Paper C")

        self.backend._client.get_author_papers.side_effect = [
            [paper_a1, paper_b],  # stored ID
            [paper_a2, paper_c],  # resolved ID
        ]

        works, _ = _run(
            self.backend.resolve_and_fetch_works(
                stored_id="111", orcid="0000-0002-1234-5678"
            )
        )

        assert len(works) == 3
        paper_ids = [w.semantic_scholar_id for w in works]
        assert len(set(paper_ids)) == 3

    def test_fragmentation_warning_logged(self, caplog):
        """WARNING is logged when ORCID-resolved ID differs from stored."""
        mock_author = MagicMock()
        mock_author.authorId = "222"
        self.backend._client.get_author.return_value = mock_author
        self.backend._client.get_author_papers.return_value = []

        with caplog.at_level(logging.WARNING):
            _run(
                self.backend.resolve_and_fetch_works(
                    stored_id="111", orcid="0000-0002-1234-5678"
                )
            )

        assert any(
            "fragmentation" in r.message for r in caplog.records
        )

    def test_no_stored_id_no_orcid(self):
        """With neither stored ID nor ORCID, returns empty."""
        works, resolved_id = _run(
            self.backend.resolve_and_fetch_works(
                stored_id=None, orcid=None
            )
        )

        assert works == []
        assert resolved_id is None

    def test_empty_string_stored_id_treated_as_none(self):
        """Empty string stored ID is treated as no stored ID."""
        mock_author = MagicMock()
        mock_author.authorId = "222"
        self.backend._client.get_author.return_value = mock_author

        paper = _make_mock_paper("p1", "Paper A")
        self.backend._client.get_author_papers.return_value = [paper]

        works, resolved_id = _run(
            self.backend.resolve_and_fetch_works(
                stored_id="", orcid="0000-0002-1234-5678"
            )
        )

        assert resolved_id == "222"
        assert len(works) == 1
        # Only called once (empty string is falsy, not added to set)
        assert (
            self.backend._client.get_author_papers.call_count == 1
        )

    def test_name_fallback_when_orcid_fails(self):
        """Name-based search is used when ORCID lookup fails."""
        self.backend._client.get_author.side_effect = Exception(
            "Not found"
        )

        mock_candidate = MagicMock()
        mock_candidate.authorId = "333"
        self.backend._client.search_author.return_value = [
            mock_candidate
        ]

        paper = _make_mock_paper("p1", "Paper A")
        self.backend._client.get_author_papers.return_value = [paper]

        works, resolved_id = _run(
            self.backend.resolve_and_fetch_works(
                stored_id=None,
                orcid="0000-0002-1234-5678",
                name="Jane Doe",
            )
        )

        assert resolved_id == "333"
        assert len(works) == 1
        self.backend._client.search_author.assert_called_once_with(
            "Jane Doe", limit=5
        )

    def test_name_fallback_not_used_when_orcid_succeeds(self):
        """Name search is skipped when ORCID resolution succeeds."""
        mock_author = MagicMock()
        mock_author.authorId = "222"
        self.backend._client.get_author.return_value = mock_author

        paper = _make_mock_paper("p1", "Paper A")
        self.backend._client.get_author_papers.return_value = [paper]

        works, resolved_id = _run(
            self.backend.resolve_and_fetch_works(
                stored_id=None,
                orcid="0000-0002-1234-5678",
                name="Jane Doe",
            )
        )

        assert resolved_id == "222"
        self.backend._client.search_author.assert_not_called()

    def test_name_fallback_with_stored_id(self):
        """Name search discovers additional IDs beyond stored ID."""
        self.backend._client.get_author.side_effect = Exception(
            "Not found"
        )

        mock_candidate = MagicMock()
        mock_candidate.authorId = "444"
        self.backend._client.search_author.return_value = [
            mock_candidate
        ]

        paper_a = _make_mock_paper("p1", "Paper A")
        paper_b = _make_mock_paper("p2", "Paper B")
        self.backend._client.get_author_papers.side_effect = [
            [paper_a],  # stored ID "111"
            [paper_b],  # name-discovered ID "444"
        ]

        works, resolved_id = _run(
            self.backend.resolve_and_fetch_works(
                stored_id="111",
                orcid="0000-0002-1234-5678",
                name="Jane Doe",
            )
        )

        assert len(works) == 2
        assert resolved_id == "444"
        assert (
            self.backend._client.get_author_papers.call_count == 2
        )

    def test_name_fallback_no_name_no_orcid(self):
        """Without name or ORCID, only stored ID is used."""
        paper = _make_mock_paper("p1", "Paper A")
        self.backend._client.get_author_papers.return_value = [paper]

        works, resolved_id = _run(
            self.backend.resolve_and_fetch_works(
                stored_id="111", orcid=None, name=None
            )
        )

        assert len(works) == 1
        assert resolved_id is None
        self.backend._client.search_author.assert_not_called()


class TestStoreUpdateResearcherSourceId:
    """Tests for Store.update_researcher_source_id."""

    def test_updates_s2_id(self, tmp_db):
        """S2 ID is updated in the database."""
        tmp_db.upsert_researcher(
            name="Martin",
            config_key="Martin",
            semantic_scholar_id="old_id",
        )
        tmp_db.update_researcher_source_id(
            config_key="Martin",
            semantic_scholar_id="new_id",
        )
        cursor = tmp_db._conn.execute(
            "SELECT semantic_scholar_id FROM researchers "
            "WHERE config_key = ?",
            ("Martin",),
        )
        row = cursor.fetchone()
        assert row["semantic_scholar_id"] == "new_id"

    def test_updates_openalex_id(self, tmp_db):
        """OpenAlex ID is updated in the database."""
        tmp_db.upsert_researcher(
            name="Jane",
            config_key="Jane",
            openalex_id="A_old",
        )
        tmp_db.update_researcher_source_id(
            config_key="Jane",
            openalex_id="A_new",
        )
        cursor = tmp_db._conn.execute(
            "SELECT openalex_id FROM researchers "
            "WHERE config_key = ?",
            ("Jane",),
        )
        row = cursor.fetchone()
        assert row["openalex_id"] == "A_new"

    def test_no_op_when_no_fields(self, tmp_db):
        """Calling with no fields is a safe no-op."""
        tmp_db.upsert_researcher(
            name="Bob",
            config_key="Bob",
            semantic_scholar_id="123",
        )
        tmp_db.update_researcher_source_id(config_key="Bob")
        cursor = tmp_db._conn.execute(
            "SELECT semantic_scholar_id FROM researchers "
            "WHERE config_key = ?",
            ("Bob",),
        )
        row = cursor.fetchone()
        assert row["semantic_scholar_id"] == "123"
