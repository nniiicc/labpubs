"""Tests for the researchers router."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def test_list_researchers_returns_all(
    client: TestClient, mock_engine: MagicMock
) -> None:
    """GET /researchers returns serialized researcher data."""
    mock_author = MagicMock()
    mock_author.model_dump.return_value = {
        "name": "Jane Doe",
        "orcid": "0000-0002-1234-5678",
        "openalex_id": "A5000000001",
    }
    mock_engine.get_researchers.return_value = [mock_author]

    response = client.get("/researchers")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Jane Doe"
    assert data[0]["orcid"] == "0000-0002-1234-5678"
    mock_engine.get_researchers.assert_called_once()


def test_list_researchers_empty(client: TestClient, mock_engine: MagicMock) -> None:
    """GET /researchers returns empty list when no researchers."""
    mock_engine.get_researchers.return_value = []

    response = client.get("/researchers")

    assert response.status_code == 200
    assert response.json() == []
