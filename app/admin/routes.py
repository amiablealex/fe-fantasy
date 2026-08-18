"""Admin blueprint.

Read-mostly by design (SPEC.md §10). Mutating actions are added per phase, must
be idempotent, and are logged with actor and timestamp. Arbitrary record editing
is deliberately absent — that is what psql is for.

Phase 0 ships the mechanism and three counts, so `admin_required` and the
navigation are proven end to end before there is anything real to administer.
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

@admin_bp.route("/request-info")
@admin_required
def request_info():
    """What the proxy chain is actually delivering.

    The hop count in ProxyFix has to match reality: too few and you read a
    proxy's IP instead of the client's, too many and a client can spoof it.
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
