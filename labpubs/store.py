"""SQLite storage layer for labpubs.

Persists researchers, works, and sync history in a local SQLite database.
"""

import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path

import orjson

from labpubs.models import (
    Author,
    Award,
    Funder,
    Investigator,
    LinkedResource,
    Source,
    SyncResult,
    Work,
    WorkType,
)
from labpubs.normalize import normalize_title as _normalize_title

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS researchers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    openalex_id TEXT,
    semantic_scholar_id TEXT,
    orcid TEXT,
    affiliation TEXT,
    config_key TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY,
    doi TEXT UNIQUE,
    title TEXT NOT NULL,
    title_normalized TEXT NOT NULL,
    publication_date TEXT,
    year INTEGER,
    venue TEXT,
    work_type TEXT,
    abstract TEXT,
    openalex_id TEXT,
    semantic_scholar_id TEXT,
    open_access INTEGER,
    open_access_url TEXT,
    citation_count INTEGER,
    tldr TEXT,
    sources TEXT,
    first_seen TEXT,
    last_updated TEXT,
    raw_metadata TEXT,
    verified INTEGER DEFAULT 0,
    verified_by TEXT,
    verified_at TEXT,
    verification_issue_url TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS work_authors (
    work_id INTEGER REFERENCES works(id),
    author_name TEXT NOT NULL,
    author_openalex_id TEXT,
    author_semantic_scholar_id TEXT,
    author_orcid TEXT,
    author_affiliation TEXT,
    author_position INTEGER NOT NULL,
    PRIMARY KEY (work_id, author_position)
);

CREATE TABLE IF NOT EXISTS researcher_works (
    researcher_id INTEGER REFERENCES researchers(id),
    work_id INTEGER REFERENCES works(id),
    PRIMARY KEY (researcher_id, work_id)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    researchers_checked INTEGER,
    new_works_count INTEGER,
    errors TEXT
);

CREATE INDEX IF NOT EXISTS idx_works_doi ON works(doi);
CREATE INDEX IF NOT EXISTS idx_works_title ON works(title_normalized);
CREATE INDEX IF NOT EXISTS idx_works_year ON works(year);
CREATE TABLE IF NOT EXISTS funders (
    id INTEGER PRIMARY KEY,
    openalex_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    ror_id TEXT,
    crossref_id TEXT,
    country TEXT,
    alternate_names TEXT
);

CREATE TABLE IF NOT EXISTS awards (
    id INTEGER PRIMARY KEY,
    openalex_id TEXT UNIQUE NOT NULL,
    display_name TEXT,
    description TEXT,
    funder_award_id TEXT,
    funder_id INTEGER REFERENCES funders(id),
    doi TEXT,
    amount INTEGER,
    funding_type TEXT,
    start_year INTEGER,
    lead_investigator_orcid TEXT,
    lead_investigator_name TEXT,
    funded_outputs_count INTEGER
);

CREATE TABLE IF NOT EXISTS award_investigators (
    award_id INTEGER REFERENCES awards(id),
    given_name TEXT,
    family_name TEXT,
    orcid TEXT,
    affiliation_name TEXT,
    affiliation_country TEXT,
    position INTEGER NOT NULL,
    PRIMARY KEY (award_id, position)
);

CREATE TABLE IF NOT EXISTS work_awards (
    work_id INTEGER REFERENCES works(id),
    award_id INTEGER REFERENCES awards(id),
    PRIMARY KEY (work_id, award_id)
);

CREATE TABLE IF NOT EXISTS work_funders (
    work_id INTEGER REFERENCES works(id),
    funder_id INTEGER REFERENCES funders(id),
    PRIMARY KEY (work_id, funder_id)
);

