"""Base protocol for source backends."""

from datetime import date
from typing import Protocol

from labpubs.models import Author, Work


class SourceBackend(Protocol):
    """Protocol that all source backends must implement."""

    async def fetch_works_for_author(
        self, author_id: str, since: date | None = None
    ) -> list[Work]:
        """Fetch works authored by the given author.

        Args:
            author_id: Source-specific author identifier.
            since: If provided, only return works published on or after
                this date.

        Returns:
            List of Work objects from this source.
        """
        ...

    async def resolve_author_id(
        self, name: str, affiliation: str | None = None
    ) -> list[Author]:
        """Search for author candidates by name and affiliation.

        Args:
            name: Author name to search for.
            affiliation: Optional institutional affiliation to narrow
                results.

        Returns:
            List of candidate Author objects with source-specific IDs.
        """
        ...

    async def resolve_and_fetch_works(
        self,
        stored_id: str | None,
        orcid: str | None,
        since: date | None = None,
        name: str | None = None,
    ) -> tuple[list[Work], str | None]:
        """Fetch works using ORCID resolution to discover all author IDs.

        Resolves the current canonical author ID via ORCID, then fetches
        works from both the stored ID and the ORCID-resolved ID (if
        different).  Deduplicates by source-specific work ID.

        Args:
            stored_id: Source-specific author ID from config/DB.
            orcid: Researcher ORCID for resolving current canonical ID.
            since: Optional date filter.
            name: Researcher name for fallback search when ORCID fails.

        Returns:
            Tuple of (deduplicated works, ORCID-resolved author ID or
            None).
        """
        ...
