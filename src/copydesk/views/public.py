"""The public website: home, articles, issues, people, pages, feeds and files."""

from __future__ import annotations

import hashlib

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from markupsafe import escape
from sqlalchemy import and_, func, or_, select, text

from copydesk import __version__, issue_previews, newsletter, publication, settings, workflow
from copydesk import permissions as perms
from copydesk.auth import current_user
from copydesk.colors import accent_tokens
from copydesk.db import db
from copydesk.helpers import external_url, first_or_404, paginate, state
from copydesk.models import (
    Article,
    Issue,
    IssueItem,
    Page,
    Section,
    Subscriber,
    Tag,
    User,
    article_tags,
)
from copydesk.subscribers import signup_groups
from copydesk.text import render_body, render_markdown
from copydesk.utils import utcnow

bp = Blueprint("public", __name__)

RESERVED_PAGE_SLUGS = frozenset(
    {"articles", "issues", "sections", "tags", "people", "search", "subscribe", "subscription",
     "unsubscribe", "login", "logout", "join", "account", "write", "dashboard", "api", "setup",
     "static", "uploads", "theme", "feed.xml", "sitemap.xml", "robots.txt", "healthz", "favicon.svg",
     "custom.css", "forgot-password", "reset-password", "verify-email", "competitions", "business"}
)


def require_read() -> None:
    """If the "Everyone" group can't read, the publication is private."""
    if not perms.has(current_user, "read"):
        if not current_user.is_authenticated:
            abort(redirect(url_for("auth.login", next=request.full_path.rstrip("?"))))
        abort(403)


def published_articles():
    return select(Article).where(Article.status == "published", Article.published_at.is_not(None))


def published_issues():
    return select(Issue).where(Issue.published_at.is_not(None))


def lock_reason(article: Article) -> str | None:
    """Why the current visitor can't read ``article`` (None if they can)."""
    if workflow.can_view(current_user, article):
        return None
    if article.visibility == "members":
        return "This article is for members. Sign in to read it."
    if article.visibility == "groups":
        names = ", ".join(g.name for g in article.visibility_groups) or "certain groups"
        return f"This article is only for {names}."
    return "You don't have access to this article."


@bp.app_context_processor
def _public_helpers():
    def issue_articles_for_reader(issue):
        audience = ({m.group_id for m in current_user.audience_memberships}
                    if current_user.is_verified else set())
        return [entry.article for entry in issue.items if entry.article and entry.article.is_published
                and entry.visible_to(audience) and workflow.can_view(current_user, entry.article)]

    return {"lock_reason": lock_reason, "issue_articles_for_reader": issue_articles_for_reader}


# --------------------------------------------------------------------------- pages


@bp.get("/")
def home():
    from copydesk import launch

    if launch.is_soon() and not launch.editor():
        return render_template("public/launching.html", signup_available=launch.signup_available(), groups=signup_groups())
    require_read()
    if publication.is_blog():
        page = paginate(published_articles().order_by(Article.published_at.desc(), Article.id.desc()), per_page=10)
        return render_template("public/blog_home.html", page=page, active_nav="articles", groups=signup_groups() if settings.get("newsletter.ask_audience") else [])
    latest_issue = db.session.scalars(published_issues().order_by(Issue.number.desc()).limit(1)).first()
    featured = db.session.scalars(
        published_articles().where(Article.featured.is_(True)).order_by(Article.published_at.desc()).limit(1)
    ).first()
    recent_query = published_articles().order_by(Article.published_at.desc()).limit(9)
    recent = [a for a in db.session.scalars(recent_query).all() if not featured or a.id != featured.id][:8]
    if featured is None and recent:
        featured, recent = recent[0], recent[1:]
    subscriber_count = 0
    if settings.get("appearance.show_subscriber_count"):
        subscriber_count = db.session.scalar(select(func.count()).where(Subscriber.status == "active")) or 0
    sections = db.session.scalars(select(Section).order_by(Section.position, Section.name)).all()
    return render_template(
        "public/home.html",
        latest_issue=latest_issue,
        featured=featured,
        recent=recent,
        subscriber_count=subscriber_count,
        groups=signup_groups() if settings.get("newsletter.ask_audience") else [],
        sections=sections,
    )


