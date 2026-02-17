"""BibTeX export for labpubs works."""

import re

import bibtexparser
from bibtexparser.bwriter import BibTexWriter

from labpubs.models import Work, WorkType
from labpubs.normalize import split_author_name

_TYPE_MAP: dict[WorkType, str] = {
    WorkType.JOURNAL_ARTICLE: "article",
    WorkType.CONFERENCE_PAPER: "inproceedings",
    WorkType.PREPRINT: "misc",
    WorkType.BOOK_CHAPTER: "incollection",
    WorkType.DISSERTATION: "phdthesis",
    WorkType.OTHER: "misc",
}


def _make_bibtex_key(work: Work) -> str:
    """Generate a BibTeX citation key.

    Format: {first_author_surname}{year}{first_significant_title_word}

    Args:
        work: Work to generate a key for.

    Returns:
        BibTeX citation key string.
    """
    surname = "unknown"
    if work.authors:
        _, family = split_author_name(work.authors[0].name)
        if family:
            surname = re.sub(r"[^\w]", "", family.lower())

    year = str(work.year) if work.year else "nd"

    title_word = "untitled"
    stop_words = {
        "a",
        "an",
        "the",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "but",
        "is",
        "are",
        "was",
        "were",
        "with",
    }
    for word in work.title.split():
        cleaned = re.sub(r"[^\w]", "", word.lower())
        if cleaned and cleaned not in stop_words:
            title_word = cleaned
            break

    return f"{surname}{year}{title_word}"


def _format_authors(work: Work) -> str:
    """Format authors for BibTeX.

    Args:
        work: Work with author data.

    Returns:
        BibTeX-formatted author string joined by ' and '.
    """
    names: list[str] = []
    for author in work.authors:
        given, family = split_author_name(author.name)
        if given and family:
            names.append(f"{family}, {given}")
        elif family:
            names.append(family)
    return " and ".join(names)


def work_to_bibtex_entry(work: Work) -> dict[str, str]:
    """Convert a Work to a bibtexparser v1 entry dict.

    Args:
        work: Work to convert.

    Returns:
        Dictionary suitable for bibtexparser v1 BibDatabase.
    """
    entry_type = _TYPE_MAP.get(work.work_type, "misc")
    key = _make_bibtex_key(work)

    entry: dict[str, str] = {
        "ENTRYTYPE": entry_type,
        "ID": key,
        "title": f"{{{work.title}}}",
        "author": _format_authors(work),
    }

    if work.year:
        entry["year"] = str(work.year)

    if work.venue:
        if entry_type == "article":
            entry["journal"] = work.venue
        elif entry_type == "inproceedings":
            entry["booktitle"] = work.venue

    if work.doi:
        entry["doi"] = work.doi

    if work.open_access_url:
        entry["url"] = work.open_access_url

    return entry


def works_to_bibtex(works: list[Work]) -> str:
    """Export a list of works as a BibTeX string.

    Args:
        works: List of Work objects to export.

    Returns:
        BibTeX-formatted string.
    """
    db = bibtexparser.bibdatabase.BibDatabase()
    db.entries = [work_to_bibtex_entry(w) for w in works]
    writer = BibTexWriter()
    return str(writer.write(db))
