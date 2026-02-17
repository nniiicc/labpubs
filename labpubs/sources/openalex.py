"""OpenAlex source backend using pyalex.

Primary data source with broadest free coverage and stable author IDs.
"""

import asyncio
import logging
import unicodedata
from datetime import date
from functools import partial
from typing import Any

import pyalex
from pyalex import Authors, Works

from labpubs.models import Author, Award, Funder, Source, Work, WorkType
from labpubs.normalize import normalize_doi as _normalize_doi

logger = logging.getLogger(__name__)

_OPENALEX_TYPE_MAP: dict[str, WorkType] = {
    "article": WorkType.JOURNAL_ARTICLE,
    "journal-article": WorkType.JOURNAL_ARTICLE,
    "proceedings-article": WorkType.CONFERENCE_PAPER,
    "posted-content": WorkType.PREPRINT,
    "book-chapter": WorkType.BOOK_CHAPTER,
    "dissertation": WorkType.DISSERTATION,
}


def _openalex_work_to_model(work: dict[str, Any]) -> Work:
    """Convert an OpenAlex work dict to a Work model.

    Args:
        work: Raw OpenAlex work dictionary.

    Returns:
        Populated Work instance.
    """
    authors = []
    for authorship in work.get("authorships", []):
        author_data = authorship.get("author", {})
        institutions = authorship.get("institutions", [])
        affiliation = (
            institutions[0].get("display_name") if institutions else None
        )
        authors.append(
            Author(
                name=author_data.get("display_name", "Unknown"),
                openalex_id=author_data.get("id"),
                orcid=author_data.get("orcid"),
                affiliation=affiliation,
            )
        )

    oa = work.get("open_access", {})
    pub_date = None
    if work.get("publication_date"):
        try:
            pub_date = date.fromisoformat(work["publication_date"])
        except ValueError:
            pass

    raw_type = work.get("type", "other")
    work_type = _OPENALEX_TYPE_MAP.get(raw_type, WorkType.OTHER)

    # Reconstruct abstract from inverted index
    abstract = None
    abstract_index = work.get("abstract_inverted_index")
    if abstract_index:
        abstract = _reconstruct_abstract(abstract_index)

    venue_name = None
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    venue_name = source.get("display_name")

    # Parse funding data
    awards = _parse_awards(work.get("awards", []))
    funders = _parse_funders(work.get("funders", []))

    return Work(
        doi=_normalize_doi(work.get("doi")),
        title=work.get("title", "Untitled"),
        authors=authors,
        publication_date=pub_date,
        year=work.get("publication_year"),
        venue=venue_name,
        work_type=work_type,
        abstract=abstract,
        openalex_id=work.get("id"),
        open_access=oa.get("is_oa"),
        open_access_url=oa.get("oa_url"),
        citation_count=work.get("cited_by_count"),
        awards=awards,
        funders=funders,
        sources=[Source.OPENALEX],
    )


def _parse_awards(raw_awards: list[dict[str, Any]]) -> list[Award]:
    """Parse OpenAlex award data from a Work.

    Args:
        raw_awards: List of award dicts from the Work object.

    Returns:
        List of Award model instances.
    """
    awards: list[Award] = []
    for raw in raw_awards:
        funder = None
        funder_id = raw.get("funder_id")
        funder_name = raw.get("funder_display_name")
        if funder_id and funder_name:
            funder = Funder(
                openalex_id=funder_id,
                name=funder_name,
            )

        award_id = raw.get("id")
        if not award_id:
            continue

        awards.append(
            Award(
                openalex_id=award_id,
                display_name=raw.get("display_name"),
                funder_award_id=raw.get("funder_award_id"),
                funder=funder,
                doi=raw.get("doi"),
            )
        )
    return awards


def _parse_funders(raw_funders: list[dict[str, Any]]) -> list[Funder]:
    """Parse OpenAlex funder data from a Work.

    Args:
        raw_funders: List of funder dicts from the Work object.

    Returns:
        List of Funder model instances.
    """
    funders: list[Funder] = []
    for raw in raw_funders:
        funder_id = raw.get("id")
        name = raw.get("display_name")
        if not funder_id or not name:
            continue
        ror_id = raw.get("ror")
        funders.append(
            Funder(
                openalex_id=funder_id,
                name=name,
                ror_id=ror_id,
            )
        )
    return funders


def _reconstruct_abstract(inverted_index: dict[str, list[int]]) -> str:
    """Reconstruct abstract text from an OpenAlex inverted index.

    Args:
        inverted_index: Mapping of word -> list of positions.

    Returns:
        Reconstructed abstract string.
    """
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join(word for _, word in word_positions)


def _strip_accents(text: str) -> str:
    """Remove diacritical marks from text for matching.

    Args:
        text: Input string.

    Returns:
        String with accents removed.
    """
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


