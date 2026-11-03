"""Putting issues together and sending them.

Sending happens in the background:

1. An editor presses Send (or a scheduled time arrives). The issue becomes
   "sending" and an ``issue.prepare`` job is queued.
2. ``issue.prepare`` publishes the issue (and any accepted articles in it) on
   the website, works out who should receive it, and creates one ``Delivery``
   per recipient. Those are split into ``issue.batch`` jobs.
3. Each ``issue.batch`` job sends its emails over one SMTP connection, pacing
   itself to stay under the configured rate. Every delivery is recorded, so a
   completed deliveries survive a later failure in the batch. SMTP acceptance
   followed by a process crash can still result in a duplicate on retry.
4. When no deliveries are left waiting, the issue becomes "sent".

Personalization: an issue item can be limited to some audience groups (say, a
reunion notice just for Alumni). Each subscriber gets the items meant for
their groups, plus every item meant for everyone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from flask import render_template
from sqlalchemy import func, select, update

from copydesk import appearance, audit, jobs, settings, workflow
from copydesk.colors import accent_tokens
from copydesk.db import db
from copydesk.email_connections import effective_mail_config
from copydesk.helpers import external_url, state
from copydesk.mail import Email, Mailer, MailError
from copydesk.models import Article, Delivery, Group, Issue, IssueItem, Job, Subscriber, User
from copydesk.notify import reply_to_address, unsubscribe_headers
from copydesk.text import body_text, email_html, render_body, render_markdown
from copydesk.utils import join_names, slugify, utcnow

log = logging.getLogger("copydesk.newsletter")

MAX_DELIVERY_ATTEMPTS = 3
BOUNCES_BEFORE_DISABLE = 3


class IssueError(Exception):
    pass


# --------------------------------------------------------------------------- issues


def next_number() -> int:
    return (db.session.scalar(select(func.max(Issue.number))) or 0) + 1


def create(actor: User, title: str = "") -> Issue:
    issue = Issue(number=next_number(), title=title.strip()[:200], created_by_id=actor.id)
    db.session.add(issue)
    db.session.flush()
    audit.record("issue.created", issue, actor=actor)
    return issue


def default_subject(issue: Issue) -> str:
    """The subject line built from the "Default subject line" setting."""
    template = settings.get("newsletter.subject_format") or "{site} #{number}: {title}"
    subject = (
        template.replace("{site}", settings.get("site.name"))
        .replace("{number}", str(issue.number))
        .replace("{title}", (issue.title or "").strip() or f"Issue {issue.number}")
    )
    return subject.strip().rstrip(":").strip()


def subject_for(issue: Issue) -> str:
    return (issue.subject or "").strip() or default_subject(issue)


def audience_label(issue: Issue) -> str:
    if issue.audience_mode != "groups" or not issue.audience_groups:
        return "Everyone"
    return join_names([g.name for g in issue.audience_groups])


def recipients(issue: Issue) -> list[Subscriber]:
    subs = list(
        db.session.scalars(select(Subscriber).where(Subscriber.status == "active").order_by(Subscriber.id)).all()
    )
    if issue.audience_mode == "groups":
        wanted = {g.id for g in issue.audience_groups}
        subs = [s for s in subs if s.audience_ids() & wanted] if wanted else []
    return state().hooks.apply_filters("issue.recipients", subs, issue=issue)


def eligible_articles(issue: Issue) -> list[Article]:
    """Accepted and published articles that could be added to this issue."""
    in_issue = {item.article_id for item in issue.items if item.article_id}
    rows = db.session.scalars(
        select(Article)
        .where(Article.status.in_(("accepted", "published")))
        .order_by(Article.status, Article.updated_at.desc())
        .limit(200)
    ).all()
    return [a for a in rows if a.id not in in_issue]


def issues_containing(article_ids: list[int]) -> dict[int, list[int]]:
    if not article_ids:
        return {}
    rows = db.session.execute(
        select(IssueItem.article_id, Issue.number)
        .join(Issue, Issue.id == IssueItem.issue_id)
        .where(IssueItem.article_id.in_(article_ids))
        .order_by(Issue.number)
    ).all()
    result: dict[int, list[int]] = {}
    for article_id, number in rows:
        result.setdefault(article_id, []).append(number)
    return result


def add_article(issue: Issue, article: Article) -> IssueItem:
    for existing in issue.items:
        if existing.kind == "article" and (existing.article_id == article.id or existing.article is article):
            return existing
    item = IssueItem(
        kind="article",
        article=article,
        position=len(issue.items),
        display=settings.get("newsletter.default_display") or "summary",
    )
    issue.items.append(item)
    return item


def set_article_display(item: IssueItem, display: str) -> None:
    if display not in {"summary", "full", "blurb"}:
        raise IssueError("Choose the full article, the creator's blurb, or a summary and link.")
    if display == "blurb" and not (item.article and item.article.newsletter_blurb.strip()):
        raise IssueError("This article has no creator blurb. Choose a summary or the full article.")
    item.display = display


def add_block(issue: Issue, kind: str, title: str = "", body: str = "") -> IssueItem:
    if kind not in ("text", "heading"):
        raise IssueError("Unknown item type.")
    item = IssueItem(kind=kind, title=title.strip()[:200], body=body, position=len(issue.items))
    issue.items.append(item)
    return item


def renumber(issue: Issue) -> None:
    for position, item in enumerate(sorted(issue.items, key=lambda i: (i.position, i.id or 0))):
        item.position = position


def move(issue: Issue, item: IssueItem, direction: int) -> None:
    renumber(issue)
    ordered = sorted(issue.items, key=lambda i: i.position)
    index = ordered.index(item)
    swap = index + direction
    if 0 <= swap < len(ordered):
        ordered[index].position, ordered[swap].position = ordered[swap].position, ordered[index].position


def reorder(issue: Issue, item_ids: list[int]) -> None:
    positions = {item_id: pos for pos, item_id in enumerate(item_ids)}
    for item in issue.items:
        item.position = positions.get(item.id, len(positions) + item.position)
    renumber(issue)


def problems(issue: Issue) -> list[str]:
    """Reasons this issue can't be sent yet."""
    found = []
    if not issue.items and not issue.intro.strip():
        found.append("The issue is empty. Add an introduction or at least one item.")
    for item in issue.items:
        if item.kind == "article" and item.article is None:
            found.append("One of the articles in this issue was deleted. Remove it from the issue.")
        elif item.kind == "article" and item.article.status not in ("accepted", "published"):
            found.append(f"“{item.article.display_title}” is no longer accepted. Remove it or accept it again.")
        elif item.kind == "article" and item.display == "blurb" and not item.article.newsletter_blurb.strip():
            found.append(f"“{item.article.display_title}” has no creator blurb. Choose a summary or the full article.")
    if issue.audience_mode == "groups" and not issue.audience_groups:
        found.append("You chose to send to particular groups but didn't pick any.")
    return found


