"""Shared helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps

from flask import abort, current_app, request
from flask_login import current_user

from app.extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def admin_required(view):
    """Require an authenticated user with `is_admin`.

    403 rather than a redirect: an admin URL should not advertise itself to a
    signed-in non-admin by bouncing them somewhere friendly.
    """

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def touch_last_seen() -> None:
    """Update `last_seen_at` at most once per calendar day per user.

    Called from a before_request hook. The once-a-day guard keeps this from
    turning every page view into a write; the resolution is a day, and the
    only consumer is the active-user count on the admin page.
    """
    if not current_user.is_authenticated:
        return

    now = utcnow()
    last = current_user.last_seen_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last.date() == now.date():
            return

    current_user.last_seen_at = now
    db.session.commit()

def client_ip() -> str:
    """The requesting client's address, as far as it can be trusted.

    Only rate limiting depends on this. It is derived from a header, so it is
    forgeable by anything reaching the app without passing through Cloudflare.
    """
    header = current_app.config.get("CLIENT_IP_HEADER")
    if header:
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    return request.remote_addr or "?"
