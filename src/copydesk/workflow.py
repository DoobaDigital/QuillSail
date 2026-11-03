"""The editorial workflow: how a piece of writing gets from draft to published.

    draft ──submit──▶ submitted ──start review──▶ in review ──accept──▶ accepted ──publish──▶ published
                          │                           │
                          └──────request changes──────┴──▶ changes requested ──resubmit──▶ submitted

Editors can also decline a piece. Writers can withdraw theirs and later move
it back to drafts. Every move is recorded on the article's timeline, written
to the activity log, emailed to the people involved, and announced to
extensions as ``article.status_changed``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from copydesk import audit, notify, publication, settings
from copydesk import permissions as perms
from copydesk.db import db
from copydesk.helpers import state
from copydesk.models import (
    Article,
    ArticleAuthor,
    ArticleEvent,
    ArticleRedirect,
    ArticleRevision,
    Section,
    Tag,
    User,
)
from copydesk.text import BODY_FORMATS, DEFAULT_BODY_FORMAT, source_word_count
from copydesk.utils import slugify, utcnow


@dataclass(frozen=True)
class Status:
    key: str
    label: str
    tone: str  # neutral | info | warning | success | danger
    for_writer: str
    for_editor: str


STATUSES: dict[str, Status] = {
    s.key: s
    for s in (
        Status("draft", "Draft", "neutral",
               "Only you (and any co-authors) can see this. Submit it when you're ready for an editor to read it.",
               "The writer hasn't submitted this yet."),
        Status("submitted", "Submitted", "info",
               "We've got it. An editor will pick it up soon, and you'll get an email when they do.",
               "Waiting for an editor to pick it up."),
        Status("in_review", "In review", "info",
               "An editor is reading your piece. You'll hear back by email.",
               "An editor is reviewing it."),
        Status("changes_requested", "Changes requested", "warning",
               "Your editor asked for some changes. Read their note below, edit your piece, then resubmit it.",
               "Waiting for the writer to make changes."),
        Status("accepted", "Accepted", "success",
               "Accepted! It will appear on the site or in an upcoming issue. We'll email you when it's live.",
               "Ready to publish or add to an issue."),
        Status("published", "Published", "success",
               "Your piece is live.",
               "Live on the site."),
        Status("declined", "Declined", "danger",
               "This piece won't be published. If your editor left a note, it's below.",
               "Declined."),
        Status("withdrawn", "Withdrawn", "neutral",
               "You withdrew this piece. You can move it back to your drafts at any time.",
               "The writer withdrew it."),
    )
}


@dataclass(frozen=True)
class Transition:
    action: str
    label: str
    sources: tuple[str, ...]
    target: str
    by: str  # "writer" or "editor"
    permission: str | None = None
    message: str = "none"  # none | optional | required
    message_label: str = ""
    style: str = "secondary"
    confirm: str = ""


TRANSITIONS: dict[str, Transition] = {
    t.action: t
    for t in (
        Transition("submit", "Submit for review", ("draft",), "submitted", "writer", style="primary"),
        Transition("resubmit", "Resubmit", ("changes_requested",), "submitted", "writer",
                   message="optional", message_label="What did you change? (optional)", style="primary"),
        Transition("withdraw", "Withdraw", ("submitted", "in_review", "changes_requested", "accepted"),
                   "withdrawn", "writer", confirm="Withdraw this piece? Editors will stop working on it."),
        Transition("reopen", "Move back to drafts", ("withdrawn", "declined"), "draft", "writer"),
        Transition("start_review", "Start review", ("submitted",), "in_review", "editor", "review", style="primary"),
        Transition("request_changes", "Request changes", ("submitted", "in_review", "accepted"), "changes_requested",
                   "editor", "review", message="required",
                   message_label="What should the writer change? They'll see this."),
        Transition("accept", "Accept", ("submitted", "in_review", "changes_requested"), "accepted", "editor",
                   "review", message="optional", message_label="A note for the writer (optional)", style="primary"),
        Transition("decline", "Decline", ("submitted", "in_review", "changes_requested", "accepted"), "declined",
                   "editor", "review", message="optional",
                   message_label="Why? A kind, specific note helps the writer (optional, they'll see it)",
                   style="danger"),
        Transition("publish", "Publish now", ("draft", "submitted", "in_review", "accepted"), "published",
                   "editor", "publish", style="primary",
                   confirm="Publish this article on the website now?"),
        Transition("unpublish", "Unpublish", ("published",), "accepted", "editor", "publish",
                   confirm="Take this article off the website? It goes back to Accepted."),
        Transition("reconsider", "Reopen review", ("declined", "withdrawn"), "in_review", "editor", "review"),
    )
}

WRITER_EDITABLE = ("draft", "changes_requested")


class WorkflowError(Exception):
    pass


# --------------------------------------------------------------------------- permissions


def can_view(user: Any, article: Article) -> bool:
    """Can ``user`` read this article on the public site?"""
    if article.is_published:
        if article.visibility == "public":
            return perms.has(user, "read")
        if article.visibility == "members":
            return perms.has(user, "read_members") or perms.has(user, "review")
        if article.visibility == "groups":
            if not getattr(user, "is_verified", False) or not user.is_active or user.is_deleted:
                return False
            if perms.has(user, "review"):
                return True
            allowed = {g.id for g in article.visibility_groups}
            return any(m.group_id in allowed for m in getattr(user, "active_memberships", []))
        return False
    return can_see_submission(user, article)


def can_see_submission(user: Any, article: Article) -> bool:
    """Writers see their own work; reviewers see everything that's been submitted."""
    if not getattr(user, "is_authenticated", False):
        return False
    if article.has_author(user):
        return True
    if article.status == "draft":
        return False  # drafts stay private until they're submitted
    return perms.has(user, "review")


