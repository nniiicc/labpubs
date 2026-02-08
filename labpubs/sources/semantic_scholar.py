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

    venue = getattr(paper, "venue", None) or getattr(
        paper, "journal", None
    )
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

    def _fetch_sync(
        self, author_id: str, since: date | None
    ) -> list[Work]:
        """Synchronous fetch implementation.

        Args:
            author_id: Semantic Scholar author ID.
            since: Optional date filter.

        Returns:
            List of Work objects.
        """
        results: list[Work] = []
        try:
            author = self._client.get_author(author_id)
            papers = getattr(author, "papers", []) or []
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

    def _resolve_sync(
        self, name: str, affiliation: str | None
    ) -> list[Author]:
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
                        semantic_scholar_id=getattr(
                            a, "authorId", None
                        ),
                        affiliation=getattr(a, "affiliations", [None])[
                            0
                        ]
                        if getattr(a, "affiliations", None)
                        else None,
                    )
                )
        except Exception:
            logger.exception(
                "Error resolving author '%s' in S2", name
            )
        return candidates
