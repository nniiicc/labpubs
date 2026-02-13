"""Resolve researcher IDs from ORCIDs and names.

Provides the logic behind ``labpubs init``: reads a CSV of lab members,
queries OpenAlex and Semantic Scholar to resolve author IDs, and
generates a ``labpubs.yaml`` configuration file.
"""

import asyncio
import csv
import logging
from pathlib import Path

import yaml
from pydantic import BaseModel

from labpubs.models import Author
from labpubs.sources.openalex import OpenAlexBackend
from labpubs.sources.semantic_scholar import SemanticScholarBackend

logger = logging.getLogger(__name__)

# Column name aliases accepted in the CSV header (lowercase).
_NAME_ALIASES = {"name", "full_name", "fullname", "author"}
_ORCID_ALIASES = {"orcid", "orcid_id", "orcid-id"}
_OA_ALIASES = {"openalex_id", "openalex", "oa_id"}
_S2_ALIASES = {
    "semantic_scholar_id",
    "s2_id",
    "s2id",
    "semantic_scholar",
}
_AFF_ALIASES = {"affiliation", "institution"}


class ResolveResult(BaseModel):
    """Result of resolving IDs for a single researcher."""

    name: str
    orcid: str | None = None
    affiliation: str | None = None

    openalex_id: str | None = None
    semantic_scholar_id: str | None = None

    openalex_candidates: list[Author] = []
    s2_candidates: list[Author] = []

    openalex_confident: bool = False
    s2_confident: bool = False


def _match_column(
    headers: list[str], aliases: set[str]
) -> str | None:
    """Find a CSV column matching any of the given aliases."""
    for h in headers:
        if h.strip().lower().replace(" ", "_") in aliases:
            return h
    return None


def parse_csv(csv_path: str | Path) -> list[dict[str, str]]:
    """Parse a CSV file of lab members.

    Accepts flexible header names (see module-level alias sets).

    Args:
        csv_path: Path to the CSV file.

    Returns:
        List of dicts with normalised keys: ``name``, ``orcid``,
        ``openalex_id``, ``semantic_scholar_id``, ``affiliation``.

    Raises:
        ValueError: If the CSV is missing a ``name`` column.
    """
    path = Path(csv_path)
    rows: list[dict[str, str]] = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        col_name = _match_column(headers, _NAME_ALIASES)
        col_orcid = _match_column(headers, _ORCID_ALIASES)
        col_oa = _match_column(headers, _OA_ALIASES)
        col_s2 = _match_column(headers, _S2_ALIASES)
        col_aff = _match_column(headers, _AFF_ALIASES)

        if col_name is None:
            raise ValueError(
                f"CSV must have a 'name' column. Found: {headers}"
            )

        for row in reader:
            name = (row.get(col_name) or "").strip()
            if not name:
                continue
            rows.append(
                {
                    "name": name,
                    "orcid": (
                        row.get(col_orcid, "") if col_orcid else ""
                    ).strip(),
                    "openalex_id": (
                        row.get(col_oa, "") if col_oa else ""
                    ).strip(),
                    "semantic_scholar_id": (
                        row.get(col_s2, "") if col_s2 else ""
                    ).strip(),
                    "affiliation": (
                        row.get(col_aff, "") if col_aff else ""
                    ).strip(),
                }
            )
    return rows


async def resolve_researcher(
    name: str,
    orcid: str | None,
    affiliation: str | None,
    openalex_backend: OpenAlexBackend | None = None,
    s2_backend: SemanticScholarBackend | None = None,
) -> ResolveResult:
    """Resolve OpenAlex and Semantic Scholar IDs for one researcher.

    Strategy per source:
      1. If ORCID is provided, try direct ORCID endpoint.
      2. If that fails, fall back to name (+affiliation) search.

    Args:
        name: Researcher display name.
        orcid: ORCID if known.
        affiliation: Institution name for fallback filtering.
        openalex_backend: Optional OpenAlex backend instance.
        s2_backend: Optional Semantic Scholar backend instance.

    Returns:
        A :class:`ResolveResult` with resolved IDs and/or candidates.
    """
    result = ResolveResult(
        name=name, orcid=orcid, affiliation=affiliation
    )

    # --- OpenAlex ---
    if openalex_backend:
        # 1. Try ORCID direct lookup
        if orcid:
            author = await openalex_backend.resolve_author_by_orcid(
                orcid
            )
            if author and author.openalex_id:
                result.openalex_id = author.openalex_id
                result.openalex_confident = True

        # 2. Fallback: name search
        if not result.openalex_id:
            candidates = await openalex_backend.resolve_author_id(
                name, affiliation
            )
            result.openalex_candidates = candidates

    # --- Semantic Scholar ---
    if s2_backend:
        # 1. Try ORCID direct lookup
        if orcid:
            author = await s2_backend.resolve_author_by_orcid(orcid)
            if author and author.semantic_scholar_id:
                result.semantic_scholar_id = author.semantic_scholar_id
                result.s2_confident = True

        # 2. Fallback: name search
        if not result.semantic_scholar_id:
            candidates = await s2_backend.resolve_author_id(name)
            result.s2_candidates = candidates

    return result


