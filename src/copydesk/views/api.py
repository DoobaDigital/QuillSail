"""A small read-only JSON API, plus newsletter sign-up.

Handy for showing the latest issue on another website, or for building a
custom sign-up form. Only public content is exposed. See docs/api.md.
"""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, request
from sqlalchemy import select

from copydesk import __version__, settings, subscribers
from copydesk import permissions as perms
from copydesk.auth import current_user
from copydesk.db import db
from copydesk.helpers import external_url, json_object, paginate
from copydesk.models import Article, Issue, Section, Tag, article_tags
from copydesk.security import csrf_exempt, too_many
from copydesk.text import body_excerpt, excerpt, render_body, render_markdown
from copydesk.utils import is_valid_email, normalize_email

bp = Blueprint("api", __name__, url_prefix="/api/v1")


@bp.before_request
def _readable():
    if request.method == "OPTIONS" or request.endpoint == "api.subscribe":
        return None
    if not perms.has(current_user, "read"):
        abort(403, description="This publication is private.")
    return None


@bp.after_request
def _cors(response):
    origin = request.headers.get("Origin")
    if request.endpoint == "api.subscribe":
        allowed = [o.rstrip("/") for o in settings.get("newsletter.embed_origins") or []]
        if origin and (not allowed or origin.rstrip("/") in allowed):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.vary.add("Origin")
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    else:
        response.headers["Access-Control-Allow-Origin"] = "*"
        if request.method == "GET" and response.status_code == 200:
            response.headers.setdefault("Cache-Control", "public, max-age=60")
    return response


def _page_meta(page) -> dict:
    return {"page": page.page, "pages": page.pages, "total": page.total, "per_page": page.per_page}


def author_json(user) -> dict:
    return {
        "name": user.display_name,
        "username": None if user.is_deleted else user.username,
        "url": None if user.is_deleted else external_url("public.person", username=user.username),
        "groups": [m.group.label for m in user.badge_memberships],
    }


def article_json(article: Article, *, full: bool = False) -> dict:
    data = {
        "slug": article.slug,
        "title": article.display_title,
        "subtitle": article.subtitle,
        "url": external_url("public.article", slug=article.slug),
        "summary": article.excerpt or article.subtitle or body_excerpt(article),
        "section": {"slug": article.section.slug, "name": article.section.name} if article.section else None,
        "tags": [t.name for t in article.tags],
        "authors": [author_json(a) for a in article.authors],
        "published_at": article.published_at.isoformat() + "Z" if article.published_at else None,
        "word_count": article.word_count,
        "cover_image": external_url("public.upload", path=article.cover_image) if article.cover_image else None,
        "cover_alt": article.cover_alt or None,
        "source_url": article.source_url or None,
        "source_author": article.source_author or None,
    }
    if full:
        data["html"] = str(render_body(article))
        data["body_format"] = article.body_format
        data["source"] = article.body
        # Kept for existing clients. HTML articles have no Markdown to offer.
        data["markdown"] = None if article.body_format == "html" else article.body
    return data


def issue_json(issue: Issue, *, full: bool = False) -> dict:
    data = {
        "number": issue.number,
        "title": issue.display_title,
        "url": external_url("public.issue", number=issue.number),
        "sent_at": issue.sent_at.isoformat() + "Z" if issue.sent_at else None,
        "published_at": issue.published_at.isoformat() + "Z" if issue.published_at else None,
        "summary": excerpt(issue.intro) if issue.intro else "",
        "articles": [
            {"title": a.display_title, "url": external_url("public.article", slug=a.slug)}
            for item in issue.items for a in [item.article]
            if not item.audience_groups and a and a.is_published and a.visibility == "public"
        ],
    }
    if full:
        data["intro_html"] = str(render_markdown(issue.intro))
        items = []
        for item in issue.items:
            if item.audience_groups:
                continue  # items for particular groups aren't public
            if item.kind == "article" and item.article and item.article.is_published and item.article.visibility == "public":
                items.append({"type": "article", **article_json(item.article)})
            elif item.kind == "heading":
                items.append({"type": "heading", "title": item.title})
            elif item.kind == "text":
                items.append({"type": "text", "title": item.title, "html": str(render_markdown(item.body))})
        data["items"] = items
    return data


