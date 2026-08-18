"""Configuration behaviour that is easy to get silently wrong."""
from __future__ import annotations

import pytest

from app.config import ConfigError, _normalise_db_url, validate_production_config


def test_db_url_is_normalised_onto_psycopg3():
    assert _normalise_db_url("postgres://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
    assert _normalise_db_url("postgresql://u:p@h:5432/d") == "postgresql+psycopg://u:p@h:5432/d"
    assert (
        _normalise_db_url("postgresql+psycopg://u:p@h:5432/d")
        == "postgresql+psycopg://u:p@h:5432/d"
    )


class _FakeApp:
    def __init__(self, **config):
        self.config = {
            "DEBUG": False,
            "TESTING": False,
            "SECRET_KEY": "a-real-secret",
            "APP_BASE_URL": "https://fe.kitsniff.com",
        }
        self.config.update(config)


def test_production_refuses_to_start_with_the_default_secret(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    app = _FakeApp(SECRET_KEY="dev-secret-change-me")
    with pytest.raises(ConfigError, match="SECRET_KEY"):
        validate_production_config(app)


def test_production_refuses_to_start_without_https_base_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x/y")
    app = _FakeApp(APP_BASE_URL="http://fe.kitsniff.com")
    with pytest.raises(ConfigError, match="https"):
        validate_production_config(app)


def test_validation_is_skipped_in_debug():
    validate_production_config(_FakeApp(DEBUG=True, SECRET_KEY="dev-secret-change-me"))
