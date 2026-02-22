"""Link orphaned scholar-alert works to researchers.

Google Scholar alert ingestion adds works to the database but may not
always create researcher_works linkages (e.g. when the email-time
researcher matching fails). This module resolves that by matching
alert email subjects to DB researcher records, validating against
work_authors, and inserting the linkages.
"""

import logging
import re
import sqlite3

logger = logging.getLogger(__name__)

# Alert subject names that differ from the canonical DB name.
NICKNAME_MAP: dict[str, str] = {
    "tanushree": "tanu",
}


def _normalize(name: str) -> str:
    """Lowercase, strip periods, collapse whitespace.

    Args:
        name: Raw name string.

    Returns:
        Normalized name.
    """
    return re.sub(r"\s+", " ", name.replace(".", "").strip().lower())


def match_alert_name_to_researcher(
    alert_name: str,
    researcher_names: list[str],
) -> str | None:
    """Match a scholar alert subject name to a researcher name.

    Handles middle initials ("Emma S. Spiro" -> "Emma Spiro"),
    nicknames ("Tanushree Mitra" -> "Tanu Mitra"), and
    hyphenated names ("Anna-Maria Gueorguieva" -> "Anna Gueorguieva").

    Args:
        alert_name: Name extracted from the alert email subject.
        researcher_names: Canonical researcher names from the DB.

    Returns:
        Matching researcher name, or None if no match found.
    """
    norm_alert = _normalize(alert_name)

    # Pass 1: exact normalized match
    for name in researcher_names:
        if _normalize(name) == norm_alert:
            return name

    # Pass 2: compare first + last tokens with prefix/nickname handling
    alert_parts = norm_alert.split()
    if len(alert_parts) < 2:
        return None

    alert_first = alert_parts[0].split("-")[0]
    alert_last = alert_parts[-1]
    alert_first_resolved = NICKNAME_MAP.get(alert_first, alert_first)

    for name in researcher_names:
        res_parts = _normalize(name).split()
        if len(res_parts) < 2:
            continue
        res_first = res_parts[0].split("-")[0]
        res_last = res_parts[-1]

        if res_last != alert_last:
            continue
        if (
            res_first == alert_first_resolved
            or alert_first_resolved.startswith(res_first)
            or res_first.startswith(alert_first_resolved)
        ):
            return name

    return None


def matches_author_initials(
    author_name: str,
    researcher_name: str,
) -> bool:
    """Check if a work author name matches a researcher.

    Handles abbreviated forms ("C Shah" -> "Chirag Shah"),
    multi-initial blocks ("BCG Lee" -> "Benjamin Charles Germain Lee"),
    full names ("Shahan Ali Memon" -> "Shahan Ali Memon"),
    and trailing ellipsis ("B Wen...").

    Args:
        author_name: Name from work_authors table.
        researcher_name: Full researcher name from researchers table.

    Returns:
        True if the names match.
    """
    cleaned = author_name.replace("\u2026", "").rstrip(".").strip()
    parts = cleaned.split()
    if len(parts) < 2:
        return False

    res_parts = researcher_name.split()
    if len(res_parts) < 2:
        return False

    if parts[-1].lower() != res_parts[-1].lower():
        return False

    given = parts[:-1]
    res_given = res_parts[:-1]

    # Abbreviated initials: single token, all alpha, up to 4 chars.
    if len(given) == 1 and given[0].isalpha() and len(given[0]) <= 4:
        expected = "".join(n[0].lower() for n in res_given)
        if given[0].lower().startswith(expected):
            return True

    # Full or partial name: compare first given-name tokens
    return given[0].lower() == res_given[0].lower()


def link_scholar_works(db_path: str) -> int:
    """Link orphaned scholar-alert works to researchers.

    Finds works ingested from scholar alerts that have no
    researcher_works linkage, resolves the researcher from the
    alert email subject, validates against work_authors, and
    inserts the linkages.

    Args:
        db_path: Path to the SQLite database.

    Returns:
        Number of new researcher_works linkages created.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")

        researchers: dict[str, int] = {
            row[1]: row[0] for row in conn.execute("SELECT id, name FROM researchers")
        }
        researcher_names = list(researchers.keys())

        rows = conn.execute(
            """
            SELECT DISTINCT
                   sai.work_id,
                   REPLACE(sae.subject, ' - new articles', '')
            FROM scholar_alert_items sai
            JOIN scholar_alert_emails sae
                ON sai.message_id = sae.message_id
            LEFT JOIN researcher_works rw
                ON sai.work_id = rw.work_id
            WHERE rw.work_id IS NULL
              AND sai.work_id IS NOT NULL
            """
        ).fetchall()

        if not rows:
            logger.info("No orphaned scholar-alert works found")
            return 0

        # Group alert names by work_id
        alerts_by_work: dict[int, list[str]] = {}
        for work_id, alert_name in rows:
            alerts_by_work.setdefault(work_id, []).append(alert_name)

        logger.info(
            "Found %d orphaned scholar-alert works",
            len(alerts_by_work),
        )

        orphan_ids = list(alerts_by_work.keys())
        placeholders = ",".join("?" * len(orphan_ids))
        author_rows = conn.execute(
            f"SELECT work_id, author_name FROM work_authors "
            f"WHERE work_id IN ({placeholders})",
            orphan_ids,
        ).fetchall()

        authors_by_work: dict[int, list[str]] = {}
        for work_id, author_name in author_rows:
            authors_by_work.setdefault(work_id, []).append(author_name)

        linkages: list[tuple[int, int]] = []
        for work_id, alert_names in alerts_by_work.items():
            work_authors = authors_by_work.get(work_id, [])

            for alert_name in alert_names:
                matched = match_alert_name_to_researcher(alert_name, researcher_names)
                if matched is None:
                    logger.warning(
                        "No researcher match for alert '%s' (work %d)",
                        alert_name,
                        work_id,
                    )
                    continue

                if work_authors and not any(
                    matches_author_initials(a, matched) for a in work_authors
                ):
                    logger.debug(
                        "Author validation failed for '%s' on work %d (authors: %s)",
                        matched,
                        work_id,
                        work_authors,
                    )
                    continue

                linkages.append((researchers[matched], work_id))

        if not linkages:
            logger.info("No new linkages to create")
            return 0

        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO researcher_works "
            "(researcher_id, work_id) VALUES (?, ?)",
            linkages,
        )
        conn.commit()
        count = conn.total_changes - before
        logger.info("Created %d researcher_works linkages", count)
        return count
