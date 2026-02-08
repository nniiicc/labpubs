"""Tests for the core engine."""

from pathlib import Path

import pytest

from labpubs.config import load_config
from labpubs.models import Work
from labpubs.store import Store


class TestStoreBasics:
    """Tests for the Store class."""

    def test_upsert_researcher(self, tmp_db: Store) -> None:
        """Researchers can be inserted and updated."""
        rid = tmp_db.upsert_researcher(
            name="Jane Doe",
            config_key="jane_doe",
            openalex_id="A123",
        )
        assert rid is not None

        # Update should return same ID
        rid2 = tmp_db.upsert_researcher(
            name="Jane Doe",
            config_key="jane_doe",
            openalex_id="A456",
        )
        assert rid2 == rid

    def test_insert_and_find_work(
        self, tmp_db: Store, sample_work: Work
    ) -> None:
        """Works can be inserted and found by DOI."""
        work_id = tmp_db.insert_work(sample_work)
        result = tmp_db.find_work_by_doi("10.1234/example.2025")
        assert result is not None
        found_id, found_work = result
        assert found_id == work_id
        assert found_work.title == sample_work.title
        assert len(found_work.authors) == 2

    def test_find_work_by_title(
        self, tmp_db: Store, sample_work: Work
    ) -> None:
        """Works can be found by normalized title."""
        tmp_db.insert_work(sample_work)
        result = tmp_db.find_work_by_title(
            "Computational Approaches to Federal Rulemaking"
        )
        assert result is not None

    def test_get_works_with_filters(
        self, tmp_db: Store, sample_work: Work
    ) -> None:
        """Works can be queried with filters."""
        rid = tmp_db.upsert_researcher(
            name="Jane Doe", config_key="jane"
        )
        wid = tmp_db.insert_work(sample_work)
        tmp_db.link_researcher_work(rid, wid)

        works = tmp_db.get_works(researcher_id=rid)
        assert len(works) == 1

        works = tmp_db.get_works(year=2025)
        assert len(works) == 1

        works = tmp_db.get_works(year=1999)
        assert len(works) == 0

    def test_search_works(
        self, tmp_db: Store, sample_work: Work
    ) -> None:
        """Works can be searched by title content."""
        tmp_db.insert_work(sample_work)
        results = tmp_db.search_works("rulemaking")
        assert len(results) == 1

    def test_get_researchers(self, tmp_db: Store) -> None:
        """Researchers are listed correctly."""
        tmp_db.upsert_researcher(
            name="Jane Doe",
            config_key="jane",
            openalex_id="A123",
        )
        researchers = tmp_db.get_researchers()
        assert len(researchers) == 1
        assert researchers[0].name == "Jane Doe"
        assert researchers[0].is_lab_member is True


class TestConfig:
    """Tests for config loading."""

    def test_load_config(self, tmp_config: Path) -> None:
        """Config loads and validates from YAML."""
        config = load_config(tmp_config)
        assert config.lab.name == "Test Lab"
        assert len(config.researchers) == 1
        assert config.researchers[0].name == "Jane Doe"

    def test_missing_config(self, tmp_path: Path) -> None:
        """FileNotFoundError raised for missing config."""
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")
