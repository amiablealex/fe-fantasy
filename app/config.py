"""Application configuration.

Three tiers, deliberately separated. See SPEC.md §7.

  1. Secrets and environment-varying values -> environment variables.
  2. Operational knobs                      -> here, each read from the
     environment with a sensible default, so anything can be retuned on
     Railway without a redeploy of code.
  3. Point values and design tokens         -> NOT here.

Tier 3 is the boundary the F1 app did not draw. Config holds values where only
the *current* value matters. Scoring point values need every *past* value to
stay retrievable, because a completed round must keep scoring the way it scored
at the time — so they live in `app/scoring/rules.py` as a versioned ruleset that
is snapshotted per round. Colour, spacing and type scale live in
`app/static/css/tokens.css` as CSS custom properties, so a design tweak is a
stylesheet edit rather than a Python edit and a redeploy.
"""
from __future__ import annotations

import os
from datetime import timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Load .env if present. No-op in production, where Railway sets the environment.
load_dotenv()

_DEV_SECRET = "dev-secret-change-me"


# -----------------------------------------------------------------------------
# Environment readers
# -----------------------------------------------------------------------------


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _normalise_db_url(raw: str) -> str:
    """Normalise a Postgres URL onto the psycopg 3 driver.

    Railway emits `postgresql://`; some providers still emit the legacy
    `postgres://`. SQLAlchemy 2.x defaults the bare `postgresql://` scheme to
    psycopg2, which this project does not install, so pin the driver
    explicitly.
    """
    if raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql://", 1)
    if raw.startswith("postgresql://"):
        raw = raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


# -----------------------------------------------------------------------------
# Base config
# -----------------------------------------------------------------------------


