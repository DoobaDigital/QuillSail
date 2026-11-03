"""The dashboard: where editors and administrators run the publication.

Every page checks its own permission. The dashboard as a whole is open to
anyone who holds at least one of DASHBOARD_PERMISSIONS.
"""

from __future__ import annotations

from flask import Blueprint, abort, redirect, request, url_for
from sqlalchemy import func, select

from copydesk import permissions as perms
from copydesk.auth import current_user
from copydesk.db import db

bp = Blueprint("dash", __name__, url_prefix="/dashboard")

DASHBOARD_PERMISSIONS = (
    "review", "manage_issues", "send_issues", "manage_subscribers", "manage_users",
    "manage_groups", "manage_pages", "manage_settings", "view_log", "manage_competitions", "manage_business",
    "import_content",
)

NAV = [
    (None, [("overview", "Overview", "home", None)]),
    ("Publishing", [
        ("articles", "Articles", "file", "review"),
        ("issues", "Issues", "send", "manage_issues"),
        ("pages", "Pages", "book", "manage_pages"),
        ("sections", "Sections", "layers", "manage_pages"),
        ("competitions", "Competitions", "award", "manage_competitions"),
    ]),
    ("Readers and writers", [
        ("businesses", "Business outreach", "users", "manage_business"),
        ("subscribers", "Subscribers", "mail", "manage_subscribers"),
        ("members", "Members", "users", "manage_users"),
        ("groups", "Groups and permissions", "shield", "manage_groups"),
    ]),
    ("Site", [
        ("domain", "Domain", "server", "manage_settings"),
        ("launch_page", "Launch", "send", "manage_settings"),
        ("settings", "Settings", "sliders", "manage_settings"),
        ("import_jekyll", "Import a blog", "upload", "import_content"),
        ("log", "Activity log", "activity", "view_log"),
        ("system", "System status", "server", "manage_settings"),
    ]),
]


def can_use_dashboard(user) -> bool:
    return any(perms.has(user, p) for p in DASHBOARD_PERMISSIONS)


@bp.before_request
def _guard():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
    if not current_user.is_verified:
        return redirect(url_for("auth.verify_notice"))
    if not can_use_dashboard(current_user):
        abort(403)
    return None


def nav_counts() -> dict[str, int]:
    from copydesk.models import Article, BusinessInquiry, GroupMembership

    counts: dict[str, int] = {}
    if perms.has(current_user, "manage_business"):
        counts["businesses"] = db.session.scalar(
            select(func.count()).where(BusinessInquiry.status == "new")
        ) or 0
    if perms.has(current_user, "review"):
        counts["articles"] = db.session.scalar(
            select(func.count()).where(Article.status.in_(("submitted", "in_review")))
        ) or 0
    if perms.has(current_user, "manage_users"):
        counts["members"] = db.session.scalar(
            select(func.count()).where(GroupMembership.status == "pending")
        ) or 0
    return counts


@bp.context_processor
def _dashboard_context():
    return {"dash_nav": NAV, "dash_counts": nav_counts}


from copydesk.views.dashboard import (  # noqa: E402,F401 - registers routes
    appearance,
    articles,
    business,
    competitions,
    email,
    groups,
    imports,
    issues,
    launch,
    log,
    members,
    overview,
    pages,
    settings,
    subscribers,
    system,
)
