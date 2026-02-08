"""CSL-JSON export for labpubs works.

Produces output compatible with pandoc-citeproc and Zotero.
"""

from typing import Any

from labpubs.models import Work, WorkType

_CSL_TYPE_MAP: dict[WorkType, str] = {
    WorkType.JOURNAL_ARTICLE: "article-journal",
    WorkType.CONFERENCE_PAPER: "paper-conference",
    WorkType.PREPRINT: "article",
    WorkType.BOOK_CHAPTER: "chapter",
    WorkType.DISSERTATION: "thesis",
    WorkType.OTHER: "article",
}


def work_to_csl(work: Work) -> dict[str, Any]:
    """Convert a Work to a CSL-JSON dictionary.

    Args:
        work: Work to convert.

    Returns:
        CSL-JSON compatible dictionary.
    """
    csl_type = _CSL_TYPE_MAP.get(work.work_type, "article")

    authors = []
    for a in work.authors:
        parts = a.name.strip().split()
        if len(parts) >= 2:
            authors.append(
                {"family": parts[-1], "given": " ".join(parts[:-1])}
            )
        elif parts:
            authors.append({"literal": parts[0]})

    entry: dict[str, Any] = {
        "type": csl_type,
        "title": work.title,
        "author": authors,
    }

    if work.doi:
        entry["DOI"] = work.doi
        # Generate a stable ID from DOI
        entry["id"] = work.doi.replace("/", "_").replace(".", "-")
    else:
        safe_title = "".join(
            c if c.isalnum() else "_" for c in work.title[:40]
        )
        entry["id"] = f"{safe_title}_{work.year or 'nd'}"

    if work.publication_date:
        entry["issued"] = {
            "date-parts": [
                [
                    work.publication_date.year,
                    work.publication_date.month,
                    work.publication_date.day,
                ]
            ]
        }
    elif work.year:
        entry["issued"] = {"date-parts": [[work.year]]}

    if work.venue:
        if csl_type == "article-journal":
            entry["container-title"] = work.venue
        elif csl_type == "paper-conference":
            entry["container-title"] = work.venue
        else:
            entry["container-title"] = work.venue

    if work.abstract:
        entry["abstract"] = work.abstract

    if work.open_access_url:
        entry["URL"] = work.open_access_url

    return entry


def works_to_csl_json(works: list[Work]) -> list[dict[str, Any]]:
    """Export a list of works as CSL-JSON.

    Args:
        works: List of Work objects.

    Returns:
        List of CSL-JSON dictionaries.
    """
    return [work_to_csl(w) for w in works]
