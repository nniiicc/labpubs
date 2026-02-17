"""Pydantic data models for labpubs.

Defines the core domain types: Work, Author, SyncResult, and related enums.
"""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Source(StrEnum):
    """Upstream data source identifier."""

    OPENALEX = "openalex"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    CROSSREF = "crossref"


class WorkType(StrEnum):
    """Scholarly work type classification."""

    JOURNAL_ARTICLE = "journal-article"
    CONFERENCE_PAPER = "conference-paper"
    PREPRINT = "preprint"
    BOOK_CHAPTER = "book-chapter"
    DISSERTATION = "dissertation"
    OTHER = "other"


class Author(BaseModel):
    """A researcher with optional cross-source identifiers."""

    name: str
    openalex_id: str | None = None
    semantic_scholar_id: str | None = None
    orcid: str | None = None
    affiliation: str | None = None
    is_lab_member: bool = False
    start_date: str | None = None
    end_date: str | None = None
    groups: list[str] = Field(default_factory=list)


class Funder(BaseModel):
    """A funding organization."""

    openalex_id: str
    name: str
    ror_id: str | None = None
    crossref_id: str | None = None
    country: str | None = None
    alternate_names: list[str] = Field(default_factory=list)


class Investigator(BaseModel):
    """A grant investigator (PI or co-PI)."""

    given_name: str | None = None
    family_name: str | None = None
    orcid: str | None = None
    affiliation_name: str | None = None
    affiliation_country: str | None = None


class Award(BaseModel):
    """A funding award/grant linked to publications."""

    openalex_id: str
    display_name: str | None = None
    description: str | None = None
    funder_award_id: str | None = None
    funder: Funder | None = None
    doi: str | None = None
    amount: int | None = None
    funding_type: str | None = None
    start_year: int | None = None
    lead_investigator: Investigator | None = None
    investigators: list[Investigator] = Field(default_factory=list)
    funded_outputs_count: int | None = None


class LinkedResource(BaseModel):
    """A code repository, dataset, or other resource linked to a work."""

    url: str
    resource_type: str  # "code", "dataset", "slides", "video", "other"
    name: str | None = None
    description: str | None = None


class Work(BaseModel):
    """A single scholarly work, deduplicated across sources."""

    doi: str | None = None
    title: str
    authors: list[Author] = Field(default_factory=list)
    publication_date: date | None = None
    year: int | None = None
    venue: str | None = None
    work_type: WorkType = WorkType.OTHER
    abstract: str | None = None

    # Source-specific IDs
    openalex_id: str | None = None
    semantic_scholar_id: str | None = None

    # Metadata
    open_access: bool | None = None
    open_access_url: str | None = None
    citation_count: int | None = None
    tldr: str | None = None

    # Funding
    awards: list[Award] = Field(default_factory=list)
    funders: list[Funder] = Field(default_factory=list)

    # Verification & enrichment (from GitHub issues)
    linked_resources: list[LinkedResource] = Field(
        default_factory=list
    )
    verified: bool = False
    verified_by: str | None = None
    verified_at: datetime | None = None
    verification_issue_url: str | None = None
    notes: str | None = None

    # Provenance
    sources: list[Source] = Field(default_factory=list)
    first_seen: datetime | None = None
    last_updated: datetime | None = None


class SyncResult(BaseModel):
    """Result of a sync operation."""

    timestamp: datetime
    researchers_checked: int
    new_works: list[Work] = Field(default_factory=list)
    updated_works: list[Work] = Field(default_factory=list)
    total_works: int
    errors: list[str] = Field(default_factory=list)