class Config:
    # -------------------------------------------------------------------------
    # Release. Bump on every tagged release. Sent to the data provider in the
    # User-Agent header (SPEC.md §6) and shown in the UI footer.
    # -------------------------------------------------------------------------
    APP_VERSION = "0.1.0"
    APP_NAME = "Formula E Fantasy"

    # -------------------------------------------------------------------------
    # Flask core
    # -------------------------------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", _DEV_SECRET)
    FLASK_ENV = os.environ.get("FLASK_ENV", "production")
    DEBUG = FLASK_ENV == "development"
    TESTING = False

    SESSION_COOKIE_SECURE = not DEBUG
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=_env_int("SESSION_LIFETIME_DAYS", 30))

    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")
    TIMEZONE = ZoneInfo(os.environ.get("DISPLAY_TIMEZONE", "Europe/London"))

    # Cloudflare sets CF-Connecting-IP to the true client address. Railway's
    # edge rebuilds X-Forwarded-For from its own peer, so the client never
    # appears there — the chain reads "<cloudflare-edge>, <railway-edge>".
    # Empty falls back to request.remote_addr, which is correct locally.
    CLIENT_IP_HEADER = os.environ.get("CLIENT_IP_HEADER", "CF-Connecting-IP")

    # -------------------------------------------------------------------------
    # Database
    # -------------------------------------------------------------------------
    SQLALCHEMY_DATABASE_URI = _normalise_db_url(
        os.environ.get(
            "DATABASE_URL",
            "postgresql://fe_user:fe_pass@localhost:5432/fe_fantasy",
        )
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": _env_int("DB_POOL_RECYCLE_SECONDS", 300),
    }

    # -------------------------------------------------------------------------
    # Email (Resend). Password reset only — see SPEC.md §7. No reminders, no
    # digests, no notifications of any kind.
    # -------------------------------------------------------------------------
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
    RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "noreply@fe.kitsniff.com")
    RESEND_FROM_NAME = os.environ.get("RESEND_FROM_NAME", "Formula E Fantasy")
    PASSWORD_RESET_TOKEN_TTL_HOURS = _env_int("PASSWORD_RESET_TOKEN_TTL_HOURS", 2)

    # -------------------------------------------------------------------------
    # Rate limiting.
    #
    # Known limitation, accepted (SPEC.md §7): the store is in-memory and
    # therefore per-process. With `gunicorn --workers 2` the effective allowance
    # doubles and blocking is inconsistent between requests. Fine at invite
    # scale; revisit with a `login_attempts` table if this app ever goes public.
    # -------------------------------------------------------------------------
    LOGIN_MAX_ATTEMPTS = _env_int("LOGIN_MAX_ATTEMPTS", 8)
    LOGIN_WINDOW_MINUTES = _env_int("LOGIN_WINDOW_MINUTES", 15)
    LOGIN_BLOCK_MINUTES = _env_int("LOGIN_BLOCK_MINUTES", 15)

    REGISTER_MAX_ATTEMPTS = _env_int("REGISTER_MAX_ATTEMPTS", 5)
    REGISTER_WINDOW_MINUTES = _env_int("REGISTER_WINDOW_MINUTES", 60)
    REGISTER_BLOCK_MINUTES = _env_int("REGISTER_BLOCK_MINUTES", 60)

    # -------------------------------------------------------------------------
    # Leagues (Phase 6; the models are in the Phase 0 baseline so the schema
    # does not need a migration later).
    # -------------------------------------------------------------------------
    INVITE_CODE_LENGTH = _env_int("INVITE_CODE_LENGTH", 6)
    INVITE_CODE_ALPHABET = os.environ.get(
        "INVITE_CODE_ALPHABET", "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
    )
    MAX_LEAGUE_MEMBERS = _env_int("MAX_LEAGUE_MEMBERS", 50)

    # -------------------------------------------------------------------------
    # Admin.
    # -------------------------------------------------------------------------
    ACTIVE_USER_WINDOW_DAYS = _env_int("ACTIVE_USER_WINDOW_DAYS", 30)

    # -------------------------------------------------------------------------
    # Orange Cat Blacktop API (Phase 1). Declared here so the environment shape
    # is settled, but nothing in Phase 0 makes a network call.
    #
    # The User-Agent is not optional: the default Python UA is refused by
    # Cloudflare with Error 1010 before reaching the API (SPEC.md §6).
    # -------------------------------------------------------------------------
    OCB_BASE_URL = os.environ.get(
        "OCB_BASE_URL", "https://api.ocblacktop.com/v1/formula-e"
    ).rstrip("/")
    OCB_API_KEY = os.environ.get("OCB_API_KEY", "")
    OCB_USER_AGENT = os.environ.get(
        "OCB_USER_AGENT",
        f"KitsniffFEFantasy/{APP_VERSION} (+https://fe.kitsniff.com)",
    )
    OCB_REQUEST_TIMEOUT_SECONDS = _env_int("OCB_REQUEST_TIMEOUT_SECONDS", 15)
    OCB_MIN_REQUEST_INTERVAL_SECONDS = _env_float("OCB_MIN_REQUEST_INTERVAL_SECONDS", 0.5)


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = _normalise_db_url(
        os.environ.get(
            "TEST_DATABASE_URL",
            "postgresql://fe_user:fe_pass@localhost:5432/fe_fantasy_test",
        )
    )


class ProductionConfig(Config):
    DEBUG = False


def get_config() -> type[Config]:
    """Return the config class appropriate to FLASK_ENV."""
    env = os.environ.get("FLASK_ENV", "production").lower()
    if env == "development":
        return DevelopmentConfig
    if env == "testing":
        return TestingConfig
    return ProductionConfig


# -----------------------------------------------------------------------------
# Boot validation
# -----------------------------------------------------------------------------


class ConfigError(RuntimeError):
    """Raised when production configuration is missing or unsafe."""


def validate_production_config(app) -> None:
    """Refuse to start production with missing or unsafe configuration.

    A default `SECRET_KEY` is the failure worth catching here: without this
    check, a Railway variable that was never set ships a publicly known signing
    key and nothing anywhere reports a problem.
    """
    if app.config["DEBUG"] or app.config["TESTING"]:
        return

    problems: list[str] = []

    if app.config["SECRET_KEY"] in (_DEV_SECRET, "", None):
        problems.append("SECRET_KEY is unset or still the development default")

    if not os.environ.get("DATABASE_URL"):
        problems.append("DATABASE_URL is not set (falling back to a local dev URL)")

    base_url = app.config["APP_BASE_URL"]
    if not base_url.startswith("https://"):
        problems.append(f"APP_BASE_URL must be https in production, got {base_url!r}")

    if problems:
        raise ConfigError(
            "Refusing to start. Fix the following environment variables:\n  - "
            + "\n  - ".join(problems)
        )