async def resolve_researchers_from_csv(
    csv_path: str | Path,
    openalex_backend: OpenAlexBackend | None = None,
    s2_backend: SemanticScholarBackend | None = None,
    rate_limit_delay: float = 0.5,
    progress_callback: object = None,
) -> list[ResolveResult]:
    """Resolve IDs for every researcher in a CSV.

    Args:
        csv_path: Path to the CSV file.
        openalex_backend: OpenAlex backend (or None to skip).
        s2_backend: Semantic Scholar backend (or None to skip).
        rate_limit_delay: Seconds to wait between API calls.
        progress_callback: Optional ``callable(name, i, total)``
            invoked before each lookup.

    Returns:
        List of :class:`ResolveResult` objects.
    """
    rows = parse_csv(csv_path)
    results: list[ResolveResult] = []

    for i, row in enumerate(rows):
        if progress_callback:
            progress_callback(row["name"], i, len(rows))  # type: ignore[operator]

        # Skip lookup if IDs are already provided in the CSV.
        pre_oa = row.get("openalex_id", "")
        pre_s2 = row.get("semantic_scholar_id", "")

        r = await resolve_researcher(
            name=row["name"],
            orcid=row["orcid"] or None,
            affiliation=row["affiliation"] or None,
            openalex_backend=None if pre_oa else openalex_backend,
            s2_backend=None if pre_s2 else s2_backend,
        )

        # Carry forward pre-filled IDs from CSV.
        if pre_oa:
            r.openalex_id = pre_oa
            r.openalex_confident = True
        if pre_s2:
            r.semantic_scholar_id = pre_s2
            r.s2_confident = True

        results.append(r)
        await asyncio.sleep(rate_limit_delay)

    return results


def generate_config_yaml(
    results: list[ResolveResult],
    lab_name: str = "",
    institution: str = "",
    openalex_email: str | None = None,
    database_path: str = "~/.labpubs/labpubs.db",
) -> str:
    """Build a ``labpubs.yaml`` string from resolution results.

    Args:
        results: Resolved researcher results.
        lab_name: Lab display name.
        institution: Lab institution.
        openalex_email: Email for OpenAlex polite pool.
        database_path: SQLite database path.

    Returns:
        YAML string ready to be written to a file.
    """
    researchers = []
    for r in results:
        entry: dict[str, str | None] = {"name": r.name}
        if r.orcid:
            entry["orcid"] = r.orcid
        if r.openalex_id:
            entry["openalex_id"] = r.openalex_id
        if r.semantic_scholar_id:
            entry["semantic_scholar_id"] = r.semantic_scholar_id
        if r.affiliation:
            entry["affiliation"] = r.affiliation
        researchers.append(entry)

    config: dict = {
        "lab": {"name": lab_name, "institution": institution},
        "openalex_email": openalex_email,
        "database_path": database_path,
        "researchers": researchers,
        "sources": ["openalex", "semantic_scholar", "crossref"],
    }

    return yaml.dump(
        config, default_flow_style=False, sort_keys=False
    )


def merge_into_existing(
    existing_path: str | Path,
    results: list[ResolveResult],
) -> str:
    """Merge new researchers into an existing ``labpubs.yaml``.

    Matches by ORCID first, then by name. Existing researchers are
    updated with any newly resolved IDs; new researchers are appended.

    Args:
        existing_path: Path to the existing YAML config.
        results: Resolved researcher results to merge.

    Returns:
        Updated YAML string.
    """
    with open(existing_path) as f:
        config = yaml.safe_load(f) or {}

    existing = config.setdefault("researchers", [])

    # Build lookup indices.
    by_orcid: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for entry in existing:
        if entry.get("orcid"):
            by_orcid[entry["orcid"]] = entry
        by_name[entry["name"].lower()] = entry

    for r in results:
        match = None
        if r.orcid:
            match = by_orcid.get(r.orcid)
        if match is None:
            match = by_name.get(r.name.lower())

        if match is not None:
            # Update with any newly resolved IDs.
            if r.openalex_id and not match.get("openalex_id"):
                match["openalex_id"] = r.openalex_id
            if r.semantic_scholar_id and not match.get(
                "semantic_scholar_id"
            ):
                match["semantic_scholar_id"] = r.semantic_scholar_id
        else:
            entry: dict[str, str | None] = {"name": r.name}
            if r.orcid:
                entry["orcid"] = r.orcid
            if r.openalex_id:
                entry["openalex_id"] = r.openalex_id
            if r.semantic_scholar_id:
                entry["semantic_scholar_id"] = r.semantic_scholar_id
            if r.affiliation:
                entry["affiliation"] = r.affiliation
            existing.append(entry)

    return yaml.dump(
        config, default_flow_style=False, sort_keys=False
    )