def can_edit(user: Any, article: Article) -> bool:
    if not getattr(user, "is_authenticated", False) or not user.is_verified:
        return False
    if perms.has(user, "edit_any") and article.status != "draft":
        return True
    if publication.is_blog() and article.has_author(user) and perms.has(user, "publish") and article.status in ("draft", "published", "accepted"):
        return True
    return article.has_author(user) and article.status in WRITER_EDITABLE and perms.has(user, "submit")


def allowed_transitions(user: Any, article: Article) -> list[Transition]:
    result = []
    for transition in TRANSITIONS.values():
        if article.status not in transition.sources:
            continue
        if transition.by == "writer":
            if transition.action in ("submit", "resubmit") and not (
                perms.has(user, "submit") or perms.has(user, "publish")
            ):
                continue
            if article.has_author(user):
                result.append(transition)
        elif transition.permission and perms.has(user, transition.permission):
            if transition.action == "publish" and article.status == "draft" and not article.has_author(user):
                continue  # editors can't publish someone else's unsubmitted draft
            result.append(transition)
    return result


def writer_transitions(user: Any, article: Article) -> list[Transition]:
    return [t for t in allowed_transitions(user, article) if t.by == "writer"]


def editor_transitions(user: Any, article: Article) -> list[Transition]:
    return [t for t in allowed_transitions(user, article) if t.by == "editor"]


# --------------------------------------------------------------------------- changes


def unique_slug(title: str, exclude_id: int | None = None) -> str:
    base = slugify(title, 100, "untitled")
    candidate, number = base, 2
    while True:
        query = select(Article.id).where(Article.slug == candidate)
        if exclude_id:
            query = query.where(Article.id != exclude_id)
        if db.session.scalar(query) is None:
            return candidate
        candidate = f"{base}-{number}"
        number += 1


def slug_exists(slug: str) -> bool:
    return db.session.scalar(select(Article.id).where(Article.slug == slug)) is not None


def create_draft(user: User, title: str = "") -> Article:
    article = Article(
        title=title.strip(),
        slug=unique_slug(title or f"draft-{utcnow():%Y%m%d%H%M%S}"),
        created_by_id=user.id,
        status="draft",
    )
    article.author_links.append(ArticleAuthor(user_id=user.id, position=0))
    db.session.add(article)
    db.session.flush()
    audit.record("article.created", article, actor=user)
    state().hooks.fire("article.created", article=article)
    return article


def save(
    article: Article,
    actor: User,
    *,
    title: str,
    subtitle: str,
    body: str,
    summary: str = "",
    body_format: str | None = None,
) -> ArticleRevision | None:
    """Update the text. A new revision is kept only if something changed."""
    title, subtitle = title.strip()[:200], subtitle.strip()[:300]
    body = body.replace("\r\n", "\n")
    body_format = body_format or article.body_format or DEFAULT_BODY_FORMAT
    if body_format not in BODY_FORMATS:
        raise WorkflowError("That isn't a format this piece can be written in.")
    changed = (title, subtitle, body, body_format) != (
        article.title, article.subtitle, article.body, article.body_format,
    )
    article.title, article.subtitle, article.body = title, subtitle, body
    article.body_format = body_format
    article.word_count = source_word_count(body, body_format)
    article.updated_at = utcnow()
    if article.status == "draft" and article.slug.startswith("draft-") and title:
        article.slug = unique_slug(title, exclude_id=article.id)
    if not changed:
        return None
    revision = ArticleRevision(
        article_id=article.id,
        user_id=actor.id,
        title=title,
        subtitle=subtitle,
        body=body,
        body_format=body_format,
        summary=summary.strip()[:255],
        word_count=article.word_count,
    )
    db.session.add(revision)
    if not article.has_author(actor):
        audit.record("article.edited", article, actor=actor, details={"summary": revision.summary})
    state().hooks.fire("article.saved", article=article, revision=revision)
    return revision


