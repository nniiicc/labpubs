"""Semantic Scholar source backend.

Secondary source with faster preprint pickup and TLDR summaries.
"""

import asyncio
import logging
from datetime import date
from functools import partial

from semanticscholar import SemanticScholar

from labpubs.models import Author, Source, Work, WorkType

logger = logging.getLogger(__name__)

_S2_TYPE_MAP: dict[str, WorkType] = {
    "JournalArticle": WorkType.JOURNAL_ARTICLE,
    "Conference": WorkType.CONFERENCE_PAPER,
    "Review": WorkType.JOURNAL_ARTICLE,
    "Book": WorkType.BOOK_CHAPTER,
    "Dataset": WorkType.OTHER,
}


def _s2_paper_to_model(paper: object) -> Work:
    """Convert a Semantic Scholar paper object to a Work model.

    Args:
        paper: semanticscholar Paper object.

    Returns:
        Populated Work instance.
    """
    authors = []
    for a in getattr(paper, "authors", []) or []:
        authors.append(
            Author(
                name=getattr(a, "name", "Unknown"),
                semantic_scholar_id=getattr(a, "authorId", None),
            )
        )

    pub_date = None
    year = None
    raw_date = getattr(paper, "publicationDate", None)
    if raw_date:
        if isinstance(raw_date, str):
            try:
                pub_date = date.fromisoformat(raw_date)
                year = pub_date.year
            except ValueError:
                pass
        elif isinstance(raw_date, date):
            pub_date = raw_date
            year = pub_date.year

    if year is None:
        year = getattr(paper, "year", None)

    raw_type = getattr(paper, "publicationTypes", None) or []
    work_type = WorkType.OTHER
    for t in raw_type:
        if t in _S2_TYPE_MAP:
            work_type = _S2_TYPE_MAP[t]
            break

    doi = getattr(paper, "externalIds", {})
    if isinstance(doi, dict):
        doi = doi.get("DOI")
    else:
        doi = None

    if doi:
        doi = doi.lower().strip()

    tldr = None
    tldr_obj = getattr(paper, "tldr", None)
    if tldr_obj and hasattr(tldr_obj, "text"):
        tldr = tldr_obj.text
    elif isinstance(tldr_obj, dict):
        tldr = tldr_obj.get("text")

    venue = getattr(paper, "venue", None) or getattr(paper, "journal", None)
    if venue and hasattr(venue, "name"):
        venue = venue.name

    return Work(
        doi=doi,
        title=getattr(paper, "title", "Untitled") or "Untitled",
        authors=authors,
        publication_date=pub_date,
        year=year,
        venue=venue if isinstance(venue, str) else None,
        work_type=work_type,
        abstract=getattr(paper, "abstract", None),
        semantic_scholar_id=getattr(paper, "paperId", None),
        open_access=getattr(paper, "isOpenAccess", None),
        open_access_url=getattr(paper, "openAccessPdf", {}).get("url")
        if isinstance(getattr(paper, "openAccessPdf", None), dict)
        else None,
        citation_count=getattr(paper, "citationCount", None),
        tldr=tldr,
        sources=[Source.SEMANTIC_SCHOLAR],
    )