class OpenAlexBackend:
    """OpenAlex source backend using pyalex."""

    def __init__(self, email: str | None = None) -> None:
        """Initialize the OpenAlex backend.

        Args:
            email: Contact email for the OpenAlex polite pool.
        """
        if email:
            pyalex.config.email = email

    async def fetch_works_for_author(
        self, author_id: str, since: date | None = None
    ) -> list[Work]:
        """Fetch all works for an author from OpenAlex.

        Args:
            author_id: OpenAlex author ID.
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
            author_id: OpenAlex author ID.
            since: Optional date filter.

        Returns:
            List of Work objects.
        """
        filters: dict[str, str] = {"author.id": author_id}
        if since:
            filters["from_publication_date"] = since.isoformat()

        results: list[Work] = []
        try:
            for page in Works().filter(**filters).paginate(per_page=200):
                for work in page:
                    results.append(_openalex_work_to_model(work))
        except Exception:
            logger.exception(
                "Error fetching works for author %s from OpenAlex",
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
        """Fetch works from all known OpenAlex IDs for a researcher.

        Resolves the current canonical OpenAlex author ID via ORCID,
        then fetches works from both the stored and resolved IDs (if
        different).  Deduplicates by OpenAlex work ID.

        Args:
            stored_id: OpenAlex author ID from config/DB (may be stale).
            orcid: Researcher ORCID for resolving current canonical ID.
            since: Optional date filter.
            name: Researcher name (unused by OpenAlex, accepted for
                protocol compliance).

        Returns:
            Tuple of (deduplicated works, ORCID-resolved OpenAlex
            author ID or None).
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(
                self._resolve_and_fetch_sync, stored_id, orcid, since
            ),
        )

    def _resolve_and_fetch_sync(
        self,
        stored_id: str | None,
        orcid: str | None,
        since: date | None,
    ) -> tuple[list[Work], str | None]:
        """Synchronous resolve-and-fetch implementation."""
        author_ids: set[str] = set()
        resolved_id: str | None = None

        if stored_id:
            author_ids.add(stored_id)

        # Resolve current canonical ID via ORCID
        if orcid:
            author = self._resolve_by_orcid_sync(orcid)
            if author and author.openalex_id:
                resolved_id = author.openalex_id
                author_ids.add(resolved_id)
                if stored_id and resolved_id != stored_id:
                    logger.warning(
                        "OpenAlex profile fragmentation detected "
                        "for ORCID %s: stored ID %s, "
                        "ORCID-resolved ID %s",
                        orcid,
                        stored_id,
                        resolved_id,
                    )

        if not author_ids:
            return [], None

        # Fetch from all known IDs, dedup by OA work ID
        all_works: list[Work] = []
        seen_oa_ids: set[str] = set()
        for aid in author_ids:
            works = self._fetch_sync(aid, since)
            for work in works:
                oa_id = work.openalex_id
                if oa_id and oa_id in seen_oa_ids:
                    continue
                if oa_id:
                    seen_oa_ids.add(oa_id)
                all_works.append(work)

        return all_works, resolved_id

    async def resolve_author_by_orcid(
        self, orcid: str
    ) -> Author | None:
        """Look up an OpenAlex author directly by ORCID.

        Uses the deterministic endpoint rather than search, so the
        result is exact when the ORCID is linked in OpenAlex.

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
            author = Authors()[f"https://orcid.org/{orcid}"]
            if author:
                aff = None
                institutions = author.get("last_known_institutions", [])
                if institutions:
                    aff = institutions[0].get("display_name")
                oa_id = (author.get("id") or "").replace(
                    "https://openalex.org/", ""
                )
                return Author(
                    name=author.get("display_name", "Unknown"),
                    openalex_id=oa_id,
                    orcid=orcid,
                    affiliation=aff,
                )
        except Exception:
            logger.debug(
                "ORCID %s not found in OpenAlex", orcid
            )
        return None

    async def resolve_author_id(
        self, name: str, affiliation: str | None = None
    ) -> list[Author]:
        """Search OpenAlex for author candidates.

        Args:
            name: Author name to search for.
            affiliation: Optional affiliation to narrow results.

        Returns:
            List of candidate Author objects with OpenAlex IDs.
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
            query = Authors().search(name)
            for page in query.paginate(per_page=25, n_max=50):
                for author in page:
                    aff = None
                    if author.get("last_known_institutions"):
                        aff = author["last_known_institutions"][0].get(
                            "display_name"
                        )
                    if affiliation and aff:
                        name_lower = _strip_accents(
                            affiliation.lower()
                        )
                        aff_lower = _strip_accents(aff.lower())
                        if name_lower not in aff_lower:
                            continue
                    candidates.append(
                        Author(
                            name=author.get("display_name", "Unknown"),
                            openalex_id=author.get("id"),
                            orcid=author.get("orcid"),
                            affiliation=aff,
                        )
                    )
        except Exception:
            logger.exception(
                "Error resolving author '%s' in OpenAlex", name
            )
        return candidates