@bp.get("/articles/")
def articles():
    require_read()
    page = paginate(published_articles().order_by(Article.published_at.desc()), per_page=15)
    sections = db.session.scalars(select(Section).order_by(Section.position, Section.name)).all()
    return render_template("public/articles.html", page=page, sections=sections, active_nav="articles")


@bp.get("/articles/<slug>/")
def article(slug: str):
    require_read()
    item = first_or_404(select(Article).where(Article.slug == slug))
    preview = not item.is_published
    if preview and not workflow.can_see_submission(current_user, item):
        abort(404)
    reason = None if preview else lock_reason(item)
    issues = []
    if not preview:
        issues = db.session.scalars(
            published_issues()
            .join(IssueItem, IssueItem.issue_id == Issue.id)
            .where(IssueItem.article_id == item.id)
            .order_by(Issue.number)
        ).all()
    related = []
    if item.section_id and not preview:
        related = db.session.scalars(
            published_articles()
            .where(Article.section_id == item.section_id, Article.id != item.id)
            .order_by(Article.published_at.desc())
            .limit(3)
        ).all()
    return render_template(
        "public/article.html",
        article=item,
        preview=preview,
        locked_message=reason,
        issues=issues,
        related=related,
        groups=signup_groups() if settings.get("newsletter.ask_audience") else [],
        active_nav="articles",
        can_edit_post=workflow.can_edit(current_user, item),
        can_offer_post=item.is_published and current_user.is_verified and (item.has_author(current_user) or perms.has(current_user, "manage_issues")),
    )


@bp.get("/issues/")
def issues():
    require_read()
    page = paginate(published_issues().order_by(Issue.number.desc()), per_page=20)
    return render_template("public/issues.html", page=page, active_nav="issues")


@bp.get("/issues/<int:number>/")
def issue(number: int):
    require_read()
    item = first_or_404(select(Issue).where(Issue.number == number))
    can_manage = perms.has(current_user, "manage_issues")
    if not item.is_public and not can_manage:
        abort(404)
    tokens = accent_tokens(settings.get("appearance.accent_color"))
    prepared = newsletter.prepare_items(item, tokens["accent"], email=False, include_unpublished=can_manage)
    if can_manage:
        audience = None
    elif current_user.is_authenticated:
        audience = {m.group_id for m in current_user.audience_memberships}
    else:
        audience = set()
    visible = newsletter.visible(prepared, audience)
    hidden_count = len(prepared) - len(visible)
    newer = db.session.scalars(
        published_issues().where(Issue.number > item.number).order_by(Issue.number).limit(1)
    ).first()
    older = db.session.scalars(
        published_issues().where(Issue.number < item.number).order_by(Issue.number.desc()).limit(1)
    ).first()
    return render_template(
        "public/issue.html",
        issue=item,
        items=visible,
        hidden_count=hidden_count,
        preview=not item.is_public,
        newer=newer,
        older=older,
        groups=signup_groups() if settings.get("newsletter.ask_audience") else [],
        active_nav="issues",
    )


@bp.get("/issues/<slug>", strict_slashes=False)
def shared_issue(slug: str):
    link = issue_previews.resolve(slug, request.args.get("key", ""))
    if link is None:
        abort(404)
    tokens = accent_tokens(settings.get("appearance.accent_color"))
    email = request.args.get("format") == "email"
    items = issue_previews.public_items(link.issue, tokens["accent"], email=email)
    share_url = external_url("public.shared_issue", slug=slug, key=request.args["key"])
    if email:
        _subject, html, _text = newsletter.render(
            link.issue, items=items, audience_ids=set(), preview_url=share_url,
        )
        g.csp_override = "default-src 'none'; img-src https: data:; style-src 'unsafe-inline'; frame-ancestors 'self'; base-uri 'none'"
        return html
    return render_template("public/shared_issue.html", issue=link.issue, items=items,
                           share_url=share_url, expires_at=link.expires_at, active_nav="")


