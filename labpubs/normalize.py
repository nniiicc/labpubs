"""Shared text normalization utilities for labpubs.

Used by deduplication, storage, source backends, and export modules
for consistent normalization across the codebase.
"""

import re
import unicodedata


def split_author_name(name: str) -> tuple[str | None, str | None]:
    """Split an author name string into (given_names, family_name).

    Assumes 'Given [Middle] Family' ordering, which is what OpenAlex
    and Semantic Scholar return.

    Args:
        name: Full author name string.

    Returns:
        Tuple of (given_names, family_name). Returns (None, None)
        for empty/whitespace-only names. Returns (None, name) for
        single-word names.
    """
    parts = name.strip().split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return None, parts[0]
    return " ".join(parts[:-1]), parts[-1]


def normalize_doi(doi: str | None) -> str | None:
    """Normalize a DOI to lowercase without URL prefix.

    Args:
        doi: Raw DOI string, possibly with URL prefix.

    Returns:
        Normalized DOI or None.
    """
    if doi is None:
        return None
    doi = doi.lower().strip()
    doi = re.sub(r"^https?://doi\.org/", "", doi)
    return doi or None


def normalize_title(title: str) -> str:
    """Normalize a title for comparison and matching.

    Lowercases, strips accents, removes punctuation, and collapses
    whitespace.

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