def _public_articles():
    return select(Article).where(
        Article.status == "published", Article.published_at.is_not(None), Article.visibility == "public"
    )


@bp.get("/")
def index():
    return jsonify(
        name=settings.get("site.name"),
        description=settings.get("site.description") or settings.get("site.tagline"),
        url=external_url("public.home"),
        copydesk_version=__version__,
        endpoints={
            "issues": external_url("api.issues"),
            "articles": external_url("api.articles"),
            "sections": external_url("api.sections"),
            "subscribe": external_url("api.subscribe"),
        },
    )


@bp.get("/issues")
def issues():
    page = paginate(select(Issue).where(Issue.published_at.is_not(None)).order_by(Issue.number.desc()), per_page=20)
    return jsonify(issues=[issue_json(i) for i in page.items], **_page_meta(page))


@bp.get("/issues/latest")
def latest_issue():
    issue = db.session.scalars(
        select(Issue).where(Issue.published_at.is_not(None)).order_by(Issue.number.desc()).limit(1)
    ).first()
    if issue is None:
        abort(404, description="No issues have been published yet.")
    return jsonify(issue_json(issue, full=True))


@bp.get("/issues/<int:number>")
def issue(number: int):
    item = db.session.scalar(select(Issue).where(Issue.number == number, Issue.published_at.is_not(None)))
    if item is None:
        abort(404, description="No published issue with that number.")
    return jsonify(issue_json(item, full=True))


@bp.get("/articles")
def articles():
    stmt = _public_articles()
    section_slug = request.args.get("section")
    if section_slug:
        stmt = stmt.join(Section, Section.id == Article.section_id).where(Section.slug == section_slug)
    tag_slug = request.args.get("tag")
    if tag_slug:
        stmt = stmt.join(article_tags, article_tags.c.article_id == Article.id).join(
            Tag, Tag.id == article_tags.c.tag_id
        ).where(Tag.slug == tag_slug)
    page = paginate(stmt.order_by(Article.published_at.desc()), per_page=20)
    return jsonify(articles=[article_json(a) for a in page.items], **_page_meta(page))


@bp.get("/articles/<slug>")
def article(slug: str):
    item = db.session.scalar(_public_articles().where(Article.slug == slug))
    if item is None:
        abort(404, description="No public article at that address.")
    return jsonify(article_json(item, full=True))


@bp.get("/sections")
def sections():
    rows = db.session.scalars(select(Section).order_by(Section.position, Section.name)).all()
    return jsonify(sections=[
        {"slug": s.slug, "name": s.name, "description": s.description, "url": external_url("public.section", slug=s.slug)}
        for s in rows
    ])


@bp.route("/subscribe", methods=["POST", "OPTIONS"])
@csrf_exempt
def subscribe():
    if request.method == "OPTIONS":
        return "", 204
    data = json_object() if request.is_json else request.form
    if not isinstance(data.get("email"), str) or not isinstance(data.get("name", ""), str):
        abort(400, description="Email and name must be text.")
    if data.get("website"):
        return jsonify(status="pending"), 202
    email = normalize_email(data.get("email"))
    if not is_valid_email(email):
        return jsonify(error="invalid_email", message="Enter a valid email address."), 400
    if too_many("api-subscribe", 10, 3600):
        return jsonify(error="rate_limited", message="Too many sign-ups from here. Try again later."), 429
    if request.is_json:
        wanted = data.get("groups") or []
    else:
        wanted = [slug.strip() for value in data.getlist("groups") for slug in value.split(",") if slug.strip()]
    if not isinstance(wanted, list) or not all(isinstance(slug, str) for slug in wanted):
        abort(400, description="Groups must be a list of group names.")
    offered = {g.slug: g for g in subscribers.signup_groups()} if settings.get("newsletter.ask_audience") else {}
    subscriber, outcome = subscribers.subscribe(
        email,
        name=str(data.get("name") or "")[:100],
        groups=[offered[slug] for slug in dict.fromkeys(wanted) if slug in offered],
        source="api",
    )
    if outcome == "already":
        from copydesk import notify

        notify.send("already_subscribed", subscriber.email,
                    f"You're already subscribed to {notify.site_name()}",
                    subscriber=subscriber, **notify.subscriber_links(subscriber))
    db.session.commit()
    return jsonify(status="pending", message="Check your inbox to confirm your subscription."), 202