@bp.get("/sections/<slug>/")
def section(slug: str):
    require_read()
    item = first_or_404(select(Section).where(Section.slug == slug))
    page = paginate(
        published_articles().where(Article.section_id == item.id).order_by(Article.published_at.desc()), per_page=15
    )
    return render_template("public/section.html", section=item, page=page, active_nav="articles")


@bp.get("/tags/<slug>/")
def tag(slug: str):
    require_read()
    item = first_or_404(select(Tag).where(Tag.slug == slug))
    page = paginate(
        published_articles()
        .join(article_tags, article_tags.c.article_id == Article.id)
        .where(article_tags.c.tag_id == item.id)
        .order_by(Article.published_at.desc()),
        per_page=15,
    )
    return render_template("public/tag.html", tag=item, page=page, active_nav="articles")


@bp.get("/people/<username>/")
def person(username: str):
    require_read()
    user = first_or_404(select(User).where(User.username == username, User.deleted_at.is_(None)))
    from copydesk.models import ArticleAuthor

    query = (
        published_articles()
        .join(ArticleAuthor, ArticleAuthor.article_id == Article.id)
        .where(ArticleAuthor.user_id == user.id)
        .order_by(Article.published_at.desc())
    )
    page = paginate(query, per_page=15)
    is_self = current_user.is_authenticated and current_user.id == user.id
    if page.total == 0 and not is_self and not perms.has(current_user, "manage_users"):
        abort(404)
    return render_template("public/person.html", person=user, page=page, is_self=is_self)


@bp.get("/search")
def search():
    require_read()
    query_text = (request.args.get("q") or "").strip()[:100]
    page = None
    issue_hits = []
    if query_text:
        like = f"%{query_text.lower()}%"
        body_access = [Article.visibility == "public"]
        if perms.has(current_user, "read_members") or perms.has(current_user, "review"):
            body_access.append(Article.visibility == "members")
        if perms.has(current_user, "review"):
            body_access.append(Article.visibility == "groups")
        elif current_user.is_verified:
            from copydesk.models import article_groups

            group_ids = [m.group_id for m in current_user.audience_memberships]
            body_access.append(and_(Article.visibility == "groups", Article.id.in_(
                select(article_groups.c.article_id).where(article_groups.c.group_id.in_(group_ids))
            )))
        stmt = published_articles().where(
            or_(
                func.lower(Article.title).like(like),
                func.lower(Article.subtitle).like(like),
                and_(func.lower(Article.body).like(like), or_(*body_access)),
            )
        ).order_by(func.lower(Article.title).like(like).desc(), Article.published_at.desc())
        page = paginate(stmt, per_page=15)
        issue_hits = db.session.scalars(
            published_issues()
            .where(or_(func.lower(Issue.title).like(like), func.lower(Issue.intro).like(like)))
            .order_by(Issue.number.desc())
            .limit(5)
        ).all()
    return render_template("public/search.html", q=query_text, page=page, issue_hits=issue_hits)


@bp.get("/<slug>")
def page(slug: str):
    if slug in RESERVED_PAGE_SLUGS:
        abort(404)
    require_read()
    item = first_or_404(select(Page).where(Page.slug == slug))
    if not item.is_published and not perms.has(current_user, "manage_pages"):
        abort(404)
    return render_template("public/page.html", page=item, active_nav=f"page:{item.slug}")


# --------------------------------------------------------------------------- feeds and machine-readable files


def _atom(entries, title: str, self_url: str, alternate_url: str) -> Response:
    updated = max((e["updated"] for e in entries), default=utcnow())
    xml = render_template(
        "public/feed.xml", entries=entries, title=title, self_url=self_url,
        alternate_url=alternate_url, updated=updated,
    )
    return Response(xml, mimetype="application/atom+xml")


@bp.get("/feed.xml")
def feed():
    require_read()
    rows = db.session.scalars(
        published_articles().where(Article.visibility == "public").order_by(Article.published_at.desc()).limit(30)
    ).all()
    entries = [
        {
            "title": a.display_title,
            "url": external_url("public.article", slug=a.slug),
            "published": a.published_at,
            "updated": max(a.updated_at, a.published_at),
            "authors": [u.display_name for u in a.authors],
            "summary": a.excerpt or a.subtitle,
            "content_html": render_body(a),
            "category": a.section.name if a.section else "",
        }
        for a in rows
    ]
    return _atom(entries, settings.get("site.name"), external_url("public.feed"), external_url("public.articles"))


