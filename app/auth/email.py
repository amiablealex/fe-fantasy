"""Email delivery via Resend.

The only transactional email this app sends is the password-reset link. That is
product scope, not an oversight (SPEC.md §7).

Failures are logged, never raised to the user: the forgot-password flow reports
the same thing regardless of outcome so it cannot be used to enumerate accounts.
"""
from __future__ import annotations

import logging

import resend
from flask import current_app, render_template, url_for

from app.models.user import PasswordResetToken, User

log = logging.getLogger(__name__)


def _configure_resend() -> bool:
    key = current_app.config.get("RESEND_API_KEY")
    if not key:
        log.warning("RESEND_API_KEY not set - email will be skipped.")
        return False
    resend.api_key = key
    return True


def send_password_reset_email(user: User, token: PasswordResetToken) -> bool:
    """Send the password-reset email. Returns True if the send was attempted."""
    reset_url = url_for("auth.reset_password", token=token.token, _external=True)

    if not _configure_resend():
        # Development: log the link so the flow can be completed end to end
        # without configured email. Phase 0 checkpoint 0.3 relies on this.
        log.info("DEV password reset link for %s: %s", user.email, reset_url)
        return False

    ttl_hours = current_app.config["PASSWORD_RESET_TOKEN_TTL_HOURS"]
    html_body = render_template(
        "auth/email/reset_password.html",
        username=user.username,
        reset_url=reset_url,
        ttl_hours=ttl_hours,
    )
    text_body = render_template(
        "auth/email/reset_password.txt",
        username=user.username,
        reset_url=reset_url,
        ttl_hours=ttl_hours,
    )
    from_address = (
        f"{current_app.config['RESEND_FROM_NAME']} "
        f"<{current_app.config['RESEND_FROM_EMAIL']}>"
    )

    try:
        resend.Emails.send({
            "from": from_address,
            "to": [user.email],
            "subject": "Reset your Formula E Fantasy password",
            "html": html_body,
            "text": text_body,
        })
        return True
    except Exception:  # pragma: no cover - network
        log.exception("Failed to send password reset email to %s", user.email)
        return False
