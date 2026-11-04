"""Isolated evidence storage for each test."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "receipt_evidence")


@pytest.fixture
def client(settings: Settings):
    return TestClient(create_app(settings))