@bp.get("/issues/feed.xml")
def issues_feed():
    require_read()
    rows = db.session.scalars(published_issues().order_by(Issue.number.desc()).limit(30)).all()
    entries = [
        {
            "title": f"#{i.number}: {i.display_title}",
            "url": external_url("public.issue", number=i.number),
            "published": i.published_at,
            "updated": i.sent_at or i.published_at,
            "authors": [settings.get("site.name")],
            "summary": "",
            "content_html": render_markdown(i.intro),
            "category": "",
        }
        for i in rows
    ]
    title = f"{settings.get('site.name')}: issues"
    return _atom(entries, title, external_url("public.issues_feed"), external_url("public.issues"))


@bp.get("/sitemap.xml")
def sitemap():
    urls = [(external_url("public.home"), None), (external_url("public.issues"), None),
            (external_url("public.articles"), None)]
    if perms.has(current_user, "read"):
        for a in db.session.scalars(published_articles().where(Article.visibility == "public")).all():
            urls.append((external_url("public.article", slug=a.slug), a.updated_at))
        for i in db.session.scalars(published_issues()).all():
            urls.append((external_url("public.issue", number=i.number), i.sent_at or i.published_at))
        for p in db.session.scalars(select(Page).where(Page.is_published.is_(True))).all():
            urls.append((external_url("public.page", slug=p.slug), p.updated_at))
        for s in db.session.scalars(select(Section)).all():
            urls.append((external_url("public.section", slug=s.slug), None))
    xml = render_template("public/sitemap.xml", urls=urls)
    return Response(xml, mimetype="application/xml")


@bp.get("/robots.txt")
def robots():
    private = not perms.has(current_user, "read")
    lines = ["User-agent: *"]
    if private:
        lines.append("Disallow: /")
    else:
        for path in ("/dashboard/", "/account/", "/write/", "/subscription/", "/unsubscribe/", "/api/"):
            lines.append(f"Disallow: {state().config.url_prefix}{path}")
        lines.append(f"Sitemap: {external_url('public.sitemap')}")
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


@bp.get("/uploads/<path:path>")
def upload(path: str):
    response = send_from_directory(state().config.uploads_dir, path, max_age=31536000)
    response.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'"
    return response


@bp.get("/theme/<theme>/<path:filename>")
def theme_asset(theme: str, filename: str):
    for item in state().theme_chain() if theme == state().active_theme else [state().themes.get(theme)]:
        if item is not None and (item.static_dir / filename).is_file():
            return send_from_directory(item.static_dir, filename, max_age=86400)
    abort(404)


@bp.get("/custom.css")
def custom_css():
    css = settings.get("appearance.custom_css") or ""
    response = Response(css, mimetype="text/css")
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@bp.get("/favicon.svg")
def favicon():
    name = (settings.get("site.name") or "C").strip()
    letter = escape((name[4:5] if name.lower().startswith("the ") and len(name) > 4 else name[:1]).upper() or "C")
    color = accent_tokens(settings.get("appearance.accent_color"))["accent"]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" rx="14" fill="{color}"/>'
        '<text x="32" y="44" text-anchor="middle" font-family="Georgia, serif" font-size="38" '
        f'font-weight="700" fill="#ffffff">{letter}</text></svg>'
    )
    response = Response(svg, mimetype="image/svg+xml")
    response.headers["Cache-Control"] = "public, max-age=3600"
    response.set_etag(hashlib.sha1(svg.encode()).hexdigest())
    return response


@bp.get("/healthz")
def health():
    from copydesk.maintenance import active

    try:
        db.session.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001 - report, don't crash
        database = "unavailable"
    status = 200 if database == "ok" else 503
    identity = settings.get("system.instance_id") if database == "ok" else None
    return jsonify(instance_id=identity, status="ok" if status == 200 else "error", database=database, version=__version__,
                   maintenance=active(current_app.extensions["copydesk"].config)), status
