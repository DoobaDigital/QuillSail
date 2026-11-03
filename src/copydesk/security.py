"""CSRF protection, security headers and rate limiting."""

from __future__ import annotations

import hmac
import secrets
from datetime import timedelta

from flask import abort, current_app, g, request, session
from sqlalchemy import case, or_, update
from sqlalchemy.exc import IntegrityError

from copydesk.db import db
from copydesk.models import RateLimit
from copydesk.utils import utcnow

CSRF_SESSION_KEY = "_csrf"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def csrf_token() -> str:
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def csrf_exempt(view):
    """Mark a view that is safe to call without a CSRF token (it must not rely on cookies)."""
    view._csrf_exempt = True
    return view


def check_csrf() -> None:
    if request.method not in UNSAFE_METHODS:
        return
    view = current_app.view_functions.get(request.endpoint or "")
    if view is None or getattr(view, "_csrf_exempt", False):
        return
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    expected = session.get(CSRF_SESSION_KEY, "")
    if not sent or not expected or not hmac.compare_digest(str(sent), str(expected)):
        abort(400, description="csrf")


def csp_nonce() -> str:
    nonce = g.get("csp_nonce")
    if nonce is None:
        nonce = secrets.token_urlsafe(16)
        g.csp_nonce = nonce
    return nonce


def default_csp() -> str:
    nonce = csp_nonce()
    # A form-initiated OAuth redirect is checked against form-action by Chrome.
    form_action = "'self' https://dash.cloudflare.com" if request.endpoint == "dash.domain" else "'self'"
    return (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        f"style-src 'self' 'nonce-{nonce}'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "media-src 'self' https:; "
        # Keep these hosts in step with EMBED_HOSTS in text.py.
        "frame-src 'self' https://www.youtube-nocookie.com https://player.vimeo.com; "
        "frame-ancestors 'self'; "
        f"form-action {form_action}; "
        "base-uri 'self'; "
        "object-src 'none'"
    )


def apply_headers(response):
    if request.endpoint in {"public.shared_issue", "business.confirm", "dash.issue_share"}:
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    csp = g.get("csp_override")
    if csp is None:
        csp = default_csp()
    if csp:
        response.headers.setdefault("Content-Security-Policy", csp)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if not g.get("allow_framing"):
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), interest-cohort=()")
    if session.get("uid") or request.endpoint in {
        "subscribe.manage", "subscribe.unsubscribe", "subscribe.confirm", "auth.verify_email",
        "auth.reset_password", "account.confirm_email",
        "public.shared_issue", "business.confirm", "dash.issue_share",
    }:
        response.headers["Cache-Control"] = "private, no-store"
        response.vary.add("Cookie")
    return response


def client_ip() -> str:
    return request.remote_addr or "unknown"


def too_many(bucket: str, limit: int, period_seconds: int, key: str | None = None) -> bool:
    """Count one attempt against ``bucket``. True when the limit has been reached.

    Uses the database, so the limit holds across all web server processes.
    """
    if not current_app.config.get("RATELIMIT_ENABLED", True):
        return False
    ident = f"{bucket}:{key if key is not None else client_ip()}"[:191]
    now = utcnow()
    for _attempt in range(2):
        row = db.session.get(RateLimit, ident)
        try:
            if row is None:
                db.session.add(RateLimit(key=ident, window_start=now, count=1))
                db.session.commit()
                return False
            expired = RateLimit.window_start <= now - timedelta(seconds=period_seconds)
            result = db.session.execute(
                update(RateLimit).where(RateLimit.key == ident, or_(expired, RateLimit.count < limit))
                # MySQL evaluates assignments left to right; test expiry before resetting the window.
                .ordered_values(
                    (RateLimit.count, case((expired, 1), else_=RateLimit.count + 1)),
                    (RateLimit.window_start, case((expired, now), else_=RateLimit.window_start)),
                )
            )
            db.session.commit()
            return result.rowcount == 0
        except IntegrityError:
            db.session.rollback()
    return True