# --------------------------------------------------------------------------- rendering


@dataclass
class PreparedItem:
    kind: str
    title: str = ""
    url: str = ""
    section: str = ""
    byline: str = ""
    summary: str = ""
    text: str = ""
    html: Any = ""
    web_html: Any = ""
    reading_minutes: int = 0
    display: str = "summary"
    audience_ids: set[int] = field(default_factory=set)
    audience_labels: list[str] = field(default_factory=list)
    article: Article | None = None


def prepare_items(
    issue: Issue, accent: str, *, email: bool = True, include_unpublished: bool = False,
) -> list[PreparedItem]:
    """Render each item once. With ``email=False`` the HTML is for the web archive."""
    origin = state().config.origin

    def for_email(html):
        return email_html(html, accent, origin) if email and html else html

    prepared = []
    for item in sorted(issue.items, key=lambda i: i.position):
        groups = list(item.audience_groups)
        common = {
            "audience_ids": {g.id for g in groups},
            "audience_labels": [g.name for g in groups],
        }
        if item.kind == "article":
            article = item.article
            if article is None or (not email and not include_unpublished and not article.is_published):
                continue
            full_allowed = item.display == "full" and article.visibility == "public"
            body_html = render_body(article) if full_allowed else ""
            prepared.append(PreparedItem(
                kind="article",
                title=article.display_title,
                url=external_url("public.article", slug=article.slug),
                section=article.section.name if article.section else "",
                byline=join_names([a.display_name for a in article.authors]),
                summary=(article.newsletter_blurb.strip() if item.display == "blurb"
                         else item.body.strip() or article.summary),
                text=body_text(article) if full_allowed else "",
                html=for_email(body_html),
                web_html=body_html,
                reading_minutes=max(1, round(article.word_count / 230)) if article.word_count else 0,
                display="full" if full_allowed else "summary",
                article=article,
                **common,
            ))
        elif item.kind == "heading":
            prepared.append(PreparedItem(kind="heading", title=item.title, **common))
        else:
            body = render_markdown(item.body)
            prepared.append(PreparedItem(
                kind="text", title=item.title, text=item.body, html=for_email(body), web_html=body, **common
            ))
    return prepared