def set_tags(article: Article, names: list[str]) -> None:
    tags = []
    for name in names[:12]:
        name = name.strip()[:60]
        slug = slugify(name, 60, "")
        if not slug:
            continue
        tag = db.session.scalar(select(Tag).where(Tag.slug == slug))
        if tag is None:
            tag = Tag(slug=slug, name=name)
            db.session.add(tag)
        if tag not in tags:
            tags.append(tag)
    article.tags = tags


def set_section(article: Article, section_id: int | None) -> None:
    article.section_id = section_id if section_id and db.session.get(Section, section_id) else None


def set_coauthors(article: Article, users: list[User]) -> None:
    """Keep the primary author first and replace everyone else."""
    primary = article.author_links[0].user_id if article.author_links else None
    wanted = [primary] + [u.id for u in users if u.id != primary]
    for link in list(article.author_links):
        if link.user_id not in wanted:
            article.author_links.remove(link)
    existing = {link.user_id: link for link in article.author_links}
    for position, user_id in enumerate(wanted):
        if user_id is None:
            continue
        link = existing.get(user_id)
        if link is None:
            article.author_links.append(ArticleAuthor(user_id=user_id, position=position))
        else:
            link.position = position


def transition(article: Article, action: str, actor: Any, message: str = "") -> str:
    """Apply a workflow action. Returns the new status, or raises WorkflowError."""
    move = TRANSITIONS.get(action)
    if move is None or move not in allowed_transitions(actor, article):
        raise WorkflowError("That action isn't available for this article right now.")
    message = (message or "").strip()
    if move.message == "required" and not message:
        raise WorkflowError("Please add a note explaining what to change.")
    if action in ("submit", "resubmit"):
        if not settings.get("submissions.enabled") and not perms.has(actor, "publish"):
            raise WorkflowError(settings.get("submissions.closed_message"))
        if settings.get("submissions.require_section") and not article.section_id:
            raise WorkflowError("Choose a section before you submit.")
        if article.section is not None and not article.section.accepts_submissions and not perms.has(actor, "publish"):
            raise WorkflowError("This section is not accepting submissions. Choose another section.")
        if not article.title.strip():
            raise WorkflowError("Give your piece a title before you submit it.")
        if source_word_count(article.body, article.body_format) < 20:
            raise WorkflowError("There isn't much here yet. Write at least a few sentences before submitting.")
    if action == "publish" and not article.title.strip():
        raise WorkflowError("Add a title before publishing.")

    old = article.status
    article.status = move.target
    now = utcnow()
    article.updated_at = now
    if move.target == "submitted":
        article.submitted_at = now
    if move.target == "published":
        article.published_at = article.published_at or now
        if article.slug.startswith("draft-"):
            article.slug = unique_slug(article.title, exclude_id=article.id)
    if action == "unpublish":
        article.published_at = None
    if action == "start_review" and article.assigned_editor_id is None and getattr(actor, "id", None):
        article.assigned_editor_id = actor.id

    event = ArticleEvent(
        article=article, user_id=getattr(actor, "id", None), kind="status",
        from_status=old, to_status=move.target, body=message, internal=False,
    )
    db.session.add(event)
    audit.record("article.status", article, actor=actor, details={"from": old, "to": move.target})

    hooks = state().hooks
    hooks.fire("article.status_changed", article=article, old=old, new=move.target, actor=actor, message=message)
    if move.target == "submitted":
        hooks.fire("article.submitted", article=article)
        if old == "draft":
            notify.submission_received(article)
        notify.new_submission(article, resubmitted=old != "draft")
    else:
        notify.status_changed(article, old, move.target, actor, message)
    if move.target == "published":
        hooks.fire("article.published", article=article)
    return move.target


def publish(article: Article, actor: Any) -> None:
    """Publish without permission checks (used when an issue goes out)."""
    if article.status == "published":
        return
    old = article.status
    article.status = "published"
    article.published_at = article.published_at or utcnow()
    article.updated_at = utcnow()
    db.session.add(ArticleEvent(article=article, user_id=getattr(actor, "id", None), kind="status",
                                from_status=old, to_status="published"))
    audit.record("article.status", article, actor=actor, details={"from": old, "to": "published"})
    state().hooks.fire("article.status_changed", article=article, old=old, new="published", actor=actor, message="")
    state().hooks.fire("article.published", article=article)
    notify.status_changed(article, old, "published", actor)


