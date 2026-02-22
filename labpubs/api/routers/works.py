"""Router for publication/work endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from labpubs.api.deps import get_engine
from labpubs.core import LabPubs

router = APIRouter(prefix="/works", tags=["works"])


@router.get("")
def list_works(
    researcher: str | None = Query(None, description="Filter by researcher name"),
    year: int | None = Query(None, description="Filter by publication year"),
    funder: str | None = Query(None, description="Filter by funder name"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    engine: LabPubs = Depends(get_engine),
) -> list[dict[str, Any]]:
    """List publications with optional filters.

    Args:
        researcher: Researcher name to filter by.
        year: Publication year to filter by.
        funder: Funder name to filter by.
        limit: Maximum number of results (1-500).
        engine: Injected LabPubs engine.

    Returns:
        List of publication records.
    """
    if funder:
        works = engine.get_works_by_funder(funder, year=year)
    else:
        works = engine.get_works(researcher=researcher, year=year)
    return [w.model_dump(exclude_none=True) for w in works[:limit]]


@router.get("/search")
def search_works(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=200),
    engine: LabPubs = Depends(get_engine),
) -> list[dict[str, Any]]:
    """Full-text search across publication titles and abstracts.

    Args:
        q: Search string.
        limit: Maximum number of results.
        engine: Injected LabPubs engine.

    Returns:
        Matching publication records.
    """
    works = engine.search_works(q, limit=limit)
    return [w.model_dump(exclude_none=True) for w in works]


@router.get("/{doi:path}")
def get_work_by_doi(
    doi: str,
    engine: LabPubs = Depends(get_engine),
) -> dict[str, Any]:
    """Get a specific publication by DOI.

    Args:
        doi: The DOI identifier (e.g., 10.1234/example).
        engine: Injected LabPubs engine.

    Returns:
        Full publication record.

    Raises:
        HTTPException: 404 if the DOI is not found.
    """
    works = engine.search_works(doi, limit=5)
    matching = [w for w in works if w.doi and doi in w.doi]
    if not matching:
        raise HTTPException(status_code=404, detail=f"Work with DOI '{doi}' not found")
    return matching[0].model_dump(exclude_none=True)