def visible(items: list[PreparedItem], audience_ids: set[int] | None) -> list[PreparedItem]:
    if audience_ids is None:
        return items
    return [i for i in items if not i.audience_ids or i.audience_ids & audience_ids]


def render(
    issue: Issue,
    *,
    subscriber: Subscriber | None = None,
    audience_ids: set[int] | None = None,
    items: list[PreparedItem] | None = None,
    test: bool = False,
    preview_url: str = "",
) -> tuple[str, str, str]:
    """Render (subject, html, text) for one recipient, or for a preview."""
    tokens = accent_tokens(settings.get("appearance.accent_color"))
    if items is None:
        items = prepare_items(issue, tokens["accent"])
    if subscriber is not None and audience_ids is None:
        audience_ids = subscriber.audience_ids()
    shown = visible(items, audience_ids)
    if subscriber is not None and subscriber.token:
        manage_url = external_url("subscribe.manage", token=subscriber.token)
        unsubscribe_url = external_url("subscribe.unsubscribe", token=subscriber.token)
    else:
        manage_url = unsubscribe_url = external_url("subscribe.subscribe")
    groups = [g for g in (subscriber.groups if subscriber else []) if g.is_audience]
    context = {
        "issue": issue,
        "items": shown,
        "intro_html": email_html(render_markdown(issue.intro), tokens["accent"], state().config.origin)
        if issue.intro.strip() else "",
        "intro_text": issue.intro.strip(),
        "subscriber": subscriber,
        "subscriber_groups": groups,
        "manage_url": manage_url,
        "unsubscribe_url": unsubscribe_url,
        "web_url": preview_url or external_url("public.issue", number=issue.number),
        "shared_preview": bool(preview_url),
        "test": test,
        "subject": subject_for(issue),
    }
    html = appearance.inline_email_css(render_template("email/issue.html", **context))
    text = render_template("email/issue.txt", **context)
    subject = ("[Test] " if test else "") + subject_for(issue)
    return subject, html, text.strip() + "\n"


def build_email(issue: Issue, subscriber: Subscriber, items: list[PreparedItem]) -> Email:
    subject, html, text = render(issue, subscriber=subscriber, items=items)
    site = settings.get("site.name")
    headers = unsubscribe_headers(external_url("subscribe.unsubscribe", token=subscriber.token))
    headers["List-Id"] = f"{site} <{slugify(site, 40, 'newsletter')}.{state().config.server_name.split(':')[0]}>"
    headers["X-Copydesk-Issue"] = str(issue.number)
    return Email(
        to=subscriber.email,
        subject=subject,
        text=text,
        html=html,
        from_name=site,
        from_email=effective_mail_config().from_email,
        reply_to=reply_to_address(),
        headers=headers,
        category="newsletter",
    )


# --------------------------------------------------------------------------- sending


def send_test(issue: Issue, addresses: list[str], audience_ids: set[int] | None, actor: User) -> None:
    for address in addresses[:10]:
        subject, html, text = render(issue, audience_ids=audience_ids, test=True)
        email = Email(
            to=address, subject=subject, text=text, html=html,
            from_name=settings.get("site.name"), from_email=effective_mail_config().from_email,
            reply_to=reply_to_address(), category="newsletter",
        )
        jobs.enqueue("mail.send", email.to_payload(), priority=jobs.PRIORITY_URGENT, max_attempts=3)
    audit.record("issue.test_sent", issue, actor=actor, details={"to": addresses[:10]})


def schedule(issue: Issue, when: datetime, actor: User) -> None:
    if not issue.is_editable:
        raise IssueError("This issue has already been sent.")
    if when <= utcnow() + timedelta(minutes=1):
        raise IssueError("Pick a time in the future.")
    issue.status = "scheduled"
    issue.scheduled_at = when
    issue.updated_at = utcnow()
    audit.record("issue.scheduled", issue, actor=actor, details={"at": when.isoformat()})
    state().hooks.fire("issue.scheduled", issue=issue)


