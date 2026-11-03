"""The activity log: a permanent record of who changed what."""

from __future__ import annotations

from typing import Any

from flask import has_request_context

from copydesk.db import db
from copydesk.models import AuditEntry

# How each action reads in the log: "<actor> <phrase> <target>".
ACTIONS: dict[str, str] = {
    "user.registered": "created an account",
    "user.verified": "confirmed their email address",
    "user.updated": "edited the account of",
    "user.blocked": "blocked",
    "user.unblocked": "unblocked",
    "user.deleted": "deleted the account of",
    "user.password_changed": "changed their password",
    "group.created": "created the group",
    "group.updated": "edited the group",
    "group.deleted": "deleted the group",
    "membership.added": "added someone to a group:",
    "membership.removed": "removed someone from a group:",
    "membership.requested": "asked to join",
    "membership.approved": "approved a request to join",
    "membership.rejected": "turned down a request to join",
    "article.created": "started writing",
    "article.status": "changed the status of",
    "article.edited": "edited",
    "article.assigned": "assigned an editor to",
    "article.deleted": "deleted",
    "article.imported": "imported",
    "article.imported_site": "imported a blog:",
    "article.settings": "changed the publishing settings of",
    "issue.created": "created",
    "issue.updated": "edited",
    "issue.scheduled": "scheduled",
    "issue.unscheduled": "unscheduled",
    "issue.sending": "started sending",
    "issue.sent": "finished sending",
    "issue.published": "published on the web",
    "issue.deleted": "deleted",
    "issue.test_sent": "sent a test of",
    "issue.preview_shared": "created a private preview link for",
    "issue.preview_revoked": "revoked the private preview link for",
    "business.confirmed": "confirmed the email for",
    "business.updated": "updated follow-up for",
    "business.draft_created": "created an editorial draft from",
    "business.deleted": "deleted",
    "subscriber.added": "added the subscriber",
    "subscriber.updated": "edited the subscriber",
    "subscriber.deleted": "removed the subscriber",
    "subscriber.imported": "imported subscribers",
    "subscriber.exported": "exported the subscriber list",
    "settings.updated": "changed settings:",
    "page.created": "created the page",
    "page.updated": "edited the page",
    "page.deleted": "deleted the page",
    "section.created": "created the section",
    "section.updated": "edited the section",
    "section.deleted": "deleted the section",
    "setup.completed": "set up the site",
}


def record(
    action: str,
    target: Any = None,
    *,
    label: str | None = None,
    details: dict[str, Any] | None = None,
    actor: Any = None,
) -> AuditEntry:
    """Add a log entry to the session (the caller commits)."""
    if actor is None and has_request_context():
        from copydesk.auth import current_user

        actor = current_user if current_user.is_authenticated else None
    entry = AuditEntry(
        action=action,
        actor_id=getattr(actor, "id", None),
        target_type=type(target).__name__.lower() if target is not None else "",
        target_id=getattr(target, "id", None),
        target_label=(label if label is not None else _label(target))[:255],
        details=details or {},
    )
    db.session.add(entry)
    return entry


def _label(target: Any) -> str:
    if target is None:
        return ""
    for attr in ("display_title", "display_name", "name", "title", "email", "slug"):
        value = getattr(target, attr, None)
        if value:
            return str(value)
    return f"#{getattr(target, 'id', '?')}"


def describe(entry: AuditEntry) -> str:
    return ACTIONS.get(entry.action, entry.action.replace(".", " "))
