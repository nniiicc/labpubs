"""Tests for the works router."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def _make_mock_work(
    title: str = "Test Paper",
    doi: str | None = "10.1234/test",
) -> MagicMock:
    """Create a mock Work with model_dump support."""
    work = MagicMock()
    work.doi = doi
    work.model_dump.return_value = {
        "title": title,
        "doi": doi,
        "year": 2024,
        "authors": [{"name": "Jane Doe"}],
    }
    return work


def test_list_works_no_filters(client: TestClient, mock_engine: MagicMock) -> None:
    """GET /works returns all works when no filters applied."""
    mock_engine.get_works.return_value = [_make_mock_work()]

    response = client.get("/works")

    assert response.status_code == 200
    assert len(response.json()) == 1
    mock_engine.get_works.assert_called_once_with(researcher=None, year=None)


def test_list_works_with_researcher_filter(
    client: TestClient, mock_engine: MagicMock
) -> None:
    """Researcher query param is forwarded to engine."""
    mock_engine.get_works.return_value = []

    response = client.get("/works?researcher=Jane+Doe")

    assert response.status_code == 200
    mock_engine.get_works.assert_called_once_with(researcher="Jane Doe", year=None)


def test_list_works_with_year_filter(
    client: TestClient, mock_engine: MagicMock
) -> None:
    """Year query param is forwarded to engine."""
    mock_engine.get_works.return_value = []

    response = client.get("/works?year=2024")

    assert response.status_code == 200
    mock_engine.get_works.assert_called_once_with(researcher=None, year=2024)


def test_list_works_with_funder_filter(
    client: TestClient, mock_engine: MagicMock
) -> None:
    """Funder filter routes to get_works_by_funder."""
    mock_engine.get_works_by_funder.return_value = [_make_mock_work()]

    response = client.get("/works?funder=NSF")

    assert response.status_code == 200
    mock_engine.get_works_by_funder.assert_called_once_with("NSF", year=None)


def test_list_works_respects_limit(client: TestClient, mock_engine: MagicMock) -> None:
    """Limit parameter caps the number of returned works."""
    works = [_make_mock_work(title=f"Paper {i}") for i in range(10)]
    mock_engine.get_works.return_value = works

    response = client.get("/works?limit=3")

    assert response.status_code == 200
    assert len(response.json()) == 3


def test_search_works(client: TestClient, mock_engine: MagicMock) -> None:
    """GET /works/search passes query to engine."""
    mock_engine.search_works.return_value = [_make_mock_work()]

    response = client.get("/works/search?q=machine+learning")

    assert response.status_code == 200
    assert len(response.json()) == 1
    mock_engine.search_works.assert_called_once_with("machine learning", limit=20)


def test_search_works_requires_query(client: TestClient) -> None:
    """GET /works/search returns 422 without q param."""
    response = client.get("/works/search")

    assert response.status_code == 422


def test_get_work_by_doi_found(client: TestClient, mock_engine: MagicMock) -> None:
    """GET /works/{doi} returns matching work."""
    work = _make_mock_work(doi="10.1234/test")
    mock_engine.search_works.return_value = [work]

    response = client.get("/works/10.1234/test")

    assert response.status_code == 200
    assert response.json()["doi"] == "10.1234/test"


def test_get_work_by_doi_not_found(client: TestClient, mock_engine: MagicMock) -> None:
    """GET /works/{doi} returns 404 when DOI not found."""
    mock_engine.search_works.return_value = []

    response = client.get("/works/10.9999/nonexistent")

    assert response.status_code == 404
