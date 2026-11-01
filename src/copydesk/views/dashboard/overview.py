"""Dashboard home: what needs attention, at a glance."""

from __future__ import annotations

from datetime import timedelta

from flask import flash, redirect, render_template, url_for
from sqlalchemy import func, select

from copydesk import audit, jobs, newsletter, publication, settings
from copydesk import permissions as perms
from copydesk.auth import current_user
from copydesk.db import db
from copydesk.email_connections import public_status
from copydesk.helpers import state
from copydesk.models import Article, Group, GroupMembership, Issue, Job, Subscriber, User
from copydesk.utils import utcnow
from copydesk.views.dashboard import bp


def system_warnings() -> list[tuple[str, str]]:
    """Problems an administrator should fix, as (kind, message) pairs."""
    warnings: list[tuple[str, str]] = []
    config = state().config
    counts = jobs.queue_counts()
    last_seen = jobs.worker_last_seen()
    stale = last_seen is None or utcnow() - last_seen > timedelta(minutes=5)
    if counts.get("queued", 0) and stale:
        warnings.append(("error", f"{counts['queued']} background jobs (such as emails) are waiting, but no worker "
                                  "has run in the last 5 minutes. Start `quillsail worker`, or see System status."))
    if counts.get("failed"):
        warnings.append(("warning", f"{counts['failed']} background jobs failed. See System status for details."))
    mail_status = public_status()
    if mail_status.get("problem"):
        warnings.append(("error", "Email needs attention. Open Settings → Email to reconnect your sender."))
    if mail_status["provider"] in ("console", "file", "memory") and not config.debug:
        warnings.append(("warning", f"Email is set to the “{mail_status['provider']}” backend, so no real email is "
                                    "being sent. Connect Gmail, Outlook, or an SMTP server in Settings → Email."))
    return warnings


def setup_checklist() -> list[tuple[bool, str, str, str]]:
    """First-run tasks for a new site: (done, label, link, skip link or "")."""
    has_tagline = bool(settings.get("site.tagline"))
    audience_domains = db.session.scalars(select(Group).where(Group.is_audience.is_(True))).all()
    has_domains = any(g.auto_join_domains for g in audience_domains)
    issue_count = db.session.scalar(select(func.count()).select_from(Issue)) or 0
    smtp = public_status()["connected"]
    if publication.is_blog():
        reader_site = "blog and newsletter" if publication.has_newsletter() else "blog"
    else:
        reader_site = "newsletter"
    items = [(settings.get("onboarding.appearance") in ("done", "skipped"),
              f"Change the appearance of your dashboard and {reader_site}",
              url_for("dash.settings", tab="appearance"), url_for("dash.skip_appearance"))]
    if publication.is_blog():
        post_count = db.session.scalar(select(func.count()).select_from(Article).where(Article.status == "published")) or 0
        items += [(has_tagline, "Add a tagline and description", url_for("dash.settings"), ""),
                  (post_count > 0, "Write and publish your first blog post", url_for("write.index"), "")]
        if publication.has_newsletter():
            items += [(smtp, "Connect an email account", url_for("dash.email_settings"), ""),
                      (issue_count > 0, "Create an optional newsletter issue", url_for("dash.issues"), "")]
        return items
    return items + [
        (has_tagline, "Add a tagline and description", url_for("dash.settings"), ""),
        (smtp, "Connect Gmail, Outlook, or an email server", url_for("dash.email_settings"), ""),
        (has_domains, "Tell QuillSail which email domains identify students or staff", url_for("dash.groups"), ""),
        (issue_count > 0, "Put together your first issue", url_for("dash.issues"), ""),
    ]


@bp.post("/getting-started/appearance/skip")
@perms.require("manage_settings")
def skip_appearance():
    settings.set_value("onboarding.appearance", "skipped")
    audit.record("settings.updated", None, actor=current_user, label="Getting started",
                 details={"keys": ["onboarding.appearance"]})
    db.session.commit()
    flash("Skipped. You can change the appearance anytime in Settings → Appearance.", "info")
    return redirect(url_for("dash.overview"))


@bp.get("/")
def overview():
    context: dict = {"dash_active": "overview"}
    if perms.has(current_user, "review"):
        context["waiting"] = db.session.scalars(
            select(Article).where(Article.status.in_(("submitted", "in_review")))
            .order_by(Article.submitted_at).limit(6)
        ).all()
        status_counts = dict(db.session.execute(
            select(Article.status, func.count()).group_by(Article.status)
        ).all())
        context["status_counts"] = status_counts
        context["mine"] = db.session.scalars(
            select(Article).where(
                Article.assigned_editor_id == current_user.id,
                Article.status.in_(("submitted", "in_review", "changes_requested", "accepted")),
            ).order_by(Article.updated_at.desc()).limit(5)
        ).all()
    if publication.has_newsletter() and perms.has(current_user, "manage_subscribers"):
        context["subscriber_count"] = db.session.scalar(
            select(func.count()).where(Subscriber.status == "active")
        ) or 0
        context["new_subscribers"] = db.session.scalar(
            select(func.count()).where(
                Subscriber.status == "active", Subscriber.confirmed_at >= utcnow() - timedelta(days=30)
            )
        ) or 0
    if perms.has(current_user, "manage_users"):
        context["member_count"] = db.session.scalar(
            select(func.count()).where(User.deleted_at.is_(None), User.email_verified_at.is_not(None))
        ) or 0
        context["requests"] = db.session.scalars(
            select(GroupMembership).where(GroupMembership.status == "pending")
            .order_by(GroupMembership.created_at).limit(5)
        ).all()
    if publication.has_newsletter() and perms.has(current_user, "manage_issues"):
        context["last_issue"] = db.session.scalars(
            select(Issue).where(Issue.status.in_(("sent", "sending"))).order_by(Issue.number.desc()).limit(1)
        ).first()
        if context["last_issue"]:
            context["last_stats"] = newsletter.delivery_stats(context["last_issue"])
        context["upcoming"] = db.session.scalars(
            select(Issue).where(Issue.status.in_(("draft", "scheduled"))).order_by(Issue.number).limit(3)
        ).all()
    if perms.has(current_user, "manage_settings"):
        context["warnings"] = system_warnings()
        checklist = setup_checklist()
        context["checklist"] = checklist if not all(done for done, *_ in checklist) else []
    context["failed_jobs"] = 0
    if perms.has(current_user, "manage_settings"):
        context["failed_jobs"] = db.session.scalar(select(func.count()).where(Job.status == "failed")) or 0
    return render_template("dashboard/overview.html", **context)
