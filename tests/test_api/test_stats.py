"""Tests for the stats router."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def test_get_stats(client: TestClient, mock_engine: MagicMock) -> None:
    """GET /stats returns aggregated counts."""
    mock_engine.get_researchers.return_value = [MagicMock()] * 5
    mock_engine.get_works.return_value = [MagicMock()] * 100
    mock_engine.get_funders.return_value = [MagicMock()] * 3
    mock_engine.get_verification_stats.return_value = {
        "total": 100,
        "verified": 40,
        "unverified": 60,
        "has_code": 25,
        "has_data": 15,
    }

    response = client.get("/stats")

    assert response.status_code == 200
    data = response.json()
    assert data["total_researchers"] == 5
    assert data["total_works"] == 100
    assert data["total_funders"] == 3
    assert data["verification"]["verified"] == 40
