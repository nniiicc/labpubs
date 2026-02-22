"""Router for researcher endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from labpubs.api.deps import get_engine
from labpubs.core import LabPubs

router = APIRouter(prefix="/researchers", tags=["researchers"])


@router.get("")
def list_researchers(
    engine: LabPubs = Depends(get_engine),
) -> list[dict[str, Any]]:
    """List all tracked lab members with their identifiers.

    Args:
        engine: Injected LabPubs engine.

    Returns:
        List of researcher records.
    """
    researchers = engine.get_researchers()
    return [r.model_dump(exclude_none=True) for r in researchers]
