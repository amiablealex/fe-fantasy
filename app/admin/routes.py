"""Admin blueprint.

Read-mostly by design (SPEC.md §10). Mutating actions must be idempotent and
logged with actor and timestamp, and none exist yet: every remedy the health
page points at is a CLI command. Arbitrary record editing is deliberately
absent — that is what psql is for.
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, current_app, render_template
from sqlalchemy import func, select

from app.extensions import db
from app.models.league import League
from app.models.user import User
from app.utils import admin_required, client_ip, utcnow

admin_bp = Blueprint("admin", __name__, template_folder="../templates")


@admin_bp.route("/")
@admin_required
def index():
    window_days = current_app.config["ACTIVE_USER_WINDOW_DAYS"]
    since = utcnow() - timedelta(days=window_days)

    stats = {
        "users_total": db.session.scalar(select(func.count()).select_from(User)) or 0,
        "users_active": db.session.scalar(
            select(func.count()).select_from(User).where(User.last_seen_at >= since)
        ) or 0,
        "users_new_7d": db.session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.created_at >= utcnow() - timedelta(days=7))
        ) or 0,
        "leagues_total": db.session.scalar(select(func.count()).select_from(League)) or 0,
    }

    return render_template(
        "admin/index.html",
        stats=stats,
        window_days=window_days,
        title="Admin",
    )

@admin_bp.route("/health")
@admin_required
def health():
    """Sync health, provider quota and outstanding conflicts.

    The page §10 said the admin surface needed first. Read-only: every remedy
    it points at is a CLI command, because a button that rescores a season is
    the kind of thing that gets pressed by accident on a race weekend.
    """
    from app.admin import health as health_queries

    return render_template(
        "admin/health.html",
        health=health_queries.snapshot(),
        ago=health_queries.ago,
        title="Health",
    )


@admin_bp.route("/request-info")
@admin_required
def request_info():
    """What the proxy chain is actually delivering.

    Client IPs come from `CF-Connecting-IP` (SPEC.md §7): Railway's edge
    rebuilds `X-Forwarded-For` from its own peer, so no hop count recovers the
    client from it. This page is how to check that is still true.
    """
    from flask import request

    return {
        "remote_addr": request.remote_addr,
        "x_forwarded_for": request.headers.get("X-Forwarded-For"),
        "cf_connecting_ip": request.headers.get("CF-Connecting-IP"),
        "x_forwarded_proto": request.headers.get("X-Forwarded-Proto"),
        "scheme": request.scheme,
        "client_ip": client_ip(),
    }
