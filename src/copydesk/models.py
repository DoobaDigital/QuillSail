"""Database tables.

A quick map:

* ``User``: a person with an account. Writers, editors and admins are all users.
* ``Group``: a named set of people with permissions. Some groups are *roles*
  (Editors, Administrators) and some are *audiences*, the reader types you
  define, such as Students, Staff and Alumni. ``Everyone`` and ``Members`` are
  implicit: nobody is added to them by hand.
* ``GroupMembership``: a user's place in a group, which may be pending approval
  and may carry custom profile fields (a major, a graduation year).
* ``Subscriber``: an email address that receives the newsletter. A subscriber may
  or may not have an account.
* ``Article``: a piece of writing at any stage, from draft to published.
  ``ArticleRevision`` keeps every saved version, and ``ArticleEvent`` is the
  editorial conversation (comments and status changes).
* ``Issue``: one edition of the newsletter, made of ordered ``IssueItem`` rows.
  ``Delivery`` records each email sent.
* ``Job``: background work such as sending email.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from copydesk.db import Base
from copydesk.utils import utcnow

# Built-in group slugs.
EVERYONE = "everyone"
MEMBERS = "members"
EDITORS = "editors"
ADMINS = "admins"
IMPLICIT_GROUPS = (EVERYONE, MEMBERS)

JOIN_POLICIES = ("open", "approval", "closed")
GROUP_COLORS = ("gray", "blue", "green", "purple", "orange", "red", "teal", "pink", "gold")

ARTICLE_STATUSES = (
    "draft",
    "submitted",
    "in_review",
    "changes_requested",
    "accepted",
    "published",
    "declined",
    "withdrawn",
)
VISIBILITIES = ("public", "members", "groups")
ISSUE_STATUSES = ("draft", "scheduled", "sending", "sent")
SUBSCRIBER_STATUSES = ("pending", "active", "unsubscribed", "bounced")


# --------------------------------------------------------------------------- people


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    website: Mapped[str] = mapped_column(String(255), default="")
    avatar: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    blocked_reason: Mapped[str] = mapped_column(String(255), default="")
    email_verified_at: Mapped[datetime | None] = mapped_column(default=None)
    auth_version: Mapped[int] = mapped_column(default=1)
    notification_prefs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)

    memberships: Mapped[list[GroupMembership]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="GroupMembership.user_id",
    )

    is_authenticated = True

    def __repr__(self) -> str:
        return f"<User {self.id} {self.username}>"

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def active_memberships(self) -> list[GroupMembership]:
        return sorted(
            (m for m in self.memberships if m.status == "active"),
            key=lambda m: (m.group.position, m.group.name),
        )

    @property
    def groups(self) -> list[Group]:
        return [m.group for m in self.active_memberships]

    @property
    def audience_memberships(self) -> list[GroupMembership]:
        if not self.is_verified or not self.is_active or self.is_deleted:
            return []
        return [m for m in self.active_memberships if m.group.is_audience]

    @property
    def badge_memberships(self) -> list[GroupMembership]:
        return [m for m in self.audience_memberships if m.group.show_badge]

    def membership(self, group: Group) -> GroupMembership | None:
        for m in self.memberships:
            if m.group_id == group.id:
                return m
        return None

    def in_group(self, slug: str) -> bool:
        return any(m.group.slug == slug for m in self.active_memberships)

    @property
    def initials(self) -> str:
        parts = [p for p in (self.display_name or self.username or "?").split() if p]
        letters = "".join(p[0] for p in parts[:2]) or "?"
        return letters.upper()

    def pref(self, key: str, default: bool = True) -> bool:
        return bool((self.notification_prefs or {}).get(key, default))


class AnonymousUser:
    """Stand-in for "nobody is signed in", so templates can always use current_user."""

    id = None
    is_authenticated = False
    is_verified = False
    is_active = False
    is_deleted = False
    display_name = "Guest"
    username = ""
    email = ""
    memberships: list = []
    active_memberships: list = []
    groups: list = []
    audience_memberships: list = []

    def in_group(self, slug: str) -> bool:
        return False

    def pref(self, key: str, default: bool = True) -> bool:
        return default


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(60))
    member_label: Mapped[str] = mapped_column(String(60), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    is_system: Mapped[bool] = mapped_column(default=False)
    is_implicit: Mapped[bool] = mapped_column(default=False)
    is_audience: Mapped[bool] = mapped_column(default=False)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    join_policy: Mapped[str] = mapped_column(String(20), default="closed")
    auto_join_domains: Mapped[list[str]] = mapped_column(JSON, default=list)
    color: Mapped[str] = mapped_column(String(20), default="gray")
    show_badge: Mapped[bool] = mapped_column(default=True)
    byline_template: Mapped[str] = mapped_column(String(160), default="")
    on_signup_form: Mapped[bool] = mapped_column(default=True)
    fields: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    position: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    memberships: Mapped[list[GroupMembership]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Group {self.slug}>"

    @property
    def label(self) -> str:
        """What one member is called: "Student" for the group "Students"."""
        return self.member_label or self.name

    @property
    def is_admin_group(self) -> bool:
        return self.slug == ADMINS

    @property
    def self_service(self) -> bool:
        """Can people ask to join this group themselves?"""
        return self.slug != ADMINS and self.join_policy in ("open", "approval") and not self.is_implicit

    def field(self, key: str) -> dict[str, Any] | None:
        for spec in self.fields or []:
            if spec.get("key") == key:
                return spec
        return None


class GroupMembership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (UniqueConstraint("user_id", "group_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    source: Mapped[str] = mapped_column(String(20), default="admin")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
    decided_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    user: Mapped[User] = relationship(back_populates="memberships", foreign_keys=[user_id])
    group: Mapped[Group] = relationship(back_populates="memberships")
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id])

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"

    def public_fields(self) -> list[tuple[str, str]]:
        """(label, value) pairs this member chose to show on their profile."""
        out = []
        for spec in self.group.fields or []:
            value = (self.data or {}).get(spec.get("key"))
            if spec.get("public") and value not in (None, ""):
                out.append((spec.get("label", spec.get("key")), str(value)))
        return out

    def byline_detail(self) -> str:
        """The group's byline template filled in, or "" if a field it needs is empty."""
        template = (self.group.byline_template or "").strip()
        if not template:
            return ""
        values = {k: v for k, v in (self.data or {}).items() if v not in (None, "")}
        try:
            return template.format_map(_StrictMap(values))
        except (KeyError, ValueError, IndexError):
            return ""


