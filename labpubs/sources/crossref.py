"""Crossref source backend using habanero.

Used for DOI metadata enrichment rather than author-based searching,
since Crossref lacks stable author IDs.
"""

import asyncio
import logging
from datetime import date
from functools import partial
from typing import Any

from habanero import Crossref

from labpubs.models import Author, Source, Work, WorkType

logger = logging.getLogger(__name__)

_CR_TYPE_MAP: dict[str, WorkType] = {
    "journal-article": WorkType.JOURNAL_ARTICLE,
    "proceedings-article": WorkType.CONFERENCE_PAPER,
    "posted-content": WorkType.PREPRINT,
    "book-chapter": WorkType.BOOK_CHAPTER,
    "dissertation": WorkType.DISSERTATION,
}


def _crossref_to_work(message: dict[str, Any]) -> Work:
    """Convert a Crossref message dict to a Work model.

    Args:
        message: Crossref API message dictionary.

    Returns:
        Populated Work instance.
    """
    authors = []
    for a in message.get("author", []):
        given = a.get("given", "")
        family = a.get("family", "")
        name = f"{given} {family}".strip() or "Unknown"
        aff_list = a.get("affiliation", [])
        affiliation = aff_list[0].get("name") if aff_list else None
        authors.append(Author(name=name, affiliation=affiliation))

    doi = message.get("DOI")
    if doi:
        doi = doi.lower().strip()

    pub_date = None
    year = None
    date_parts = message.get("published-print", {}).get(
        "date-parts", [[]]
    )[0]
    if not date_parts:
        date_parts = message.get("published-online", {}).get(
            "date-parts", [[]]
        )[0]
    if date_parts:
        year = date_parts[0] if len(date_parts) >= 1 else None
        month = date_parts[1] if len(date_parts) >= 2 else 1
        day = date_parts[2] if len(date_parts) >= 3 else 1
        if year:
            try:
                pub_date = date(year, month, day)
            except (ValueError, TypeError):
                pass

    raw_type = message.get("type", "other")
    work_type = _CR_TYPE_MAP.get(raw_type, WorkType.OTHER)

    title_list = message.get("title", [])
    title = title_list[0] if title_list else "Untitled"

    venue_list = message.get("container-title", [])
    venue = venue_list[0] if venue_list else None

    return Work(
        doi=doi,
        title=title,
        authors=authors,
        publication_date=pub_date,
        year=year,
        venue=venue,
        work_type=work_type,
        sources=[Source.CROSSREF],
        citation_count=message.get("is-referenced-by-count"),
    )


class CrossrefBackend:
    """Crossref backend for DOI enrichment using habanero."""

    def __init__(self, email: str | None = None) -> None:
        """Initialize the Crossref backend.

        Args:
            email: Contact email for Crossref polite pool.
        """
        self._client = Crossref(mailto=email)

    async def enrich_work_by_doi(self, doi: str) -> Work | None:
        """Fetch metadata for a single DOI from Crossref.

        Args:
            doi: DOI to look up.

        Returns:
            Work with Crossref metadata, or None on failure.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, partial(self._enrich_sync, doi)
        )

    def _enrich_sync(self, doi: str) -> Work | None:
        """Synchronous DOI enrichment.

        Args:
            doi: DOI to look up.

        Returns:
            Work or None.
        """
        try:
            result = self._client.works(ids=doi)
            message = result.get("message", {})
            return _crossref_to_work(message)
        except Exception:
            logger.exception(
                "Error enriching DOI %s from Crossref", doi
            )
            return None

    async def fetch_works_for_author(
        self, author_id: str, since: date | None = None
    ) -> list[Work]:
        """Not supported -- Crossref lacks stable author IDs.

        Args:
            author_id: Unused.
            since: Unused.

        Returns:
            Empty list.
        """
        logger.warning(
            "Crossref does not support author-based fetching"
        )
        return []

    async def resolve_author_id(
        self, name: str, affiliation: str | None = None
    ) -> list[Author]:
        """Not supported -- Crossref lacks stable author IDs.

        Args:
            name: Unused.
            affiliation: Unused.

        Returns:
            Empty list.
        """
        logger.warning(
            "Crossref does not support author ID resolution"
        )
        return []
