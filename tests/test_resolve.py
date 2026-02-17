"""Tests for labpubs.resolve -- CSV parsing, ID resolution, config generation."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from labpubs.models import Author
from labpubs.resolve import (
    ResolveResult,
    generate_config_yaml,
    merge_into_existing,
    parse_csv,
    resolve_researcher,
    resolve_researchers_from_csv,
)

# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


class TestParseCSV:
    def test_basic(self, tmp_path: Path) -> None:
        csv = tmp_path / "members.csv"
        csv.write_text("name,orcid\nJane Doe,0000-0001-2345-6789\n")
        rows = parse_csv(csv)
        assert len(rows) == 1
        assert rows[0]["name"] == "Jane Doe"
        assert rows[0]["orcid"] == "0000-0001-2345-6789"

    def test_optional_columns(self, tmp_path: Path) -> None:
        csv = tmp_path / "members.csv"
        csv.write_text(
            "name,orcid,openalex_id,semantic_scholar_id,affiliation\n"
            "Jane,0000-0001-2345-6789,A123,S456,MIT\n"
        )
        rows = parse_csv(csv)
        assert rows[0]["openalex_id"] == "A123"
        assert rows[0]["semantic_scholar_id"] == "S456"
        assert rows[0]["affiliation"] == "MIT"

    def test_header_aliases(self, tmp_path: Path) -> None:
        csv = tmp_path / "members.csv"
        csv.write_text(
            "Full Name,ORCID-ID\n" "John Smith,0000-0002-0000-0000\n"
        )
        rows = parse_csv(csv)
        assert rows[0]["name"] == "John Smith"
        assert rows[0]["orcid"] == "0000-0002-0000-0000"

    def test_missing_name_column_raises(self, tmp_path: Path) -> None:
        csv = tmp_path / "bad.csv"
        csv.write_text("orcid\n0000-0001-2345-6789\n")
        with pytest.raises(ValueError, match="name"):
            parse_csv(csv)

    def test_skips_empty_rows(self, tmp_path: Path) -> None:
        csv = tmp_path / "members.csv"
        csv.write_text("name,orcid\nJane,111\n,,\nJohn,222\n")
        rows = parse_csv(csv)
        assert len(rows) == 2

    def test_utf8_bom(self, tmp_path: Path) -> None:
        csv = tmp_path / "members.csv"
        csv.write_bytes(
            b"\xef\xbb\xbfname,orcid\nJane,111\n"
        )
        rows = parse_csv(csv)
        assert rows[0]["name"] == "Jane"

    def test_start_end_date_columns(self, tmp_path: Path) -> None:
        csv = tmp_path / "members.csv"
        csv.write_text(
            "name,start_date,end_date\n"
            "Jane Doe,2020-09-01,2023-06-30\n"
            "John Smith,2024-01-15,\n"
        )
        rows = parse_csv(csv)
        assert rows[0]["start_date"] == "2020-09-01"
        assert rows[0]["end_date"] == "2023-06-30"
        assert rows[1]["start_date"] == "2024-01-15"
        assert rows[1]["end_date"] == ""

    def test_start_date_aliases(self, tmp_path: Path) -> None:
        csv = tmp_path / "members.csv"
        csv.write_text("name,joined\nJane,2022-01-01\n")
        rows = parse_csv(csv)
        assert rows[0]["start_date"] == "2022-01-01"

    def test_groups_column(self, tmp_path: Path) -> None:
        csv = tmp_path / "members.csv"
        csv.write_text(
            "name,groups\n"
            'Jane Doe,"NLP, IR"\n'
            "John Smith,faculty\n"
            "Alice,,\n"
        )
        rows = parse_csv(csv)
        assert rows[0]["groups"] == "NLP,IR"
        assert rows[1]["groups"] == "faculty"

    def test_groups_alias_team(self, tmp_path: Path) -> None:
        csv = tmp_path / "members.csv"
        csv.write_text("name,team\nJane,NLP\n")
        rows = parse_csv(csv)
        assert rows[0]["groups"] == "NLP"


# ---------------------------------------------------------------------------
# resolve_researcher
# ---------------------------------------------------------------------------


class TestResolveResearcher:
    async def test_orcid_match(self) -> None:
        oa = AsyncMock()
        oa.resolve_author_by_orcid.return_value = Author(
            name="Jane Doe", openalex_id="A123", orcid="0000-1"
        )
        s2 = AsyncMock()
        s2.resolve_author_by_orcid.return_value = Author(
            name="Jane Doe",
            semantic_scholar_id="S456",
            orcid="0000-1",
        )

        result = await resolve_researcher(
            "Jane Doe", "0000-1", None, oa, s2
        )
        assert result.openalex_id == "A123"
        assert result.openalex_confident is True
        assert result.semantic_scholar_id == "S456"
        assert result.s2_confident is True
        # No fallback search should have been called.
        oa.resolve_author_id.assert_not_called()
        s2.resolve_author_id.assert_not_called()

    async def test_fallback_to_name_search(self) -> None:
        oa = AsyncMock()
        oa.resolve_author_by_orcid.return_value = None
        oa.resolve_author_id.return_value = [
            Author(name="Jane Doe", openalex_id="A999")
        ]
        s2 = AsyncMock()
        s2.resolve_author_by_orcid.return_value = None
        s2.resolve_author_id.return_value = []

        result = await resolve_researcher(
            "Jane Doe", "0000-1", "MIT", oa, s2
        )
        assert result.openalex_id is None
        assert len(result.openalex_candidates) == 1
        oa.resolve_author_id.assert_called_once_with("Jane Doe", "MIT")

    async def test_no_orcid(self) -> None:
        oa = AsyncMock()
        oa.resolve_author_id.return_value = []
        s2 = AsyncMock()
        s2.resolve_author_id.return_value = []

        result = await resolve_researcher(
            "Jane Doe", None, None, oa, s2
        )
        assert result.openalex_id is None
        assert result.semantic_scholar_id is None
        # ORCID lookup should not have been called.
        oa.resolve_author_by_orcid.assert_not_called()
        s2.resolve_author_by_orcid.assert_not_called()


# ---------------------------------------------------------------------------
# resolve_researchers_from_csv
# ---------------------------------------------------------------------------


class TestResolveFromCSV:
    async def test_prefilled_ids_skip_lookup(
        self, tmp_path: Path
    ) -> None:
        csv = tmp_path / "members.csv"
        csv.write_text(
            "name,orcid,openalex_id,semantic_scholar_id\n"
            "Jane,0000-1,A123,S456\n"
        )
        oa = AsyncMock()
        s2 = AsyncMock()

        results = await resolve_researchers_from_csv(
            csv, oa, s2, rate_limit_delay=0
        )
        assert len(results) == 1
        assert results[0].openalex_id == "A123"
        assert results[0].semantic_scholar_id == "S456"
        # Backends should not have been called.
        oa.resolve_author_by_orcid.assert_not_called()
        s2.resolve_author_by_orcid.assert_not_called()


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------


class TestGenerateConfig:
    def test_generates_valid_yaml(self) -> None:
        results = [
            ResolveResult(
                name="Jane Doe",
                orcid="0000-1",
                openalex_id="A123",
                semantic_scholar_id="S456",
            ),
            ResolveResult(name="John Smith"),
        ]
        yaml_str = generate_config_yaml(
            results,
            lab_name="Test Lab",
            institution="MIT",
            openalex_email="test@example.com",
        )
        config = yaml.safe_load(yaml_str)
        assert config["lab"]["name"] == "Test Lab"
        assert len(config["researchers"]) == 2
        assert config["researchers"][0]["openalex_id"] == "A123"
        assert "openalex_id" not in config["researchers"][1]

    def test_includes_dates_and_groups(self) -> None:
        results = [
            ResolveResult(
                name="Jane Doe",
                start_date="2020-09-01",
                end_date="2023-06-30",
                groups=["NLP", "faculty"],
            ),
        ]
        yaml_str = generate_config_yaml(results)
        config = yaml.safe_load(yaml_str)
        r = config["researchers"][0]
        assert r["start_date"] == "2020-09-01"
        assert r["end_date"] == "2023-06-30"
        assert r["groups"] == ["NLP", "faculty"]

    def test_omits_empty_dates_and_groups(self) -> None:
        results = [ResolveResult(name="Jane Doe")]
        yaml_str = generate_config_yaml(results)
        config = yaml.safe_load(yaml_str)
        r = config["researchers"][0]
        assert "start_date" not in r
        assert "end_date" not in r
        assert "groups" not in r


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


class TestMerge:
    def test_merge_adds_new_and_updates_existing(
        self, tmp_path: Path
    ) -> None:
        existing = tmp_path / "labpubs.yaml"
        existing.write_text(
            yaml.dump(
                {
                    "lab": {"name": "My Lab"},
                    "researchers": [
                        {"name": "Jane Doe", "orcid": "0000-1"},
                    ],
                }
            )
        )

        results = [
            # Existing researcher -- should update with new ID.
            ResolveResult(
                name="Jane Doe",
                orcid="0000-1",
                openalex_id="A123",
            ),
            # New researcher.
            ResolveResult(
                name="John Smith",
                orcid="0000-2",
                openalex_id="A456",
            ),
        ]
        yaml_str = merge_into_existing(existing, results)
        config = yaml.safe_load(yaml_str)
        researchers = config["researchers"]
        assert len(researchers) == 2
        assert researchers[0]["openalex_id"] == "A123"
        assert researchers[1]["name"] == "John Smith"

    def test_merge_does_not_overwrite_existing_ids(
        self, tmp_path: Path
    ) -> None:
        existing = tmp_path / "labpubs.yaml"
        existing.write_text(
            yaml.dump(
                {
                    "researchers": [
                        {
                            "name": "Jane Doe",
                            "orcid": "0000-1",
                            "openalex_id": "ORIGINAL",
                        },
                    ],
                }
            )
        )
        results = [
            ResolveResult(
                name="Jane Doe",
                orcid="0000-1",
                openalex_id="NEW",
            ),
        ]
        yaml_str = merge_into_existing(existing, results)
        config = yaml.safe_load(yaml_str)
        assert config["researchers"][0]["openalex_id"] == "ORIGINAL"
