"""Reviewing submissions and managing articles."""

from __future__ import annotations

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from copydesk import audit, newsletter, notify, publication, workflow
from copydesk import permissions as perms
from copydesk.auth import current_user
from copydesk.db import db
from copydesk.helpers import get_or_404, paginate
from copydesk.models import Article, ArticleAuthor, Group, Issue, Section, User
from copydesk.utils import parse_int, slugify, truncate, utcnow
from copydesk.views.dashboard import bp

TABS = [
    ("review", "Needs review", ("submitted", "in_review")),
    ("waiting", "With writers", ("changes_requested",)),
    ("accepted", "Accepted", ("accepted",)),
    ("published", "Published", ("published",)),
    ("closed", "Declined and withdrawn", ("declined", "withdrawn")),
    ("all", "All", tuple(s for s in workflow.STATUSES if s != "draft")),
]


def _article(article_id: int) -> Article:
    article = get_or_404(Article, article_id)
    if article.status == "draft" and not article.has_author(current_user):
        abort(404)  # drafts are private to their writers
    return article


@bp.get("/articles/")
@perms.require("review")
def articles():
    tab = request.args.get("tab", "published" if publication.is_blog() else "review")
    statuses = {key: value for key, _, value in TABS}.get(tab) or TABS[0][2]
    q = (request.args.get("q") or "").strip()
    section_id = parse_int(request.args.get("section"))
    assigned = request.args.get("assigned")

    stmt = select(Article).where(Article.status.in_(statuses))
    if q:
        like = f"%{q.lower()}%"
        author_ids = select(ArticleAuthor.article_id).join(User, User.id == ArticleAuthor.user_id).where(
            func.lower(User.display_name).like(like)
        )
        stmt = stmt.where(or_(func.lower(Article.title).like(like), Article.id.in_(author_ids)))
    if section_id:
        stmt = stmt.where(Article.section_id == section_id)
    if assigned == "me":
        stmt = stmt.where(Article.assigned_editor_id == current_user.id)
    elif assigned == "nobody":
        stmt = stmt.where(Article.assigned_editor_id.is_(None))
    if tab == "review":
        stmt = stmt.order_by(Article.submitted_at.is_(None), Article.submitted_at.asc(), Article.id)
    elif tab == "published":
        stmt = stmt.order_by(Article.published_at.desc())
    else:
        stmt = stmt.order_by(Article.updated_at.desc())

    counts = dict(db.session.execute(select(Article.status, func.count()).group_by(Article.status)).all())
    tab_counts = {key: sum(counts.get(s, 0) for s in value) for key, _, value in TABS}
    return render_template(
        "dashboard/articles/list.html",
        page=paginate(stmt, per_page=25),
        tabs=TABS,
        tab=tab,
        tab_counts=tab_counts,
        q=q,
        section_id=section_id,
        assigned=assigned,
        sections=db.session.scalars(select(Section).order_by(Section.position)).all(),
        dash_active="articles",
    )


@bp.get("/articles/<int:article_id>/")
@perms.require("review")
def article(article_id: int):
    item = _article(article_id)
    editors = list(notify.users_with_permission("review"))
    open_issues = []
    if perms.has(current_user, "manage_issues") and item.status in ("accepted", "published"):
        open_issues = [
            issue for issue in db.session.scalars(
                select(Issue).where(Issue.status.in_(("draft", "scheduled"))).order_by(Issue.number)
            ).all()
            if all(entry.article_id != item.id for entry in issue.items)
        ]
    appears_in = newsletter.issues_containing([item.id]).get(item.id, [])
    return render_template(
        "dashboard/articles/review.html",
        article=item,
        transitions=workflow.editor_transitions(current_user, item),
        writer_transitions=workflow.writer_transitions(current_user, item),
        events=workflow.visible_events(item, current_user),
        editors=editors,
        open_issues=open_issues,
        appears_in=appears_in,
        audience_groups=db.session.scalars(
            select(Group).where(Group.is_audience.is_(True)).order_by(Group.position)
        ).all(),
        sections=db.session.scalars(select(Section).order_by(Section.position)).all(),
        revision_count=len(workflow.revisions(item)),
        can_edit=workflow.can_edit(current_user, item),
        status_info=workflow.STATUSES[item.status],
        dash_active="articles",
    )


