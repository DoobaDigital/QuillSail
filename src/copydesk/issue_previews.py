"""Share a draft without publishing it or granting access to restricted articles."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from sqlalchemy import select

from copydesk import audit, newsletter
from copydesk.db import db
from copydesk.helpers import external_url, state
from copydesk.models import Issue, IssuePreview, User
from copydesk.text import body_text, email_html, render_body
from copydesk.utils import slugify, utcnow


def create(issue: Issue, actor: User, slug: str = "", days: int = 30) -> str:
    if issue.status != "draft" or issue.is_public:
        raise newsletter.IssueError("Private links are available for unpublished draft issues only.")
    slug = slugify(slug or f"preview-{secrets.token_hex(6)}", 80, "")
    if not slug or slug.isdigit():
        raise newsletter.IssueError("Choose a preview address containing letters.")
    existing = db.session.scalar(select(IssuePreview).where(IssuePreview.slug == slug))
    if existing and existing.issue_id != issue.id:
        raise newsletter.IssueError("Another preview already uses that address.")
    link = db.session.scalar(select(IssuePreview).where(IssuePreview.issue_id == issue.id))
    token = secrets.token_urlsafe(32)
    if link is None:
        link = IssuePreview(issue_id=issue.id)
        db.session.add(link)
    link.slug = slug
    link.token_hash = hashlib.sha256(token.encode()).hexdigest()
    link.expires_at = utcnow() + timedelta(days=max(1, min(days, 90)))
    link.created_at = utcnow()
    audit.record("issue.preview_shared", issue, actor=actor)
    return external_url("public.shared_issue", slug=slug, key=token)


def revoke(issue: Issue, actor: User) -> None:
    link = db.session.scalar(select(IssuePreview).where(IssuePreview.issue_id == issue.id))
    if link:
        db.session.delete(link)
        audit.record("issue.preview_revoked", issue, actor=actor)


def resolve(slug: str, token: str) -> IssuePreview | None:
    if not token or len(token) > 200:
        return None
    link = db.session.scalar(select(IssuePreview).where(IssuePreview.slug == slug))
    digest = hashlib.sha256(token.encode()).hexdigest()
    if (link is None or not hmac.compare_digest(link.token_hash, digest)
            or link.expires_at <= utcnow() or link.issue.status != "draft" or link.issue.is_public):
        return None
    return link


def public_items(issue: Issue, accent: str, *, email: bool = False) -> list[newsletter.PreparedItem]:
    prepared = newsletter.prepare_items(issue, accent, email=email, include_unpublished=True)
    items = [item for item in newsletter.visible(prepared, set())
             if item.article is None or item.article.visibility == "public"]
    for item in items:
        if item.article is not None and not item.article.is_published:
            item.web_html = render_body(item.article)
            item.html = email_html(item.web_html, accent, state().config.origin) if email else item.web_html
            item.text = body_text(item.article)
            item.display = "full"
    return items