class _StrictMap(dict):
    def __missing__(self, key):
        raise KeyError(key)


subscriber_groups = Table(
    "subscriber_groups",
    Base.metadata,
    Column("subscriber_id", ForeignKey("subscribers.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)


class Subscriber(Base):
    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True, default=None
    )
    source: Mapped[str] = mapped_column(String(20), default="form")
    bounce_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(default=None)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(default=None)
    last_sent_at: Mapped[datetime | None] = mapped_column(default=None)

    groups: Mapped[list[Group]] = relationship(secondary=subscriber_groups, order_by="Group.position")
    user: Mapped[User | None] = relationship()

    def __repr__(self) -> str:
        return f"<Subscriber {self.email} {self.status}>"

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def audience_ids(self) -> set[int]:
        """Audience groups this subscriber chose, plus any verified ones from their account."""
        ids = {g.id for g in self.groups}
        if self.user is not None:
            ids |= {m.group_id for m in self.user.audience_memberships}
        return ids


# --------------------------------------------------------------------------- content


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(default=0)
    accepts_submissions: Mapped[bool] = mapped_column(default=True)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(60))


article_tags = Table(
    "article_tags",
    Base.metadata,
    Column("article_id", ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

article_groups = Table(
    "article_groups",
    Base.metadata,
    Column("article_id", ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)


class ArticleAuthor(Base):
    __tablename__ = "article_authors"

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(default=0)

    user: Mapped[User] = relationship()


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(140), unique=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    source_url: Mapped[str] = mapped_column(String(2048), default="")
    source_author: Mapped[str] = mapped_column(String(200), default="")
    newsletter_blurb: Mapped[str] = mapped_column(String(5000), default="")
    subtitle: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    body_format: Mapped[str] = mapped_column(String(20), default="markdown")
    excerpt: Mapped[str] = mapped_column(Text, default="")
    cover_image: Mapped[str] = mapped_column(String(255), default="")
    cover_alt: Mapped[str] = mapped_column(String(300), default="")
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("sections.id", ondelete="SET NULL"), default=None
    )
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    visibility: Mapped[str] = mapped_column(String(20), default="public")
    author_note: Mapped[str] = mapped_column(Text, default="")
    assigned_editor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    featured: Mapped[bool] = mapped_column(default=False)
    word_count: Mapped[int] = mapped_column(default=0)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(default=None)
    published_at: Mapped[datetime | None] = mapped_column(default=None, index=True)

    section: Mapped[Section | None] = relationship()
    author_links: Mapped[list[ArticleAuthor]] = relationship(
        order_by=ArticleAuthor.position, cascade="all, delete-orphan"
    )
    tags: Mapped[list[Tag]] = relationship(secondary=article_tags, order_by=Tag.name)
    visibility_groups: Mapped[list[Group]] = relationship(secondary=article_groups)
    assigned_editor: Mapped[User | None] = relationship(foreign_keys=[assigned_editor_id])
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    events: Mapped[list[ArticleEvent]] = relationship(
        order_by="ArticleEvent.created_at, ArticleEvent.id",
        cascade="all, delete-orphan",
        back_populates="article",
    )

    def __repr__(self) -> str:
        return f"<Article {self.id} {self.status} {self.slug}>"

    @property
    def authors(self) -> list[User]:
        return [link.user for link in self.author_links]

    @property
    def author(self) -> User | None:
        return self.author_links[0].user if self.author_links else None

    def has_author(self, user: Any) -> bool:
        return getattr(user, "id", None) is not None and any(
            link.user_id == user.id for link in self.author_links
        )

    @property
    def is_published(self) -> bool:
        return self.status == "published" and self.published_at is not None

    @property
    def display_title(self) -> str:
        return self.title.strip() or "Untitled"

    @property
    def summary(self) -> str:
        """Restricted bodies never become an automatically generated public teaser."""
        from copydesk.text import body_excerpt

        return self.excerpt or self.subtitle or (body_excerpt(self) if self.visibility == "public" else "")


class ArticleRevision(Base):
    __tablename__ = "article_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    title: Mapped[str] = mapped_column(String(200), default="")
    subtitle: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    body_format: Mapped[str] = mapped_column(String(20), default="markdown")
    summary: Mapped[str] = mapped_column(String(255), default="")
    word_count: Mapped[int] = mapped_column(default=0)

    user: Mapped[User | None] = relationship()


class ArticleRedirect(Base):
    """An address an imported post used to have. Old links keep working through it."""

    __tablename__ = "article_redirects"

    id: Mapped[int] = mapped_column(primary_key=True)
    old_path: Mapped[str] = mapped_column(String(512), unique=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    article: Mapped[Article] = relationship()


class ArticleEvent(Base):
    """One entry in an article's editorial timeline: a comment or a change."""

    __tablename__ = "article_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    kind: Mapped[str] = mapped_column(String(20), default="comment")
    body: Mapped[str] = mapped_column(Text, default="")
    from_status: Mapped[str | None] = mapped_column(String(20), default=None)
    to_status: Mapped[str | None] = mapped_column(String(20), default=None)
    internal: Mapped[bool] = mapped_column(default=False)

    article: Mapped[Article] = relationship(back_populates="events")
    user: Mapped[User | None] = relationship()


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    show_in_nav: Mapped[bool] = mapped_column(default=False)
    nav_position: Mapped[int] = mapped_column(default=0)
    is_published: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    updated_by: Mapped[User | None] = relationship()


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(255), unique=True)
    original_name: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[int] = mapped_column(default=0)
    width: Mapped[int] = mapped_column(default=0)
    height: Mapped[int] = mapped_column(default=0)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    user: Mapped[User | None] = relationship()


# --------------------------------------------------------------------------- newsletter

issue_groups = Table(
    "issue_groups",
    Base.metadata,
    Column("issue_id", ForeignKey("issues.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)

issue_item_groups = Table(
    "issue_item_groups",
    Base.metadata,
    Column("item_id", ForeignKey("issue_items.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(unique=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str] = mapped_column(String(255), default="")
    preheader: Mapped[str] = mapped_column(String(255), default="")
    intro: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    audience_mode: Mapped[str] = mapped_column(String(20), default="all")
    publish_articles: Mapped[bool] = mapped_column(default=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(default=None)
    send_started_at: Mapped[datetime | None] = mapped_column(default=None)
    sent_at: Mapped[datetime | None] = mapped_column(default=None)
    published_at: Mapped[datetime | None] = mapped_column(default=None)
    recipient_count: Mapped[int] = mapped_column(default=0)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)

    audience_groups: Mapped[list[Group]] = relationship(secondary=issue_groups, order_by="Group.position")
    items: Mapped[list[IssueItem]] = relationship(
        order_by="IssueItem.position, IssueItem.id",
        cascade="all, delete-orphan",
        back_populates="issue",
    )
    created_by: Mapped[User | None] = relationship()

    def __repr__(self) -> str:
        return f"<Issue #{self.number} {self.status}>"

    @property
    def display_title(self) -> str:
        return self.title.strip() or f"Issue #{self.number}"

    @property
    def is_editable(self) -> bool:
        return self.status in ("draft", "scheduled")

    @property
    def is_public(self) -> bool:
        return self.published_at is not None

    @property
    def articles(self) -> list[Article]:
        return [item.article for item in self.items if item.kind == "article" and item.article]


class IssueItem(Base):
    __tablename__ = "issue_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(default=0)
    kind: Mapped[str] = mapped_column(String(20), default="article")
    article_id: Mapped[int | None] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), default=None
    )
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    display: Mapped[str] = mapped_column(String(20), default="summary")

    issue: Mapped[Issue] = relationship(back_populates="items")
    article: Mapped[Article | None] = relationship()
    audience_groups: Mapped[list[Group]] = relationship(
        secondary=issue_item_groups, order_by="Group.position"
    )

    def audience_ids(self) -> set[int]:
        return {g.id for g in self.audience_groups}

    def visible_to(self, audience_ids: set[int] | None) -> bool:
        """None means "show everything" (used for previews and the web archive for editors)."""
        if audience_ids is None or not self.audience_groups:
            return True
        return bool(self.audience_ids() & audience_ids)


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("issue_id", "subscriber_id"),
        Index("ix_deliveries_issue_status", "issue_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"))
    subscriber_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscribers.id", ondelete="SET NULL"), default=None
    )
    email: Mapped[str] = mapped_column(String(254), default="")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(default=None)

    subscriber: Mapped[Subscriber | None] = relationship()


# --------------------------------------------------------------------------- system


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_pick", "status", "run_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    priority: Mapped[int] = mapped_column(default=100)
    run_at: Mapped[datetime] = mapped_column(default=utcnow)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=5)
    last_error: Mapped[str] = mapped_column(Text, default="")
    locked_by: Mapped[str] = mapped_column(String(64), default="")
    locked_at: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AuditEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[int | None] = mapped_column(default=None)
    target_label: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    actor: Mapped[User | None] = relationship()


class RateLimit(Base):
    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(191), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(default=utcnow)
    count: Mapped[int] = mapped_column(default=0)


class EmailConnection(Base):
    """One publication sender; credentials are encrypted with the instance secret."""

    __tablename__ = "email_connection"
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    connection_id: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class EmailOAuthFlow(Base):
    __tablename__ = "email_oauth_flows"
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    auth_version: Mapped[int] = mapped_column()
    provider: Mapped[str] = mapped_column(String(16))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Competition(Base):
    __tablename__ = "competitions"
    __table_args__ = (
        CheckConstraint("mode IN ('judges', 'readers', 'both')", name="ck_competition_mode"),
        CheckConstraint("status IN ('draft', 'submissions', 'judging', 'closed', 'results')", name="ck_competition_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), default="")
    rules: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), default="")
    mode: Mapped[str] = mapped_column(String(16), default="both")
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    entries_close_at: Mapped[datetime | None] = mapped_column(default=None)
    ends_at: Mapped[datetime | None] = mapped_column(default=None)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    version: Mapped[int] = mapped_column(default=1)
    results: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    results_at: Mapped[datetime | None] = mapped_column(default=None)
    entries: Mapped[list[CompetitionEntry]] = relationship(back_populates="competition", cascade="all, delete-orphan")
    judges: Mapped[list[CompetitionJudge]] = relationship(cascade="all, delete-orphan")


class CompetitionEntry(Base):
    __tablename__ = "competition_entries"
    __table_args__ = (
        UniqueConstraint("competition_id", "user_id", name="uq_competition_entrant"),
        CheckConstraint("status IN ('pending', 'approved', 'rejected', 'withdrawn')", name="ck_competition_entry_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), default="")
    project_url: Mapped[str] = mapped_column(String(2048), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    moderation_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
    competition: Mapped[Competition] = relationship(back_populates="entries")
    author: Mapped[User | None] = relationship()


class CompetitionJudge(Base):
    __tablename__ = "competition_judges"
    __table_args__ = (UniqueConstraint("competition_id", "user_id", name="uq_competition_judge"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user: Mapped[User] = relationship()


class CompetitionScore(Base):
    __tablename__ = "competition_scores"
    __table_args__ = (
        UniqueConstraint("entry_id", "judge_id", name="uq_competition_score"),
        CheckConstraint("score >= 0 AND score <= 100", name="ck_competition_score_range"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("competition_entries.id", ondelete="CASCADE"), index=True)
    judge_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    score: Mapped[int] = mapped_column()
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
    judge: Mapped[User] = relationship()


class CompetitionVote(Base):
    __tablename__ = "competition_votes"
    __table_args__ = (UniqueConstraint("competition_id", "user_id", name="uq_competition_vote"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id", ondelete="CASCADE"), index=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("competition_entries.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class IssuePreview(Base):
    """A revocable, expiring capability for one draft issue's public-audience content."""

    __tablename__ = "issue_previews"
    id: Mapped[int] = mapped_column(primary_key=True)
    issue_id: Mapped[int] = mapped_column(ForeignKey("issues.id", ondelete="CASCADE"), unique=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    issue: Mapped[Issue] = relationship()


class BusinessInquiry(Base):
    __tablename__ = "business_inquiries"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization: Mapped[str] = mapped_column(String(160))
    contact_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254))
    website_url: Mapped[str] = mapped_column(String(2048), default="")
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[str] = mapped_column(String(500), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    compensation: Mapped[str] = mapped_column(String(200), default="")
    deadline: Mapped[date | None] = mapped_column(default=None)
    application_url: Mapped[str] = mapped_column(String(2048), default="")
    share_contact: Mapped[bool] = mapped_column(default=False)
    consented_at: Mapped[datetime] = mapped_column(default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(20), default="unverified", index=True)
    staff_notes: Mapped[str] = mapped_column(Text, default="")
    article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
    article: Mapped[Article | None] = relationship()


class HostingConnection(Base):
    """One opt-in provider connection; secrets use a separate encryption context."""
    __tablename__ = 'hosting_connection'
    version: Mapped[int] = mapped_column(default=1)
    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default='connected')
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class ManagedRecord(Base):
    """A provider record and its exact original value, for safe conditional undo."""
    __tablename__ = 'managed_records'
    __table_args__ = (UniqueConstraint('zone_id', 'provider_id', name='uq_managed_record'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(253))
    type: Mapped[str] = mapped_column(String(10))
    value: Mapped[str] = mapped_column(Text)
    previous: Mapped[str | None] = mapped_column(Text, default=None)
    purpose: Mapped[str] = mapped_column(String(32), default='website')
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class EdgeReceipt(Base):
    """Durable replay receipt; no subscriber PII or token is stored here."""
    __tablename__ = 'edge_receipts'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(default=utcnow)


class HostingOAuthFlow(Base):
    __tablename__ = 'hosting_oauth_flows'
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    auth_version: Mapped[int] = mapped_column()
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