CREATE TABLE IF NOT EXISTS linked_resources (
    id INTEGER PRIMARY KEY,
    work_id INTEGER REFERENCES works(id),
    url TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    name TEXT,
    description TEXT,
    added_by TEXT,
    added_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_works_openalex ON works(openalex_id);
CREATE INDEX IF NOT EXISTS idx_works_s2 ON works(semantic_scholar_id);
CREATE INDEX IF NOT EXISTS idx_works_verified ON works(verified);
CREATE INDEX IF NOT EXISTS idx_researcher_works_work
    ON researcher_works(work_id);
CREATE INDEX IF NOT EXISTS idx_awards_funder ON awards(funder_id);
CREATE INDEX IF NOT EXISTS idx_awards_funder_award_id
    ON awards(funder_award_id);
CREATE INDEX IF NOT EXISTS idx_funders_openalex
    ON funders(openalex_id);
CREATE INDEX IF NOT EXISTS idx_linked_resources_work
    ON linked_resources(work_id);

CREATE TABLE IF NOT EXISTS scholar_alert_emails (
    message_id TEXT PRIMARY KEY,
    internal_date TEXT,
    gmail_uid TEXT,
    subject TEXT,
    from_addr TEXT,
    to_addr TEXT,
    processed_at TEXT NOT NULL,
    raw_html TEXT
);

CREATE TABLE IF NOT EXISTS scholar_alert_items (
    id INTEGER PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES scholar_alert_emails(message_id),
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    authors TEXT,
    venue TEXT,
    year INTEGER,
    target_url TEXT,
    scholar_url TEXT,
    work_id INTEGER REFERENCES works(id),
    created_at TEXT NOT NULL,
    UNIQUE(message_id, position)
);

CREATE INDEX IF NOT EXISTS idx_scholar_alert_items_work
    ON scholar_alert_items(work_id);
"""

_MIGRATION_ADD_VERIFICATION = """
ALTER TABLE works ADD COLUMN verified INTEGER DEFAULT 0;
ALTER TABLE works ADD COLUMN verified_by TEXT;
ALTER TABLE works ADD COLUMN verified_at TEXT;
ALTER TABLE works ADD COLUMN verification_issue_url TEXT;
ALTER TABLE works ADD COLUMN notes TEXT;
"""

_MIGRATION_ADD_RESEARCHER_FIELDS = """
ALTER TABLE researchers ADD COLUMN start_date TEXT;
ALTER TABLE researchers ADD COLUMN end_date TEXT;
ALTER TABLE researchers ADD COLUMN groups TEXT;
"""


def _work_to_row(work: Work) -> dict[str, str | int | None]:
    """Convert a Work model to a dict suitable for DB insertion.

    Args:
        work: Work instance.

    Returns:
        Column-name to value mapping.
    """
    now = datetime.utcnow().isoformat()
    return {
        "doi": work.doi,
        "title": work.title,
        "title_normalized": _normalize_title(work.title),
        "publication_date": work.publication_date.isoformat()
        if work.publication_date
        else None,
        "year": work.year,
        "venue": work.venue,
        "work_type": work.work_type.value if work.work_type else None,
        "abstract": work.abstract,
        "openalex_id": work.openalex_id,
        "semantic_scholar_id": work.semantic_scholar_id,
        "open_access": int(work.open_access) if work.open_access is not None else None,
        "open_access_url": work.open_access_url,
        "citation_count": work.citation_count,
        "tldr": work.tldr,
        "sources": orjson.dumps([s.value for s in work.sources]).decode(),
        "verified": int(work.verified),
        "verified_by": work.verified_by,
        "verified_at": work.verified_at.isoformat() if work.verified_at else None,
        "verification_issue_url": work.verification_issue_url,
        "notes": work.notes,
        "first_seen": work.first_seen.isoformat() if work.first_seen else now,
        "last_updated": now,
    }


def _row_to_work(row: sqlite3.Row) -> Work:
    """Convert a database row to a Work model.

    Args:
        row: sqlite3.Row from the works table.

    Returns:
        Populated Work instance.
    """
    sources_raw = row["sources"]
    sources = []
    if sources_raw:
        for s in orjson.loads(sources_raw):
            try:
                sources.append(Source(s))
            except ValueError:
                pass

    pub_date = None
    if row["publication_date"]:
        try:
            pub_date = date.fromisoformat(row["publication_date"])
        except ValueError:
            pass

    first_seen = None
    if row["first_seen"]:
        try:
            first_seen = datetime.fromisoformat(row["first_seen"])
        except ValueError:
            pass

    last_updated = None
    if row["last_updated"]:
        try:
            last_updated = datetime.fromisoformat(row["last_updated"])
        except ValueError:
            pass

    wt = WorkType.OTHER
    if row["work_type"]:
        try:
            wt = WorkType(row["work_type"])
        except ValueError:
            pass

    oa = None
    if row["open_access"] is not None:
        oa = bool(row["open_access"])

    verified_at = None
    if row["verified_at"]:
        try:
            verified_at = datetime.fromisoformat(row["verified_at"])
        except ValueError:
            pass

    return Work(
        doi=row["doi"],
        title=row["title"],
        publication_date=pub_date,
        year=row["year"],
        venue=row["venue"],
        work_type=wt,
        abstract=row["abstract"],
        openalex_id=row["openalex_id"],
        semantic_scholar_id=row["semantic_scholar_id"],
        open_access=oa,
        open_access_url=row["open_access_url"],
        citation_count=row["citation_count"],
        tldr=row["tldr"],
        verified=bool(row["verified"]) if row["verified"] else False,
        verified_by=row["verified_by"],
        verified_at=verified_at,
        verification_issue_url=row["verification_issue_url"],
        notes=row["notes"],
        sources=sources,
        first_seen=first_seen,
        last_updated=last_updated,
    )


class Store:
    """SQLite-backed persistence for labpubs data."""

    def __init__(self, db_path: str | Path) -> None:
        """Initialize the store and create schema if needed.

        Args:
            db_path: Path to the SQLite database file.
        """
        self._db_path = Path(db_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA cache_size = -64000")
        self._conn.executescript(_SCHEMA)
        self._run_migrations()
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def _run_migrations(self) -> None:
        """Apply schema migrations for existing databases."""
        cursor = self._conn.execute("PRAGMA table_info(works)")
        columns = {row["name"] for row in cursor}
        if "verified" not in columns:
            for stmt in _MIGRATION_ADD_VERIFICATION.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    self._conn.execute(stmt)

        cursor = self._conn.execute("PRAGMA table_info(researchers)")
        r_columns = {row["name"] for row in cursor}
        if "start_date" not in r_columns:
            for stmt in _MIGRATION_ADD_RESEARCHER_FIELDS.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    self._conn.execute(stmt)

    def upsert_researcher(
        self,
        name: str,
        config_key: str,
        openalex_id: str | None = None,
        semantic_scholar_id: str | None = None,
        orcid: str | None = None,
        affiliation: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        groups: list[str] | None = None,
    ) -> int:
        """Insert or update a researcher record.

        Args:
            name: Researcher display name.
            config_key: Unique key from the YAML config.
            openalex_id: OpenAlex author ID.
            semantic_scholar_id: Semantic Scholar author ID.
            orcid: ORCID identifier.
            affiliation: Institutional affiliation.
            start_date: Date the researcher joined (ISO format).
            end_date: Date the researcher left (ISO format, None=active).
            groups: List of group names the researcher belongs to.

        Returns:
            Database row ID for the researcher.
        """
        groups_json = orjson.dumps(groups).decode() if groups else None
        cursor = self._conn.execute(
            "SELECT id FROM researchers WHERE config_key = ?",
            (config_key,),
        )
        existing = cursor.fetchone()
        if existing:
            self._conn.execute(
                """UPDATE researchers
                   SET name = ?, openalex_id = ?,
                       semantic_scholar_id = ?, orcid = ?,
                       affiliation = ?, start_date = ?,
                       end_date = ?, groups = ?
                   WHERE config_key = ?""",
                (
                    name,
                    openalex_id,
                    semantic_scholar_id,
                    orcid,
                    affiliation,
                    start_date,
                    end_date,
                    groups_json,
                    config_key,
                ),
            )
            self._conn.commit()
            return int(existing["id"])

        cursor = self._conn.execute(
            """INSERT INTO researchers
               (name, openalex_id, semantic_scholar_id, orcid,
                affiliation, config_key, start_date, end_date,
                groups)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                openalex_id,
                semantic_scholar_id,
                orcid,
                affiliation,
                config_key,
                start_date,
                end_date,
                groups_json,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def update_researcher_source_id(
        self,
        config_key: str,
        openalex_id: str | None = None,
        semantic_scholar_id: str | None = None,
    ) -> None:
        """Update a researcher's source-specific author ID in the DB.

        Only updates the fields that are provided (non-None).
        Does NOT touch the YAML config file.

        Args:
            config_key: Unique key identifying the researcher.
            openalex_id: New OpenAlex author ID (or None to skip).
            semantic_scholar_id: New S2 author ID (or None to skip).
        """
        updates: list[str] = []
        params: list[str] = []
        if openalex_id is not None:
            updates.append("openalex_id = ?")
            params.append(openalex_id)
        if semantic_scholar_id is not None:
            updates.append("semantic_scholar_id = ?")
            params.append(semantic_scholar_id)
        if not updates:
            return
        params.append(config_key)
        self._conn.execute(
            f"UPDATE researchers SET {', '.join(updates)} WHERE config_key = ?",
            params,
        )
        self._conn.commit()

    def insert_work(self, work: Work) -> int:
        """Insert a new work into the database.

        Args:
            work: Work to insert.

        Returns:
            Database row ID for the work.
        """
        row = _work_to_row(work)
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        cursor = self._conn.execute(
            f"INSERT INTO works ({cols}) VALUES ({placeholders})",
            tuple(row.values()),
        )
        work_id: int = cursor.lastrowid  # type: ignore[assignment]
        self._insert_work_authors(work_id, work.authors)
        self._persist_work_funding(work_id, work)
        self._persist_linked_resources(work_id, work.linked_resources)
        self._conn.commit()
        return work_id

    def _insert_work_authors(self, work_id: int, authors: list[Author]) -> None:
        """Insert author records for a work.

        Args:
            work_id: Database ID of the work.
            authors: List of authors.
        """
        for i, author in enumerate(authors):
            self._conn.execute(
                """INSERT OR REPLACE INTO work_authors
                   (work_id, author_name, author_openalex_id,
                    author_semantic_scholar_id, author_orcid,
                    author_affiliation, author_position)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    work_id,
                    author.name,
                    author.openalex_id,
                    author.semantic_scholar_id,
                    author.orcid,
                    author.affiliation,
                    i,
                ),
            )

    def update_work(self, work_id: int, work: Work) -> None:
        """Update an existing work with new metadata.

        Args:
            work_id: Database row ID.
            work: Updated Work data.
        """
        row = _work_to_row(work)
        del row["first_seen"]  # preserve original first_seen
        set_clause = ", ".join(f"{k} = ?" for k in row)
        self._conn.execute(
            f"UPDATE works SET {set_clause} WHERE id = ?",
            (*row.values(), work_id),
        )
        self._conn.execute("DELETE FROM work_authors WHERE work_id = ?", (work_id,))
        self._insert_work_authors(work_id, work.authors)
        self._conn.execute("DELETE FROM work_awards WHERE work_id = ?", (work_id,))
        self._conn.execute("DELETE FROM work_funders WHERE work_id = ?", (work_id,))
        self._persist_work_funding(work_id, work)
        self._conn.execute(
            "DELETE FROM linked_resources WHERE work_id = ?",
            (work_id,),
        )
        self._persist_linked_resources(work_id, work.linked_resources)
        self._conn.commit()

    def link_researcher_work(self, researcher_id: int, work_id: int) -> None:
        """Create a researcher-work association.

        Args:
            researcher_id: Researcher row ID.
            work_id: Work row ID.
        """
        self._conn.execute(
            """INSERT OR IGNORE INTO researcher_works
               (researcher_id, work_id) VALUES (?, ?)""",
            (researcher_id, work_id),
        )
        self._conn.commit()

    def find_work_by_doi(self, doi: str) -> tuple[int, Work] | None:
        """Look up a work by DOI.

        Args:
            doi: Normalized DOI string.

        Returns:
            Tuple of (row_id, Work) or None if not found.
        """
        cursor = self._conn.execute("SELECT * FROM works WHERE doi = ?", (doi,))
        row = cursor.fetchone()
        if row is None:
            return None
        work = self._hydrate_work(row)
        return row["id"], work

    def find_work_by_title(self, title: str) -> tuple[int, Work] | None:
        """Look up a work by normalized title (exact match).

        Args:
            title: Raw title to normalize and search for.

        Returns:
            Tuple of (row_id, Work) or None if not found.
        """
        normalized = _normalize_title(title)
        cursor = self._conn.execute(
            "SELECT * FROM works WHERE title_normalized = ?",
            (normalized,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        work = self._hydrate_work(row)
        return row["id"], work

    def get_all_works_for_matching(
        self,
    ) -> list[tuple[int, str, str | None, int | None, list[str]]]:
        """Get minimal work data needed for deduplication matching.

        Returns:
            List of (id, title_normalized, doi, year,
            author_surnames).
        """
        cursor = self._conn.execute("SELECT id, title_normalized, doi, year FROM works")
        results = []
        for row in cursor:
            authors = self._conn.execute(
                """SELECT author_name FROM work_authors
                   WHERE work_id = ? ORDER BY author_position""",
                (row["id"],),
            ).fetchall()
            surnames = [
                a["author_name"].split()[-1].lower()
                for a in authors
                if a["author_name"]
            ]
            results.append(
                (
                    row["id"],
                    row["title_normalized"],
                    row["doi"],
                    row["year"],
                    surnames,
                )
            )
        return results

    def _load_work_authors(self, work_id: int) -> list[Author]:
        """Load authors for a specific work.

        Args:
            work_id: Database row ID.

        Returns:
            Ordered list of Author objects.
        """
        cursor = self._conn.execute(
            """SELECT * FROM work_authors
               WHERE work_id = ?
               ORDER BY author_position""",
            (work_id,),
        )
        return [
            Author(
                name=row["author_name"],
                openalex_id=row["author_openalex_id"],
                semantic_scholar_id=row["author_semantic_scholar_id"],
                orcid=row["author_orcid"],
                affiliation=row["author_affiliation"],
            )
            for row in cursor
        ]

    def _persist_work_funding(self, work_id: int, work: Work) -> None:
        """Persist funding data (awards/funders) for a work.

        Args:
            work_id: Database ID of the work.
            work: Work with funding data.
        """
        for award in work.awards:
            funder_db_id = None
            if award.funder:
                funder_db_id = self.upsert_funder(award.funder)
            award_db_id = self.upsert_award(award, funder_db_id)
            self._conn.execute(
                """INSERT OR IGNORE INTO work_awards
                   (work_id, award_id) VALUES (?, ?)""",
                (work_id, award_db_id),
            )

        for funder in work.funders:
            funder_db_id = self.upsert_funder(funder)
            self._conn.execute(
                """INSERT OR IGNORE INTO work_funders
                   (work_id, funder_id) VALUES (?, ?)""",
                (work_id, funder_db_id),
            )

    def upsert_funder(self, funder: Funder) -> int:
        """Insert or update a funder record.

        Args:
            funder: Funder model instance.

        Returns:
            Database row ID.
        """
        cursor = self._conn.execute(
            "SELECT id FROM funders WHERE openalex_id = ?",
            (funder.openalex_id,),
        )
        existing = cursor.fetchone()
        alt_names = (
            orjson.dumps(funder.alternate_names).decode()
            if funder.alternate_names
            else None
        )
        if existing:
            self._conn.execute(
                """UPDATE funders SET name = ?, ror_id = ?,
                   crossref_id = ?, country = ?,
                   alternate_names = ?
                   WHERE openalex_id = ?""",
                (
                    funder.name,
                    funder.ror_id,
                    funder.crossref_id,
                    funder.country,
                    alt_names,
                    funder.openalex_id,
                ),
            )
            return int(existing["id"])

        cursor = self._conn.execute(
            """INSERT INTO funders
               (openalex_id, name, ror_id, crossref_id,
                country, alternate_names)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                funder.openalex_id,
                funder.name,
                funder.ror_id,
                funder.crossref_id,
                funder.country,
                alt_names,
            ),
        )
        return cursor.lastrowid  # type: ignore[return-value]

    def upsert_award(self, award: Award, funder_db_id: int | None = None) -> int:
        """Insert or update an award record.

        Args:
            award: Award model instance.
            funder_db_id: Database ID of the associated funder.

        Returns:
            Database row ID.
        """
        cursor = self._conn.execute(
            "SELECT id FROM awards WHERE openalex_id = ?",
            (award.openalex_id,),
        )
        existing = cursor.fetchone()

        li_name = None
        li_orcid = None
        if award.lead_investigator:
            parts = []
            if award.lead_investigator.given_name:
                parts.append(award.lead_investigator.given_name)
            if award.lead_investigator.family_name:
                parts.append(award.lead_investigator.family_name)
            li_name = " ".join(parts) if parts else None
            li_orcid = award.lead_investigator.orcid

        if existing:
            self._conn.execute(
                """UPDATE awards SET display_name = ?,
                   description = ?, funder_award_id = ?,
                   funder_id = ?, doi = ?, amount = ?,
                   funding_type = ?, start_year = ?,
                   lead_investigator_orcid = ?,
                   lead_investigator_name = ?,
                   funded_outputs_count = ?
                   WHERE openalex_id = ?""",
                (
                    award.display_name,
                    award.description,
                    award.funder_award_id,
                    funder_db_id,
                    award.doi,
                    award.amount,
                    award.funding_type,
                    award.start_year,
                    li_orcid,
                    li_name,
                    award.funded_outputs_count,
                    award.openalex_id,
                ),
            )
            award_db_id = existing["id"]
        else:
            cursor = self._conn.execute(
                """INSERT INTO awards
                   (openalex_id, display_name, description,
                    funder_award_id, funder_id, doi, amount,
                    funding_type, start_year,
                    lead_investigator_orcid,
                    lead_investigator_name,
                    funded_outputs_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    award.openalex_id,
                    award.display_name,
                    award.description,
                    award.funder_award_id,
                    funder_db_id,
                    award.doi,
                    award.amount,
                    award.funding_type,
                    award.start_year,
                    li_orcid,
                    li_name,
                    award.funded_outputs_count,
                ),
            )
            award_db_id = cursor.lastrowid

        # Persist investigators
        self._conn.execute(
            "DELETE FROM award_investigators WHERE award_id = ?",
            (award_db_id,),
        )
        for i, inv in enumerate(award.investigators):
            self._conn.execute(
                """INSERT INTO award_investigators
                   (award_id, given_name, family_name, orcid,
                    affiliation_name, affiliation_country, position)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    award_db_id,
                    inv.given_name,
                    inv.family_name,
                    inv.orcid,
                    inv.affiliation_name,
                    inv.affiliation_country,
                    i,
                ),
            )

        return int(award_db_id)

    def _load_work_awards(self, work_id: int) -> list[Award]:
        """Load awards linked to a work.

        Args:
            work_id: Database row ID.

        Returns:
            List of Award objects.
        """
        cursor = self._conn.execute(
            """SELECT a.* FROM awards a
               JOIN work_awards wa ON a.id = wa.award_id
               WHERE wa.work_id = ?""",
            (work_id,),
        )
        return [self._row_to_award(row) for row in cursor]

    def _load_work_funders(self, work_id: int) -> list[Funder]:
        """Load funders linked to a work.

        Args:
            work_id: Database row ID.

        Returns:
            List of Funder objects.
        """
        cursor = self._conn.execute(
            """SELECT f.* FROM funders f
               JOIN work_funders wf ON f.id = wf.funder_id
               WHERE wf.work_id = ?""",
            (work_id,),
        )
        return [self._row_to_funder(row) for row in cursor]

    def _load_funder(self, funder_db_id: int) -> Funder | None:
        """Load a funder by database ID.

        Args:
            funder_db_id: Database row ID.

        Returns:
            Funder object or None.
        """
        cursor = self._conn.execute(
            "SELECT * FROM funders WHERE id = ?",
            (funder_db_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_funder(row)

    def _row_to_funder(self, row: sqlite3.Row) -> Funder:
        """Convert a DB row to a Funder model.

        Args:
            row: sqlite3.Row from funders table.

        Returns:
            Funder instance.
        """
        alt_names: list[str] = []
        if row["alternate_names"]:
            alt_names = orjson.loads(row["alternate_names"])
        return Funder(
            openalex_id=row["openalex_id"],
            name=row["name"],
            ror_id=row["ror_id"],
            crossref_id=row["crossref_id"],
            country=row["country"],
            alternate_names=alt_names,
        )

    def _row_to_award(self, row: sqlite3.Row) -> Award:
        """Convert a DB row to an Award model.

        Args:
            row: sqlite3.Row from awards table.

        Returns:
            Award instance with funder and investigators loaded.
        """
        funder = None
        if row["funder_id"]:
            funder = self._load_funder(row["funder_id"])
        li = None
        if row["lead_investigator_name"]:
            parts = row["lead_investigator_name"].split(maxsplit=1)
            li = Investigator(
                given_name=parts[0] if parts else None,
                family_name=parts[1] if len(parts) > 1 else None,
                orcid=row["lead_investigator_orcid"],
            )
        return Award(
            openalex_id=row["openalex_id"],
            display_name=row["display_name"],
            description=row["description"],
            funder_award_id=row["funder_award_id"],
            funder=funder,
            doi=row["doi"],
            amount=row["amount"],
            funding_type=row["funding_type"],
            start_year=row["start_year"],
            lead_investigator=li,
            investigators=self._load_award_investigators(row["id"]),
            funded_outputs_count=row["funded_outputs_count"],
        )

    def _load_award_investigators(self, award_db_id: int) -> list[Investigator]:
        """Load investigators for an award.

        Args:
            award_db_id: Database row ID of the award.

        Returns:
            Ordered list of Investigator objects.
        """
        cursor = self._conn.execute(
            """SELECT * FROM award_investigators
               WHERE award_id = ?
               ORDER BY position""",
            (award_db_id,),
        )
        return [
            Investigator(
                given_name=row["given_name"],
                family_name=row["family_name"],
                orcid=row["orcid"],
                affiliation_name=row["affiliation_name"],
                affiliation_country=row["affiliation_country"],
            )
            for row in cursor
        ]

    def _hydrate_work(self, row: sqlite3.Row) -> Work:
        """Convert a DB row to a fully hydrated Work model.

        Args:
            row: sqlite3.Row from works table.

        Returns:
            Work with authors, awards, funders, and resources loaded.
        """
        work = _row_to_work(row)
        work.authors = self._load_work_authors(row["id"])
        work.awards = self._load_work_awards(row["id"])
        work.funders = self._load_work_funders(row["id"])
        work.linked_resources = self._load_linked_resources(row["id"])
        return work

    def get_all_funders(self) -> list[Funder]:
        """Get all funders in the database.

        Returns:
            List of Funder objects.
        """
        cursor = self._conn.execute("SELECT * FROM funders ORDER BY name")
        return [self._row_to_funder(row) for row in cursor]

    def get_all_awards(self, funder_name: str | None = None) -> list[Award]:
        """Get all awards, optionally filtered by funder.

        Args:
            funder_name: Case-insensitive partial funder name match.

        Returns:
            List of Award objects.
        """
        if funder_name:
            cursor = self._conn.execute(
                """SELECT a.* FROM awards a
                   JOIN funders f ON a.funder_id = f.id
                   WHERE LOWER(f.name) LIKE ?
                   ORDER BY a.start_year DESC""",
                (f"%{funder_name.lower()}%",),
            )
        else:
            cursor = self._conn.execute("SELECT * FROM awards ORDER BY start_year DESC")

        return [self._row_to_award(row) for row in cursor]

    def get_award_by_funder_award_id(self, funder_award_id: str) -> Award | None:
        """Look up an award by its funder-assigned grant number.

        Args:
            funder_award_id: Grant number (case-insensitive).

        Returns:
            Award or None.
        """
        cursor = self._conn.execute(
            """SELECT * FROM awards
               WHERE LOWER(funder_award_id) = ?""",
            (funder_award_id.lower().lstrip("0"),),
        )
        row = cursor.fetchone()
        if row is None:
            # Try without stripping zeros
            cursor = self._conn.execute(
                """SELECT * FROM awards
                   WHERE LOWER(funder_award_id) = ?""",
                (funder_award_id.lower(),),
            )
            row = cursor.fetchone()
        if row is None:
            return None

        return self._row_to_award(row)

    def get_works_by_funder(
        self, funder_name: str, year: int | None = None
    ) -> list[Work]:
        """Get works funded by a funder (name match).

        Args:
            funder_name: Case-insensitive partial funder name.
            year: Optional year filter.

        Returns:
            List of Work objects.
        """
        query = """
            SELECT DISTINCT w.* FROM works w
            LEFT JOIN work_funders wf ON w.id = wf.work_id
            LEFT JOIN funders f ON wf.funder_id = f.id
            LEFT JOIN work_awards wa ON w.id = wa.work_id
            LEFT JOIN awards a ON wa.award_id = a.id
            LEFT JOIN funders af ON a.funder_id = af.id
            WHERE (LOWER(f.name) LIKE ?
                   OR LOWER(af.name) LIKE ?)
        """
        params: list[str | int] = [
            f"%{funder_name.lower()}%",
            f"%{funder_name.lower()}%",
        ]
        if year:
            query += " AND w.year = ?"
            params.append(year)
        query += " ORDER BY w.year DESC, w.title"

        cursor = self._conn.execute(query, params)
        return [self._hydrate_work(row) for row in cursor]

    def get_works_by_award(self, award_id: str) -> list[Work]:
        """Get works linked to a specific grant number.

        Args:
            award_id: Funder-assigned grant number.

        Returns:
            List of Work objects.
        """
        cursor = self._conn.execute(
            """SELECT w.* FROM works w
               JOIN work_awards wa ON w.id = wa.work_id
               JOIN awards a ON wa.award_id = a.id
               WHERE LOWER(a.funder_award_id) = ?
               ORDER BY w.year DESC, w.title""",
            (award_id.lower(),),
        )
        return [self._hydrate_work(row) for row in cursor]

    def get_funder_publication_counts(
        self,
    ) -> list[tuple[Funder, int]]:
        """Get all funders with their publication counts.

        Returns:
            List of (Funder, count) tuples sorted by count desc.
        """
        cursor = self._conn.execute(
            """SELECT f.*, COUNT(DISTINCT wf.work_id) as cnt
               FROM funders f
               LEFT JOIN work_funders wf ON f.id = wf.funder_id
               GROUP BY f.id
               ORDER BY cnt DESC, f.name"""
        )
        results: list[tuple[Funder, int]] = []
        for row in cursor:
            results.append((self._row_to_funder(row), row["cnt"]))
        return results

    def get_works(
        self,
        researcher_id: int | None = None,
        since: date | None = None,
        year: int | None = None,
        work_type: WorkType | None = None,
    ) -> list[Work]:
        """Query works with optional filters.

        Args:
            researcher_id: Filter by researcher DB ID.
            since: Filter by publication date >= this date.
            year: Filter by publication year.
            work_type: Filter by work type.

        Returns:
            List of matching Work objects.
        """
        query = "SELECT w.* FROM works w"
        conditions: list[str] = []
        params: list[str | int] = []

        if researcher_id is not None:
            query += " JOIN researcher_works rw ON w.id = rw.work_id"
            conditions.append("rw.researcher_id = ?")
            params.append(researcher_id)

        if since:
            conditions.append("w.publication_date >= ?")
            params.append(since.isoformat())

        if year:
            conditions.append("w.year = ?")
            params.append(year)

        if work_type:
            conditions.append("w.work_type = ?")
            params.append(work_type.value)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY w.year DESC, w.title"

        cursor = self._conn.execute(query, params)
        works = []
        for row in cursor:
            works.append(self._hydrate_work(row))
        return works

    def get_new_works(self, since: datetime | None = None) -> list[Work]:
        """Get works first seen after a given timestamp.

        Args:
            since: Only return works first seen after this datetime.

        Returns:
            List of newly discovered Work objects.
        """
        if since is None:
            return []
        cursor = self._conn.execute(
            """SELECT * FROM works
               WHERE first_seen >= ?
               ORDER BY first_seen DESC""",
            (since.isoformat(),),
        )
        works = []
        for row in cursor:
            works.append(self._hydrate_work(row))
        return works

    def search_works(self, query: str, limit: int = 20) -> list[Work]:
        """Full-text search across titles and abstracts.

        Args:
            query: Search terms.
            limit: Maximum results.

        Returns:
            Matching Work objects.
        """
        pattern = f"%{query}%"
        cursor = self._conn.execute(
            """SELECT * FROM works
               WHERE title LIKE ? OR abstract LIKE ?
               ORDER BY year DESC
               LIMIT ?""",
            (pattern, pattern, limit),
        )
        works = []
        for row in cursor:
            works.append(self._hydrate_work(row))
        return works

    def get_researchers(self) -> list[Author]:
        """Get all tracked researchers.

        Returns:
            List of Author objects for configured researchers.
        """
        cursor = self._conn.execute("SELECT * FROM researchers ORDER BY name")
        results: list[Author] = []
        for row in cursor:
            groups_raw = row["groups"]
            groups = orjson.loads(groups_raw) if groups_raw else []
            results.append(
                Author(
                    name=row["name"],
                    openalex_id=row["openalex_id"],
                    semantic_scholar_id=row["semantic_scholar_id"],
                    orcid=row["orcid"],
                    affiliation=row["affiliation"],
                    is_lab_member=True,
                    start_date=row["start_date"],
                    end_date=row["end_date"],
                    groups=groups,
                )
            )
        return results

    def get_researcher_id(self, name: str) -> int | None:
        """Find a researcher ID by name (case-insensitive partial match).

        Args:
            name: Researcher name or partial name.

        Returns:
            Researcher DB ID or None.
        """
        cursor = self._conn.execute(
            "SELECT id FROM researchers WHERE LOWER(name) LIKE ?",
            (f"%{name.lower()}%",),
        )
        row = cursor.fetchone()
        return row["id"] if row else None

    def get_last_sync_date(self) -> datetime | None:
        """Get the timestamp of the most recent sync.

        Returns:
            Datetime of last sync, or None if never synced.
        """
        cursor = self._conn.execute(
            "SELECT timestamp FROM sync_log ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row is None:
            return None
        try:
            return datetime.fromisoformat(row["timestamp"])
        except ValueError:
            return None

    def log_sync(self, result: SyncResult) -> None:
        """Record a sync operation in the sync log.

        Args:
            result: SyncResult to log.
        """
        self._conn.execute(
            """INSERT INTO sync_log
               (timestamp, researchers_checked, new_works_count, errors)
               VALUES (?, ?, ?, ?)""",
            (
                result.timestamp.isoformat(),
                result.researchers_checked,
                len(result.new_works),
                orjson.dumps(result.errors).decode() if result.errors else None,
            ),
        )
        self._conn.commit()

    def _load_linked_resources(self, work_id: int) -> list[LinkedResource]:
        """Load linked resources for a work.

        Args:
            work_id: Database row ID.

        Returns:
            List of LinkedResource objects.
        """
        cursor = self._conn.execute(
            """SELECT url, resource_type, name, description
               FROM linked_resources
               WHERE work_id = ?
               ORDER BY id""",
            (work_id,),
        )
        return [
            LinkedResource(
                url=row["url"],
                resource_type=row["resource_type"],
                name=row["name"],
                description=row["description"],
            )
            for row in cursor
        ]

    def _persist_linked_resources(
        self,
        work_id: int,
        resources: list[LinkedResource],
    ) -> None:
        """Persist linked resources for a work.

        Args:
            work_id: Database ID of the work.
            resources: List of LinkedResource objects.
        """
        now = datetime.utcnow().isoformat()
        for res in resources:
            self._conn.execute(
                """INSERT INTO linked_resources
                   (work_id, url, resource_type, name,
                    description, added_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    work_id,
                    res.url,
                    res.resource_type,
                    res.name,
                    res.description,
                    now,
                ),
            )

    def add_linked_resource(
        self,
        work_id: int,
        resource: LinkedResource,
        added_by: str | None = None,
    ) -> None:
        """Add a single linked resource to a work.

        Args:
            work_id: Database row ID.
            resource: LinkedResource to add.
            added_by: GitHub username of who added it.
        """
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            """INSERT INTO linked_resources
               (work_id, url, resource_type, name,
                description, added_by, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                work_id,
                resource.url,
                resource.resource_type,
                resource.name,
                resource.description,
                added_by,
                now,
            ),
        )
        self._conn.commit()

    def mark_work_verified(
        self,
        work_id: int,
        verified_by: str | None = None,
        issue_url: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Mark a work as verified.

        Args:
            work_id: Database row ID.
            verified_by: GitHub username of verifier.
            issue_url: URL of the verification issue.
            notes: Additional notes from the issue.
        """
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            """UPDATE works SET verified = 1,
               verified_by = ?, verified_at = ?,
               verification_issue_url = ?, notes = ?
               WHERE id = ?""",
            (verified_by, now, issue_url, notes, work_id),
        )
        self._conn.commit()

    def mark_work_unverified(self, work_id: int) -> None:
        """Reset verification status for a reopened issue.

        Args:
            work_id: Database row ID.
        """
        self._conn.execute(
            """UPDATE works SET verified = 0,
               verified_by = NULL, verified_at = NULL
               WHERE id = ?""",
            (work_id,),
        )
        self._conn.commit()

    def get_unverified_works(self) -> list[Work]:
        """Get works that have not been verified.

        Returns:
            List of unverified Work objects.
        """
        cursor = self._conn.execute(
            """SELECT * FROM works
               WHERE verified = 0
               ORDER BY year DESC, title"""
        )
        return [self._hydrate_work(row) for row in cursor]

    def get_works_with_code(self) -> list[Work]:
        """Get works that have linked code repositories.

        Returns:
            List of Work objects with code links.
        """
        cursor = self._conn.execute(
            """SELECT DISTINCT w.* FROM works w
               JOIN linked_resources lr ON w.id = lr.work_id
               WHERE lr.resource_type = 'code'
               ORDER BY w.year DESC, w.title"""
        )
        return [self._hydrate_work(row) for row in cursor]

    def get_works_with_data(self) -> list[Work]:
        """Get works that have linked datasets.

        Returns:
            List of Work objects with dataset links.
        """
        cursor = self._conn.execute(
            """SELECT DISTINCT w.* FROM works w
               JOIN linked_resources lr ON w.id = lr.work_id
               WHERE lr.resource_type = 'dataset'
               ORDER BY w.year DESC, w.title"""
        )
        return [self._hydrate_work(row) for row in cursor]

    def find_work_by_openalex_id(self, openalex_id: str) -> tuple[int, Work] | None:
        """Look up a work by OpenAlex ID.

        Args:
            openalex_id: OpenAlex work ID.

        Returns:
            Tuple of (row_id, Work) or None if not found.
        """
        cursor = self._conn.execute(
            "SELECT * FROM works WHERE openalex_id = ?",
            (openalex_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return row["id"], self._hydrate_work(row)

    def get_verification_stats(self) -> dict[str, int]:
        """Get verification statistics.

        Returns:
            Dict with total, verified, unverified, has_code,
            has_data counts.
        """
        total = self._conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        verified = self._conn.execute(
            "SELECT COUNT(*) FROM works WHERE verified = 1"
        ).fetchone()[0]
        has_code = self._conn.execute(
            """SELECT COUNT(DISTINCT w.id) FROM works w
               JOIN linked_resources lr ON w.id = lr.work_id
               WHERE lr.resource_type = 'code'"""
        ).fetchone()[0]
        has_data = self._conn.execute(
            """SELECT COUNT(DISTINCT w.id) FROM works w
               JOIN linked_resources lr ON w.id = lr.work_id
               WHERE lr.resource_type = 'dataset'"""
        ).fetchone()[0]
        return {
            "total": total,
            "verified": verified,
            "unverified": total - verified,
            "has_code": has_code,
            "has_data": has_data,
        }

    def get_total_works_count(self) -> int:
        """Get the total number of works in the database.

        Returns:
            Count of all works.
        """
        cursor = self._conn.execute("SELECT COUNT(*) FROM works")
        return int(cursor.fetchone()[0])

    # ── Scholar alert helpers ──────────────────────────────────

    def is_alert_email_processed(self, message_id: str) -> bool:
        """Check if a Scholar alert email has already been processed.

        Args:
            message_id: RFC Message-ID header value.

        Returns:
            True if the email is already in the database.
        """
        cursor = self._conn.execute(
            "SELECT 1 FROM scholar_alert_emails WHERE message_id = ?",
            (message_id,),
        )
        return cursor.fetchone() is not None

    def insert_alert_email(
        self,
        message_id: str,
        internal_date: str | None,
        gmail_uid: str | None,
        subject: str | None,
        from_addr: str | None,
        to_addr: str | None,
        raw_html: str | None,
    ) -> None:
        """Record a processed Scholar alert email.

        Args:
            message_id: RFC Message-ID header value.
            internal_date: Email internal date string.
            gmail_uid: IMAP UID (optional).
            subject: Email subject line.
            from_addr: Sender address.
            to_addr: Recipient address.
            raw_html: Raw HTML body.
        """
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            """INSERT OR IGNORE INTO scholar_alert_emails
               (message_id, internal_date, gmail_uid, subject,
                from_addr, to_addr, processed_at, raw_html)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message_id,
                internal_date,
                gmail_uid,
                subject,
                from_addr,
                to_addr,
                now,
                raw_html,
            ),
        )
        self._conn.commit()

    def insert_alert_item(
        self,
        message_id: str,
        position: int,
        title: str,
        authors: str | None,
        venue: str | None,
        year: int | None,
        target_url: str | None,
        scholar_url: str | None,
        work_id: int | None = None,
    ) -> int:
        """Insert a parsed alert item.

        Args:
            message_id: Parent email Message-ID.
            position: Item position within the email (0-based).
            title: Parsed title.
            authors: Authors string.
            venue: Venue string.
            year: Publication year.
            target_url: Resolved article URL.
            scholar_url: Scholar link URL.
            work_id: Linked work DB ID (if matched).

        Returns:
            Database row ID for the alert item.
        """
        now = datetime.utcnow().isoformat()
        cursor = self._conn.execute(
            """INSERT INTO scholar_alert_items
               (message_id, position, title, authors, venue,
                year, target_url, scholar_url, work_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message_id,
                position,
                title,
                authors,
                venue,
                year,
                target_url,
                scholar_url,
                work_id,
                now,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def update_alert_item_work_id(self, item_id: int, work_id: int) -> None:
        """Link an alert item to a work after dedup matching.

        Args:
            item_id: Alert item DB row ID.
            work_id: Work DB row ID.
        """
        self._conn.execute(
            "UPDATE scholar_alert_items SET work_id = ? WHERE id = ?",
            (work_id, item_id),
        )
        self._conn.commit()