@bp.post("/articles/<int:article_id>/transition")
@perms.require("review")
def article_transition(article_id: int):
    item = _article(article_id)
    action = request.form.get("action", "")
    try:
        new_status = workflow.transition(item, action, current_user, request.form.get("message", ""))
    except workflow.WorkflowError as exc:
        flash(str(exc), "error")
    else:
        db.session.commit()
        label = workflow.STATUSES[new_status].label
        flash(f"“{item.display_title}” is now {label.lower()}. The writer has been emailed.", "success")
    return redirect(url_for("dash.article", article_id=item.id))


@bp.post("/articles/<int:article_id>/comment")
@perms.require("review")
def article_comment(article_id: int):
    item = _article(article_id)
    internal = request.form.get("visibility") == "internal"
    try:
        workflow.comment(item, current_user, request.form.get("body", ""), internal=internal)
    except workflow.WorkflowError as exc:
        flash(str(exc), "error")
    else:
        db.session.commit()
        flash("Internal note added." if internal else "Comment sent to the writer.", "success")
    return redirect(url_for("dash.article", article_id=item.id) + "#conversation")


@bp.post("/articles/<int:article_id>/assign")
@perms.require("review")
def article_assign(article_id: int):
    item = _article(article_id)
    editor_id = parse_int(request.form.get("editor_id"))
    editor = db.session.get(User, editor_id) if editor_id else None
    if editor is not None and not perms.has(editor, "review"):
        flash("That person can't review articles.", "error")
    else:
        workflow.assign(item, editor, current_user)
        db.session.commit()
        flash(f"Assigned to {editor.display_name}." if editor else "Nobody is assigned now.", "success")
    return redirect(url_for("dash.article", article_id=item.id))


@bp.post("/articles/<int:article_id>/settings")
@perms.require("publish")
def article_settings(article_id: int):
    item = _article(article_id)
    form = request.form
    slug = slugify(form.get("slug") or item.title, 120, "")
    if not slug:
        flash("The web address can't be empty.", "error")
        return redirect(url_for("dash.article", article_id=item.id))
    if slug != item.slug and db.session.scalar(select(Article.id).where(Article.slug == slug, Article.id != item.id)):
        flash(f"Another article already uses the address “{slug}”.", "error")
        return redirect(url_for("dash.article", article_id=item.id))
    visibility = form.get("visibility", "public")
    if visibility not in ("public", "members", "groups"):
        visibility = "public"
    chosen_groups = []
    if visibility == "groups":
        wanted = {parse_int(v) for v in form.getlist("visibility_groups")}
        chosen_groups = db.session.scalars(select(Group).where(Group.id.in_(wanted), Group.is_audience.is_(True))).all()
        if not chosen_groups:
            flash("Pick at least one group, or choose a different visibility.", "error")
            return redirect(url_for("dash.article", article_id=item.id))
    old_slug = item.slug
    item.slug = slug
    item.visibility = visibility
    item.visibility_groups = list(chosen_groups)
    item.excerpt = truncate(form.get("excerpt", ""), 400, "")
    item.featured = bool(form.get("featured"))
    workflow.set_section(item, parse_int(form.get("section_id")))
    item.updated_at = utcnow()
    audit.record("article.settings", item, actor=current_user,
                 details={"visibility": visibility, "slug": [old_slug, slug] if old_slug != slug else slug})
    db.session.commit()
    flash("Publishing settings saved.", "success")
    return redirect(url_for("dash.article", article_id=item.id))


@bp.post("/articles/<int:article_id>/add-to-issue")
@perms.require("manage_issues")
def article_add_to_issue(article_id: int):
    item = _article(article_id)
    issue = db.session.get(Issue, parse_int(request.form.get("issue_id")))
    if issue is None or not issue.is_editable:
        flash("Pick an issue that hasn't been sent yet.", "error")
        return redirect(url_for("dash.article", article_id=item.id))
    if item.status not in ("accepted", "published"):
        flash("Only accepted or published articles can go in an issue.", "error")
        return redirect(url_for("dash.article", article_id=item.id))
    newsletter.add_article(issue, item)
    issue.updated_at = utcnow()
    db.session.commit()
    flash(f"Added to issue #{issue.number}.", "success")
    return redirect(url_for("dash.issue", issue_id=issue.id))


@bp.post("/articles/<int:article_id>/delete")
@perms.require("edit_any")
def article_delete(article_id: int):
    item = _article(article_id)
    if item.status in ("published", "accepted"):
        flash("Unpublish or decline this article before deleting it.", "error")
        return redirect(url_for("dash.article", article_id=item.id))
    title = item.display_title
    audit.record("article.deleted", item, actor=current_user)
    db.session.delete(item)
    db.session.commit()
    flash(f"“{title}” was deleted.", "success")
    return redirect(url_for("dash.articles"))