class SemanticScholarBackend:
    """Semantic Scholar source backend."""

    def __init__(self, api_key: str | None = None) -> None:
        """Initialize the Semantic Scholar backend.

        Args:
            api_key: Optional API key for higher rate limits.
        """
        self._client = SemanticScholar(api_key=api_key)

    async def fetch_works_for_author(
        self, author_id: str, since: date | None = None
    ) -> list[Work]:
        """Fetch all works for an author from Semantic Scholar.

        Args:
            author_id: Semantic Scholar author ID.
            since: Only return works published on or after this date.

        Returns:
            List of Work objects.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, partial(self._fetch_sync, author_id, since)
        )

    _PAPER_FIELDS = [
        "title",
        "authors",
        "publicationDate",
        "year",
        "venue",
        "journal",
        "publicationTypes",
        "externalIds",
        "abstract",
        "isOpenAccess",
        "openAccessPdf",
        "citationCount",
        "paperId",
    ]

    def _fetch_sync(self, author_id: str, since: date | None) -> list[Work]:
        """Synchronous fetch implementation using paginated endpoint.

        Args:
            author_id: Semantic Scholar author ID.
            since: Optional date filter.

        Returns:
            List of Work objects.
        """
        results: list[Work] = []
        try:
            papers = self._client.get_author_papers(
                author_id,
                fields=self._PAPER_FIELDS,
                limit=1000,
            )
            for paper in papers:
                work = _s2_paper_to_model(paper)
                if since and work.publication_date and work.publication_date < since:
                    continue
                results.append(work)
        except Exception:
            logger.exception(
                "Error fetching works for author %s from S2",
                author_id,
            )
        return results

    async def resolve_and_fetch_works(
        self,
        stored_id: str | None,
        orcid: str | None,
        since: date | None = None,
        name: str | None = None,
    ) -> tuple[list[Work], str | None]:
        """Fetch works from all known S2 IDs for a researcher.

        Resolution strategy:
        1. ORCID lookup (most reliable when linked)
        2. Name-based search fallback (when ORCID not linked in S2)
        3. Stored ID (always used if available)

        Fetches works from ALL discovered IDs and deduplicates by S2
        paper ID.

        Args:
            stored_id: S2 author ID from config/DB (may be stale).
            orcid: Researcher ORCID for resolving current canonical ID.
            since: Optional date filter.
            name: Researcher name for fallback search when ORCID fails.

        Returns:
            Tuple of (deduplicated works, best resolved S2 author ID
            or None).
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(
                self._resolve_and_fetch_sync,
                stored_id,
                orcid,
                since,
                name,
            ),
        )

    def _resolve_and_fetch_sync(
        self,
        stored_id: str | None,
        orcid: str | None,
        since: date | None,
        name: str | None = None,
    ) -> tuple[list[Work], str | None]:
        """Synchronous resolve-and-fetch implementation."""
        author_ids: set[str] = set()
        resolved_id: str | None = None

        if stored_id:
            author_ids.add(stored_id)

        # Strategy 1: Resolve via ORCID
        orcid_found = False
        if orcid:
            try:
                author = self._client.get_author(f"ORCID:{orcid}")
                if author:
                    resolved_id = getattr(author, "authorId", None)
                    if resolved_id:
                        orcid_found = True
                        author_ids.add(resolved_id)
                        if stored_id and resolved_id != stored_id:
                            logger.warning(
                                "S2 profile fragmentation detected "
                                "for ORCID %s: stored ID %s, "
                                "ORCID-resolved ID %s",
                                orcid,
                                stored_id,
                                resolved_id,
                            )
            except Exception:
                logger.debug("ORCID %s not found in Semantic Scholar", orcid)

        # Strategy 2: Name-based search fallback
        if not orcid_found and name:
            try:
                results = self._client.search_author(name, limit=5)
                count = 0
                for a in results or []:
                    if count >= 5:
                        break
                    count += 1
                    aid = getattr(a, "authorId", None)
                    if aid and aid != stored_id:
                        author_ids.add(aid)
                        if resolved_id is None:
                            resolved_id = aid
                        logger.debug(
                            "S2 name search found candidate %s for '%s'",
                            aid,
                            name,
                        )
            except Exception:
                logger.debug("S2 name search failed for '%s'", name)

        if not author_ids:
            return [], None

        # Fetch from all known IDs, dedup by paper ID
        all_works: list[Work] = []
        seen_paper_ids: set[str] = set()
        for aid in author_ids:
            works = self._fetch_sync(aid, since)
            for work in works:
                pid = work.semantic_scholar_id
                if pid and pid in seen_paper_ids:
                    continue
                if pid:
                    seen_paper_ids.add(pid)
                all_works.append(work)

        return all_works, resolved_id

    async def resolve_author_by_orcid(self, orcid: str) -> Author | None:
        """Look up a Semantic Scholar author directly by ORCID.

        Args:
            orcid: ORCID identifier (e.g. ``0000-0002-1234-5678``).

        Returns:
            Author if found, None otherwise.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, partial(self._resolve_by_orcid_sync, orcid)
        )

    def _resolve_by_orcid_sync(self, orcid: str) -> Author | None:
        """Synchronous ORCID-based author lookup."""
        try:
            author = self._client.get_author(f"ORCID:{orcid}")
            if author:
                return Author(
                    name=getattr(author, "name", "Unknown"),
                    semantic_scholar_id=getattr(author, "authorId", None),
                    orcid=orcid,
                )
        except Exception:
            logger.debug("ORCID %s not found in Semantic Scholar", orcid)
        return None

    async def resolve_author_id(
        self, name: str, affiliation: str | None = None
    ) -> list[Author]:
        """Search Semantic Scholar for author candidates.

        Args:
            name: Author name to search for.
            affiliation: Optional affiliation (unused by S2 API but
                accepted for protocol compliance).

        Returns:
            List of candidate Author objects.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, partial(self._resolve_sync, name, affiliation)
        )

    def _resolve_sync(self, name: str, affiliation: str | None) -> list[Author]:
        """Synchronous author resolution.

        Args:
            name: Author name.
            affiliation: Optional affiliation.

        Returns:
            List of candidate Authors.
        """
        candidates: list[Author] = []
        try:
            results = self._client.search_author(name, limit=10)
            for a in results:
                candidates.append(
                    Author(
                        name=getattr(a, "name", "Unknown"),
                        semantic_scholar_id=getattr(a, "authorId", None),
                        affiliation=getattr(a, "affiliations", [None])[0]
                        if getattr(a, "affiliations", None)
                        else None,
                    )
                )
        except Exception:
            logger.exception("Error resolving author '%s' in S2", name)
        return candidates
