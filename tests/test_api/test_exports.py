"""Tests for the exports router."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def test_export_bibtex(client: TestClient, mock_engine: MagicMock) -> None:
    """GET /export/bibtex returns plain text BibTeX."""
    mock_engine.export_bibtex.return_value = "@article{doe2024,\n  title={Test}\n}"

    response = client.get("/export/bibtex")

    assert response.status_code == 200
    assert "@article" in response.text
    mock_engine.export_bibtex.assert_called_once_with(researcher=None, year=None)


def test_export_bibtex_with_filters(client: TestClient, mock_engine: MagicMock) -> None:
    """Researcher and year filters are forwarded."""
    mock_engine.export_bibtex.return_value = ""

    response = client.get("/export/bibtex?researcher=Doe&year=2024")

    assert response.status_code == 200
    mock_engine.export_bibtex.assert_called_once_with(researcher="Doe", year=2024)


def test_export_json(client: TestClient, mock_engine: MagicMock) -> None:
    """GET /export/json returns JSON list."""
    mock_engine.export_json.return_value = [{"title": "Test", "doi": "10.1234/x"}]

    response = client.get("/export/json")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Test"
    mock_engine.export_json.assert_called_once_with(researcher=None, year=None)


def test_export_csl_json(client: TestClient, mock_engine: MagicMock) -> None:
    """GET /export/csl-json returns CSL-JSON list."""
    mock_engine.export_csl_json.return_value = [
        {"type": "article-journal", "title": "Test"}
    ]

    response = client.get("/export/csl-json")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    mock_engine.export_csl_json.assert_called_once_with(researcher=None, year=None)
