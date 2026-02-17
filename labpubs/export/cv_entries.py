"""Formatted citation string export for CV and website use."""

from labpubs.models import Work
from labpubs.normalize import split_author_name


def _format_authors_apa(work: Work) -> str:
    """Format authors in APA style.

    Args:
        work: Work with author data.

    Returns:
        APA-formatted author string.
    """
    if not work.authors:
        return ""

    names: list[str] = []
    for author in work.authors:
        given, family = split_author_name(author.name)
        if given and family:
            initials = " ".join(
                f"{p[0]}." for p in given.split()
            )
            names.append(f"{family}, {initials}")
        elif family:
            names.append(family)

    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} & {names[1]}"
    if len(names) <= 20:
        return ", ".join(names[:-1]) + f", & {names[-1]}"
    return ", ".join(names[:19]) + f", ... {names[-1]}"


def _format_authors_chicago(work: Work) -> str:
    """Format authors in Chicago style.

    Args:
        work: Work with author data.

    Returns:
        Chicago-formatted author string.
    """
    if not work.authors:
        return ""

    names: list[str] = []
    for i, author in enumerate(work.authors):
        given, family = split_author_name(author.name)
        if given and family:
            if i == 0:
                names.append(f"{family}, {given}")
            else:
                names.append(f"{given} {family}")
        elif family:
            names.append(family)

    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    if len(names) <= 10:
        return ", ".join(names[:-1]) + f", and {names[-1]}"
    return ", ".join(names[:7]) + ", et al."


def format_apa(work: Work) -> str:
    """Format a work as an APA citation string.

    Args:
        work: Work to format.

    Returns:
        APA-formatted citation string.
    """
    authors = _format_authors_apa(work)
    year = f"({work.year})" if work.year else "(n.d.)"
    title = work.title

    parts = [f"{authors} {year}. {title}."]

    if work.venue:
        parts.append(f" {work.venue}.")

    if work.doi:
        parts.append(f" https://doi.org/{work.doi}")

    return "".join(parts)


def format_chicago(work: Work) -> str:
    """Format a work as a Chicago citation string.

    Args:
        work: Work to format.

    Returns:
        Chicago-formatted citation string.
    """
    authors = _format_authors_chicago(work)
    year = str(work.year) if work.year else "n.d."
    title = f'"{work.title}."'

    parts = [f"{authors}. {year}. {title}"]

    if work.venue:
        parts.append(f" {work.venue}.")

    if work.doi:
        parts.append(f" https://doi.org/{work.doi}.")

    return "".join(parts)


def format_work(work: Work, style: str = "apa") -> str:
    """Format a work as a citation string in the given style.

    Args:
        work: Work to format.
        style: Citation style ('apa' or 'chicago').

    Returns:
        Formatted citation string.

    Raises:
        ValueError: If the style is not supported.
    """
    formatters = {
        "apa": format_apa,
        "chicago": format_chicago,
    }
    formatter = formatters.get(style.lower())
    if formatter is None:
        raise ValueError(
            f"Unsupported style: {style}. "
            f"Supported: {', '.join(formatters)}"
        )
    return formatter(work)


def works_to_cv_entries(
    works: list[Work], style: str = "apa"
) -> list[str]:
    """Export works as formatted citation strings.

    Args:
        works: List of Work objects.
        style: Citation style ('apa' or 'chicago').

    Returns:
        List of formatted citation strings.
    """
    return [format_work(w, style) for w in works]