def unschedule(issue: Issue, actor: User) -> None:
    if issue.status != "scheduled":
        return
    issue.status = "draft"
    issue.scheduled_at = None
    audit.record("issue.unscheduled", issue, actor=actor)


def start_sending(issue: Issue, actor: User | None) -> None:
    if issue.status not in ("draft", "scheduled"):
        raise IssueError("This issue is already sending or has been sent.")
    found = problems(issue)
    if found:
        raise IssueError(found[0])
    now = utcnow()
    result = db.session.execute(
        update(Issue).where(Issue.id == issue.id, Issue.status.in_(("draft", "scheduled")))
        .values(status="sending", send_started_at=now, updated_at=now)
    )
    if result.rowcount != 1:
        raise IssueError("This issue is already sending or has been sent.")
    db.session.refresh(issue)
    jobs.enqueue("issue.prepare", {"issue_id": issue.id, "actor_id": getattr(actor, "id", None)},
                 priority=jobs.PRIORITY_NORMAL, max_attempts=5)
    audit.record("issue.sending", issue, actor=actor)
    state().hooks.fire("issue.sending", issue=issue)


def publish_web(issue: Issue, actor: User) -> None:
    """Put an issue on the website without emailing it (useful for back issues)."""
    if issue.published_at is None:
        issue.published_at = utcnow()
        if issue.publish_articles:
            for article in issue.articles:
                if article.status == "accepted":
                    workflow.publish(article, actor)
        audit.record("issue.published", issue, actor=actor)


def start_due_issues() -> int:
    due = db.session.scalars(
        select(Issue).where(Issue.status == "scheduled", Issue.scheduled_at <= utcnow())
    ).all()
    started = 0
    for issue in due:
        try:
            start_sending(issue, issue.created_by)
            started += 1
        except IssueError as exc:
            log.error("Scheduled issue #%s couldn't be sent: %s", issue.number, exc)
            result = db.session.execute(
                update(Issue).where(Issue.id == issue.id, Issue.status == "scheduled")
                .values(status="draft", scheduled_at=None)
            )
            if result.rowcount == 1:
                audit.record("issue.unscheduled", issue, actor=None, details={"reason": str(exc)})
    resume_stalled()
    return started


def resume_stalled() -> None:
    """Re-queue batches for issues whose sending jobs were lost (for example, deleted)."""
    sending = db.session.scalars(
        select(Issue).where(Issue.status == "sending", Issue.send_started_at < utcnow() - timedelta(minutes=10))
    ).all()
    if not sending:
        return
    pending_jobs = db.session.scalars(
        select(Job).where(Job.kind.in_(("issue.prepare", "issue.batch")), Job.status.in_(("queued", "running")))
    ).all()
    busy = {job.payload.get("issue_id") for job in pending_jobs}
    for issue in sending:
        if issue.id in busy:
            continue
        has_deliveries = db.session.scalar(select(func.count()).where(Delivery.issue_id == issue.id))
        if not has_deliveries:
            jobs.enqueue("issue.prepare", {"issue_id": issue.id}, priority=jobs.PRIORITY_NORMAL)
        else:
            _queue_batches(issue)
            _finish_if_done(issue.id)


def batch_size() -> int:
    rate = effective_mail_config().rate_per_minute
    return max(10, min(200, rate * 2))


def _queue_batches(issue: Issue) -> int:
    ids = list(db.session.scalars(
        select(Delivery.id).where(Delivery.issue_id == issue.id, Delivery.status == "queued").order_by(Delivery.id)
    ).all())
    size = batch_size()
    for start in range(0, len(ids), size):
        jobs.enqueue("issue.batch", {"issue_id": issue.id, "delivery_ids": ids[start:start + size]},
                     priority=jobs.PRIORITY_BULK, max_attempts=10)
    return len(ids)


def _finish_if_done(issue_id: int) -> bool:
    waiting = db.session.scalar(
        select(func.count()).where(Delivery.issue_id == issue_id, Delivery.status == "queued")
    )
    if waiting:
        return False
    result = db.session.execute(
        update(Issue).where(Issue.id == issue_id, Issue.status == "sending").values(status="sent", sent_at=utcnow())
    )
    db.session.commit()
    if result.rowcount == 1:
        issue = db.session.get(Issue, issue_id, populate_existing=True)
        audit.record("issue.sent", issue, actor=None, details=delivery_stats(issue))
        db.session.commit()
        state().hooks.fire("issue.sent", issue=issue)
        db.session.commit()
        return True
    return False


