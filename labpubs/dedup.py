"""Deduplication logic for matching works across sources.

Uses a tiered strategy: DOI exact match, fuzzy title match, and
author+year+title fallback.
"""

import re
import unicodedata

from rapidfuzz import fuzz

from labpubs.models import Award, Funder, Source, Work, WorkType


def _normalize_doi(doi: str | None) -> str | None:
    """Normalize a DOI to lowercase without URL prefix.

    Args:
        doi: Raw DOI string.

    Returns:
        Normalized DOI or None.
    """
    if doi is None:
        return None
    doi = doi.lower().strip()
    doi = re.sub(r"^https?://doi\.org/", "", doi)
    return doi or None


def _normalize_title(title: str) -> str:
    """Normalize a title for comparison.

    Args:
        title: Raw title string.

    Returns:
        Normalized title.
    """
    text = title.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_surnames(work: Work) -> set[str]:
    """Extract lowercase author surnames from a Work.

    Args:
        work: Work with author data.

    Returns:
        Set of lowercase surname strings.
    """
    surnames: set[str] = set()
    for author in work.authors:
        parts = author.name.strip().split()
        if parts:
            surnames.add(parts[-1].lower())
    return surnames


def find_match(
    candidate: Work,
    existing_works: list[
        tuple[int, str, str | None, int | None, list[str]]
    ],
    title_threshold: int = 90,
) -> int | None:
    """Find a matching existing work for a candidate using tiered matching.

    Matching tiers:
    1. DOI exact match
    2. Fuzzy title match (token_sort_ratio >= threshold)
    3. Title + author surname overlap + same year (fallback)

    Args:
        candidate: New work to match.
        existing_works: List of tuples
            (id, title_normalized, doi, year, author_surnames).
        title_threshold: Minimum rapidfuzz score for title match
            (0-100).

    Returns:
        Database row ID of the matching work, or None.
    """
    candidate_doi = _normalize_doi(candidate.doi)
    candidate_title = _normalize_title(candidate.title)
    candidate_surnames = _extract_surnames(candidate)

    # Tier 1: DOI exact match
    if candidate_doi:
        for work_id, _, doi, _, _ in existing_works:
            if doi and doi == candidate_doi:
                return work_id

    # Tier 2: Fuzzy title match
    for work_id, title_norm, _, _, _ in existing_works:
        score = fuzz.token_sort_ratio(candidate_title, title_norm)
        if score >= title_threshold:
            return work_id

    # Tier 3: Title + author + year fallback (for short/generic titles)
    if candidate.year and candidate_surnames:
        for work_id, title_norm, _, year, surnames in existing_works:
            if year != candidate.year:
                continue
            score = fuzz.token_sort_ratio(
                candidate_title, title_norm
            )
            if score < 80:
                continue
            existing_surname_set = set(surnames)
            if candidate_surnames & existing_surname_set:
                return work_id

    return None


def merge_works(existing: Work, new: Work) -> Work:
    """Merge metadata from a new work into an existing work.

    Prefers existing data but fills in missing fields from the new
    source. Always updates citation counts and adds new source IDs.

    Args:
        existing: The existing stored work.
        new: Newly fetched work from another source.

    Returns:
        Merged Work instance.
    """
    merged_sources = list(
        dict.fromkeys(
            [s.value for s in existing.sources]
            + [s.value for s in new.sources]
        )
    )

    return Work(
        doi=existing.doi or new.doi,
        title=existing.title,
        authors=existing.authors if existing.authors else new.authors,
        publication_date=existing.publication_date
        or new.publication_date,
        year=existing.year or new.year,
        venue=existing.venue or new.venue,
        work_type=existing.work_type
        if existing.work_type != WorkType.OTHER
        else new.work_type,
        abstract=existing.abstract or new.abstract,
        openalex_id=existing.openalex_id or new.openalex_id,
        semantic_scholar_id=existing.semantic_scholar_id
        or new.semantic_scholar_id,
        open_access=existing.open_access
        if existing.open_access is not None
        else new.open_access,
        open_access_url=existing.open_access_url
        or new.open_access_url,
        citation_count=max(
            existing.citation_count or 0,
            new.citation_count or 0,
        )
        or None,
        tldr=existing.tldr or new.tldr,
        awards=_merge_awards(existing.awards, new.awards),
        funders=_merge_funders(existing.funders, new.funders),
        sources=[Source(s) for s in merged_sources],
        first_seen=existing.first_seen,
        last_updated=new.last_updated or existing.last_updated,
    )


def _merge_awards(
    existing: list[Award], new: list[Award]
) -> list[Award]:
    """Merge award lists, deduplicating by openalex_id.

    Args:
        existing: Awards from the existing work.
        new: Awards from the new work.

    Returns:
        Deduplicated merged list.
    """
    seen: dict[str, Award] = {}
    for award in existing:
        seen[award.openalex_id] = award
    for award in new:
        if award.openalex_id not in seen:
            seen[award.openalex_id] = award
    return list(seen.values())


def _merge_funders(
    existing: list[Funder], new: list[Funder]
) -> list[Funder]:
    """Merge funder lists, deduplicating by openalex_id.

    Args:
        existing: Funders from the existing work.
        new: Funders from the new work.

    Returns:
        Deduplicated merged list.
    """
    seen: dict[str, Funder] = {}
    for funder in existing:
        seen[funder.openalex_id] = funder
    for funder in new:
        if funder.openalex_id not in seen:
            seen[funder.openalex_id] = funder
    return list(seen.values())