def import_article(
    *,
    actor: User,
    authors: list[User],
    title: str,
    slug: str,
    body: str,
    body_format: str,
    status: str,
    published_at: datetime | None,
    updated_at: datetime | None = None,
    excerpt: str = "",
    section_id: int | None = None,
    cover_image: str = "",
    cover_alt: str = "",
    featured: bool = False,
    tags: list[str] | tuple[str, ...] = (),
    source: str = "",
) -> Article:
    """Create an article brought in from another blog, keeping its original date.

    Unlike ``transition``, this fires no hooks and sends no email: these posts already
    reached their readers, and announcing a whole archive would flood every webhook and
    co-author. The timeline and the activity log still record it.
    """
    now = utcnow()
    article = Article(
        title=title.strip()[:200],
        slug=slug if not slug_exists(slug) else unique_slug(slug),
        body=body,
        body_format=body_format,
        excerpt=excerpt,
        section_id=section_id,
        cover_image=cover_image,
        cover_alt=cover_alt,
        featured=featured,
        status=status,
        word_count=source_word_count(body, body_format),
        created_by_id=actor.id,
        created_at=published_at or now,
        updated_at=updated_at or published_at or now,
        published_at=published_at,
    )
    for position, author in enumerate(authors):
        article.author_links.append(ArticleAuthor(user_id=author.id, position=position))
    db.session.add(article)
    db.session.flush()
    set_tags(article, list(tags))
    db.session.add(ArticleRevision(
        article_id=article.id, user_id=actor.id, title=article.title, subtitle="", body=body,
        body_format=body_format, summary="Imported", word_count=article.word_count,
        created_at=article.created_at,
    ))
    db.session.add(ArticleEvent(
        article=article, user_id=actor.id, kind="status", from_status="draft", to_status=status,
        body="Imported from another blog.", internal=False,
    ))
    audit.record("article.imported", article, actor=actor, details={"source": source})
    return article


def redirect_key(path: str) -> str:
    """One form for an old address, however it was linked: with or without / or .html."""
    key = "/" + (path or "").strip().lstrip("/")
    key = key.split("?")[0].split("#")[0]
    key = key.removesuffix("/index.html").removesuffix("/index.htm").removesuffix(".html").removesuffix(".htm")
    return key.rstrip("/")


def redirect_target(path: str) -> Article | None:
    """The published article that used to live at ``path``, if any."""
    key = redirect_key(path)
    if not key or len(key) > 512:
        return None
    row = db.session.scalar(select(ArticleRedirect).where(ArticleRedirect.old_path == key))
    return row.article if row is not None and row.article.is_published else None


def comment(article: Article, actor: User, body: str, *, internal: bool = False) -> ArticleEvent:
    body = body.strip()
    if not body:
        raise WorkflowError("Write a comment first.")
    if internal and not perms.has(actor, "review"):
        internal = False
    event = ArticleEvent(article=article, user_id=actor.id, kind="comment", body=body[:10000], internal=internal)
    event.user = actor
    db.session.add(event)
    db.session.flush()
    state().hooks.fire("article.commented", article=article, event=event)
    notify.comment_added(article, event)
    return event


def assign(article: Article, editor: User | None, actor: User) -> None:
    previous = article.assigned_editor_id
    article.assigned_editor_id = editor.id if editor else None
    if previous == article.assigned_editor_id:
        return
    text = f"Assigned to {editor.display_name}." if editor else "Unassigned."
    db.session.add(ArticleEvent(article=article, user_id=actor.id, kind="assign", body=text, internal=True))
    audit.record("article.assigned", article, actor=actor, details={"editor": editor.username if editor else None})
    if editor:
        notify.assigned(article, editor, actor)


def visible_events(article: Article, user: Any) -> list[ArticleEvent]:
    """The timeline as ``user`` may see it: writers don't see internal notes."""
    show_internal = perms.has(user, "review")
    return [e for e in article.events if show_internal or not e.internal]


def revisions(article: Article) -> list[ArticleRevision]:
    return list(
        db.session.scalars(
            select(ArticleRevision)
            .where(ArticleRevision.article_id == article.id)
            .order_by(ArticleRevision.created_at.desc(), ArticleRevision.id.desc())
        ).all()
    )


def counts_by_status() -> dict[str, int]:
    rows = db.session.execute(select(Article.status, func.count()).group_by(Article.status)).all()
    return dict(rows)