@jobs.handler("issue.prepare")
def _prepare_job(payload: dict[str, Any]) -> None:
    issue = db.session.get(Issue, payload.get("issue_id"))
    if issue is None or issue.status != "sending":
        return
    actor = db.session.get(User, payload["actor_id"]) if payload.get("actor_id") else issue.created_by
    if issue.published_at is None:
        issue.published_at = utcnow()
    if issue.publish_articles:
        for article in issue.articles:
            if article.status == "accepted":
                workflow.publish(article, actor)
    db.session.commit()

    existing = set(db.session.scalars(select(Delivery.subscriber_id).where(Delivery.issue_id == issue.id)).all())
    new_rows = [
        {"issue_id": issue.id, "subscriber_id": s.id, "email": s.email, "status": "queued", "created_at": utcnow()}
        for s in recipients(issue)
        if s.id not in existing
    ]
    if new_rows:
        db.session.execute(Delivery.__table__.insert(), new_rows)
    issue.recipient_count = db.session.scalar(select(func.count()).where(Delivery.issue_id == issue.id)) or 0
    db.session.commit()
    _queue_batches(issue)
    db.session.commit()
    _finish_if_done(issue.id)


@jobs.handler("issue.batch")
def _batch_job(payload: dict[str, Any]) -> None:
    if settings.get('hosting.edge'):
        from copydesk import edge

        # Process offline opt-outs before contacting the mail server. If the
        # provider cannot be reached, retry the batch instead of sending blindly.
        edge.replay({})
        db.session.commit()
    issue = db.session.get(Issue, payload.get("issue_id"))
    if issue is None or issue.status != "sending":
        return
    ids = payload.get("delivery_ids") or []
    deliveries = db.session.scalars(
        select(Delivery).where(Delivery.id.in_(ids), Delivery.status == "queued").order_by(Delivery.id)
    ).all()
    tokens = accent_tokens(settings.get("appearance.accent_color"))
    items = prepare_items(issue, tokens["accent"])
    hooks = state().hooks
    retry_error: str | None = None
    with Mailer() as mailer:
        for delivery in deliveries:
            jobs.renew_lease()
            db.session.commit()
            subscriber = delivery.subscriber
            if subscriber is None or subscriber.status != "active":
                delivery.status = "skipped"
                db.session.commit()
                continue
            email = hooks.apply_filters("mail.before_send", build_email(issue, subscriber, items))
            if email is None:
                delivery.status = "skipped"
                db.session.commit()
                continue
            delivery.attempts += 1
            try:
                mailer.send(email)
            except MailError as exc:
                delivery.error = str(exc)[:1000]
                if exc.permanent:
                    delivery.status = "failed"
                    subscriber.bounce_count += 1
                    if subscriber.bounce_count >= BOUNCES_BEFORE_DISABLE:
                        subscriber.status = "bounced"
                elif delivery.attempts >= MAX_DELIVERY_ATTEMPTS:
                    delivery.status = "failed"
                else:
                    retry_error = str(exc)
                    break
            else:
                delivery.status = "sent"
                delivery.sent_at = utcnow()
                delivery.error = ""
                subscriber.last_sent_at = delivery.sent_at
            jobs.renew_lease()
            db.session.commit()
    db.session.commit()
    if retry_error:
        raise jobs.RetryLater(f"Mail server problem, will retry: {retry_error}", delay=120)
    _finish_if_done(issue.id)


def delivery_stats(issue: Issue) -> dict[str, int]:
    rows = db.session.execute(
        select(Delivery.status, func.count()).where(Delivery.issue_id == issue.id).group_by(Delivery.status)
    ).all()
    stats = {"queued": 0, "sent": 0, "failed": 0, "skipped": 0}
    stats.update(dict(rows))
    stats["total"] = sum(stats.values())
    return stats


def retry_failed(issue: Issue, actor: User) -> int:
    """Try failed deliveries of a sent issue again."""
    failed = db.session.scalars(
        select(Delivery).where(Delivery.issue_id == issue.id, Delivery.status == "failed")
    ).all()
    for delivery in failed:
        delivery.status = "queued"
        delivery.attempts = 0
    if failed:
        issue.status = "sending"
        db.session.flush()
        _queue_batches(issue)
    return len(failed)


def audience_choices() -> list[Group]:
    return list(
        db.session.scalars(select(Group).where(Group.is_audience.is_(True)).order_by(Group.position)).all()
    )
