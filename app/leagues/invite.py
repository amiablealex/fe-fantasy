"""The invite landing, and the invite a visitor is carrying.

Lifted from the F1 app (SPEC.md §7). Someone follows an invite link while
signed out, registers or signs in, and expects to arrive in the league — which
means the code has to survive the round trip through the auth pages. It rides
in the session and is consumed once, on the next successful authentication.

**It expires.** An invite followed three weeks ago should not silently join
someone to a league because they happened to reset their password today. The
stored value carries the moment it was stored, and `take()` discards anything
older than `PENDING_INVITE_TTL_MINUTES`.

**Consumption never raises.** A full league, a rotated code, an account that is
already a member — none of those should turn a successful sign-in into an
error page. `consume` returns what happened and the caller flashes it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from flask import current_app, session

from app.leagues import service
from app.models.league import League
from app.models.user import User

SESSION_KEY = "pending_invite"


@dataclass(frozen=True)
class InviteOutcome:
    """What became of a pending invite. `league` is set only on a real join."""

    league: League | None = None
    message: str | None = None

    @property
    def joined(self) -> bool:
        return self.league is not None


def remember(code: str) -> None:
    session[SESSION_KEY] = {"code": code.strip().upper(), "at": time.time()}


def forget() -> None:
    session.pop(SESSION_KEY, None)


def take() -> str | None:
    """Pop the pending code, or None if there is none or it has expired."""
    stored = session.pop(SESSION_KEY, None)
    if not isinstance(stored, dict):
        return None
    code = stored.get("code")
    at = stored.get("at")
    if not code or not isinstance(at, (int, float)):
        return None
    ttl = current_app.config["PENDING_INVITE_TTL_MINUTES"] * 60
    if time.time() - at > ttl:
        return None
    return code


def consume(user: User) -> InviteOutcome:
    """Apply a carried invite to a freshly authenticated user."""
    code = take()
    if not code:
        return InviteOutcome()

    league = service.league_by_code(code)
    if league is None:
        return InviteOutcome(message="That invite link is no longer valid.")

    if service.membership_of(user, league) is not None:
        return InviteOutcome(message=f"You are already in {league.name}.")

    try:
        service.join_league(user, league)
    except service.LeagueError as refusal:
        return InviteOutcome(message=refusal.message)
    return InviteOutcome(league=league)
