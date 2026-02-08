"""Shared pytest fixtures for labpubs tests."""

from datetime import date, datetime
from pathlib import Path

import pytest

from labpubs.models import Author, Source, Work, WorkType
from labpubs.store import Store


@pytest.fixture
def sample_work() -> Work:
    """Create a sample Work for testing."""
    return Work(
        doi="10.1234/example.2025",
        title="Computational Approaches to Federal Rulemaking",
        authors=[
            Author(
                name="Jane Doe",
                openalex_id="A5023888391",
                is_lab_member=True,
            ),
            Author(name="John Smith"),
        ],
        publication_date=date(2025, 6, 15),
        year=2025,
        venue="Journal of Policy Analysis",
        work_type=WorkType.JOURNAL_ARTICLE,
        abstract="This paper examines computational methods...",
        openalex_id="W1234567890",
        open_access=True,
        open_access_url="https://example.com/paper.pdf",
        citation_count=42,
        sources=[Source.OPENALEX],
        first_seen=datetime(2025, 7, 1, 12, 0, 0),
    )


@pytest.fixture
def sample_work_s2() -> Work:
    """Create a second sample Work from Semantic Scholar."""
    return Work(
        doi="10.1234/example.2025",
        title="Computational approaches to federal rulemaking",
        authors=[
            Author(
                name="Jane Doe",
                semantic_scholar_id="1741101",
            ),
            Author(name="John Smith"),
        ],
        publication_date=date(2025, 6, 15),
        year=2025,
        venue="J. Policy Analysis",
        work_type=WorkType.JOURNAL_ARTICLE,
        semantic_scholar_id="abc123",
        tldr="Methods for analyzing federal rules computationally.",
        sources=[Source.SEMANTIC_SCHOLAR],
    )


@pytest.fixture
def tmp_db(tmp_path: Path) -> Store:
    """Create a temporary Store backed by a temp SQLite database."""
    db_path = tmp_path / "test.db"
    store = Store(db_path)
    yield store
    store.close()


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Create a temporary labpubs.yaml config file."""
    config_content = f"""
lab:
  name: "Test Lab"
  institution: "Test University"

database_path: "{tmp_path / 'test.db'}"

researchers:
  - name: "Jane Doe"
    openalex_id: "A5023888391"

sources:
  - openalex
"""
    config_path = tmp_path / "labpubs.yaml"
    config_path.write_text(config_content)
    return config_path
