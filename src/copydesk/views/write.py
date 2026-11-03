"""Writing for the publication: drafts, the editor, submitting, and following a piece."""

from __future__ import annotations

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import func, select, update

from copydesk import audit, body_formats, newsletter, publication, settings, uploads, workflow
from copydesk import permissions as perms
from copydesk.auth import current_user, login_required, verified_required
from copydesk.db import db
from copydesk.helpers import get_or_404, json_object
from copydesk.models import (
    Article,
    ArticleAuthor,
    ArticleRevision,
    Group,
    Issue,
    Page,
    Section,
    User,
)
from copydesk.security import too_many
from copydesk.text import BODY_FORMATS, diff, render_source, source_word_count
from copydesk.utils import parse_int, parse_lines
from copydesk.visual_document import markdown_to_document

bp = Blueprint("write", __name__, url_prefix="/write")

BUCKETS = [
    ("drafts", "Drafts", ("draft",)),
    ("in_progress", "With the editors", ("submitted", "in_review", "changes_requested")),
    ("accepted", "Accepted and published", ("accepted", "published")),
    ("closed", "Declined or withdrawn", ("declined", "withdrawn")),
]
MAX_BODY = 200_000


@bp.route("/<int:article_id>/newsletter", methods=["GET", "POST"])
@verified_required
def post_newsletter(article_id):
    article = get_or_404(Article, article_id)
    if not article.is_published or not (
        article.has_author(current_user) or perms.has(current_user, "manage_issues")
    ):
        abort(404)
    if not workflow.can_view(current_user, article):
        abort(403)
    if request.method == "POST":
        if not publication.has_newsletter() or not perms.has(current_user, "manage_issues"):
            abort(403)
        choice = request.form.get("issue_id", "")
        if choice == "new":
            issue = newsletter.create(current_user)
        else:
            issue_id = parse_int(choice, 0)
            locked = db.session.execute(
                update(Issue)
                .where(Issue.id == issue_id, Issue.status == "draft")
                .values(updated_at=Issue.updated_at)
            )
            if locked.rowcount != 1:
                flash(
                    "Choose a draft issue. Scheduled and sent issues cannot be changed here.",
                    "error",
                )
                db.session.rollback()
                return redirect(url_for("write.post_newsletter", article_id=article.id))
            issue = db.session.get(Issue, issue_id, populate_existing=True)
        entry = newsletter.add_article(issue, article)
        entry.display = "full" if request.form.get("display") == "full" else "summary"
        audit.record(
            "article.added_to_newsletter",
            article,
            actor=current_user,
            details={"issue_id": issue.id},
        )
        db.session.commit()
        flash("Post added to the draft newsletter. Review the issue before sending.", "success")
        return redirect(url_for("dash.issue", issue_id=issue.id) + "#items")
    issues = (
        db.session.scalars(
            select(Issue).where(Issue.status == "draft").order_by(Issue.number.desc())
        ).all()
        if perms.has(current_user, "manage_issues")
        else []
    )
    return render_template(
        "write/newsletter.html",
        article=article,
        issues=issues,
        external_target=publication.external_submission_url(article),
    )


@bp.route("/from-blog", methods=["GET", "POST"])
def from_blog():
    if request.method == "GET" and not (
        current_user.is_authenticated and current_user.is_verified
    ):
        return render_template("write/blog_signin.html")
    return _from_blog()


@verified_required
def _from_blog():
    if not (perms.has(current_user, "submit") or perms.has(current_user, "publish")):
        abort(403)
    if not settings.get("submissions.enabled") and not perms.has(current_user, "publish"):
        flash(settings.get("submissions.closed_message"), "warning")
        return redirect(url_for("write.index"))
    values = (
        dict(request.form)
        if request.method == "POST"
        else {
            "source_url": request.args.get("source", "")[:2048],
            "title": request.args.get("title", "")[:200],
            "body": request.args.get("excerpt", "")[:400],
            "source_author": request.args.get("author", current_user.display_name)[:200],
        }
    )
    errors = {}
    if request.method == "POST":
        if too_many("blog-submission", 30, 3600, key=str(current_user.id)):
            abort(429)
        source = str(values.get("source_url") or "").strip()
        title = str(values.get("title") or "").strip()
        body = str(values.get("body") or "").replace("\r\n", "\n")
        body_format = str(values.get("body_format") or "markdown")
        author = str(values.get("source_author") or "").strip()
        blurb = str(values.get("newsletter_blurb") or "").strip()
        if not publication.valid_web_url(source):
            errors["source_url"] = (
                "Enter the public http:// or https:// URL of the original post without credentials."
            )
        if not 1 <= len(title) <= 200:
            errors["title"] = "Use a title between 1 and 200 characters."
        if not 1 <= len(author) <= 200:
            errors["source_author"] = "Add an author credit of up to 200 characters."
        if body_format not in BODY_FORMATS:
            body_format = "markdown"
        if source_word_count(body, body_format) < 20 or len(body) > MAX_BODY:
            errors["body"] = "Share at least 20 words, up to 200,000 characters."
        if len(blurb) > publication.MAX_NEWSLETTER_BLURB:
            errors["newsletter_blurb"] = "Keep the newsletter blurb under 5,000 characters."
        if values.get("permission") not in {"1", "on", "true"}:
            errors["permission"] = (
                "Confirm that the original is public and you have permission to submit it."
            )
        if not errors:
            # Serialize submissions by this account so a double-click cannot create duplicates.
            db.session.execute(
                update(User)
                .where(User.id == current_user.id)
                .values(last_seen_at=User.last_seen_at)
            )
            existing = db.session.scalar(
                select(Article)
                .join(ArticleAuthor)
                .where(
                    ArticleAuthor.user_id == current_user.id,
                    Article.source_url == source,
                    Article.status.not_in(("declined", "withdrawn")),
                )
                .limit(1)
            )
            if existing:
                db.session.rollback()
                flash(
                    "You already offered this post. Follow its existing submission below.", "info"
                )
                return redirect(url_for("write.status", article_id=existing.id))
            article = workflow.create_draft(current_user, title)
            workflow.save(
                article, current_user, title=title, subtitle="", body=body, body_format=body_format
            )
            article.source_url, article.source_author = source, author
            article.newsletter_blurb = blurb
            workflow.set_section(article, parse_int(values.get("section_id")))
            try:
                workflow.transition(article, "submit", current_user)
            except workflow.WorkflowError as exc:
                db.session.rollback()
                errors["section_id"] = str(exc)
            else:
                audit.record("article.blog_submitted", article, actor=current_user)
                db.session.commit()
                flash(
                    "Blog post offered to the editors. The original credit and link are included.",
                    "success",
                )
                return redirect(url_for("write.status", article_id=article.id))
    return render_template(
        "write/from_blog.html",
        values=values,
        errors=errors,
        sections=[section for section in _sections() if section.accepts_submissions],
    ), 422 if errors else 200


def guidelines_page() -> Page | None:
    slug = settings.get("submissions.guidelines_page")
    if not slug:
        return None
    return db.session.scalar(select(Page).where(Page.slug == slug, Page.is_published.is_(True)))


def _writer_article(article_id: int) -> Article:
    article = get_or_404(Article, article_id)
    if not workflow.can_see_submission(current_user, article):
        abort(404)
    return article


@bp.get("/")
def index():
    mine: dict[str, list[Article]] = {key: [] for key, _, _ in BUCKETS}
    if current_user.is_authenticated:
        rows = db.session.scalars(
            select(Article)
            .join(ArticleAuthor, ArticleAuthor.article_id == Article.id)
            .where(ArticleAuthor.user_id == current_user.id)
            .order_by(Article.updated_at.desc())
        ).all()
        for article in rows:
            for key, _, statuses in BUCKETS:
                if article.status in statuses:
                    mine[key].append(article)
    submit_groups = [
        g
        for g in db.session.scalars(select(Group).order_by(Group.position)).all()
        if "submit" in (g.permissions or []) and not g.is_implicit
    ]
    return render_template(
        "write/index.html",
        submit_groups=submit_groups,
        buckets=BUCKETS,
        mine=mine,
        has_any=any(mine.values()),
        can_submit=perms.has(current_user, "submit")
        or (publication.is_blog() and perms.has(current_user, "publish")),
        submissions_open=settings.get("submissions.enabled"),
        guidelines=guidelines_page(),
        active_nav="write",
    )


@bp.post("/new")
@verified_required
def new():
    if not settings.get("submissions.enabled") and not perms.has(current_user, "publish"):
        flash(settings.get("submissions.closed_message"), "warning")
        return redirect(url_for("write.index"))
    if not perms.has(current_user, "submit") and not perms.has(current_user, "publish"):
        abort(403)
    if too_many("new-draft", 30, 3600, key=str(current_user.id)):
        flash(
            "You've started a lot of drafts in the last hour. Please finish one first.", "warning"
        )
        return redirect(url_for("write.index"))
    article = workflow.create_draft(current_user)
    db.session.commit()
    return redirect(url_for("write.edit", article_id=article.id))


def _sections() -> list[Section]:
    return list(db.session.scalars(select(Section).order_by(Section.position, Section.name)).all())


def _find_coauthors(names: list[str]) -> tuple[list[User], list[str]]:
    found, missing = [], []
    for name in names[:5]:
        name = name.strip().lstrip("@").lower()
        user = db.session.scalar(
            select(User).where(
                (func.lower(User.username) == name) | (func.lower(User.email) == name),
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
        )
        if user is None or not user.is_verified:
            missing.append(name)
        elif user not in found:
            found.append(user)
    return found, missing


@bp.route("/<int:article_id>/edit", methods=["GET", "POST"])
@verified_required
def edit(article_id: int):
    article = get_or_404(Article, article_id)
    if not workflow.can_edit(current_user, article):
        if workflow.can_see_submission(current_user, article):
            flash("This piece is with the editors, so it can't be edited right now.", "warning")
            return redirect(url_for("write.status", article_id=article.id))
        abort(404)

    errors: dict[str, str] = {}
    preview_html = None
    form = request.form
    is_editor = not article.has_author(current_user)
    if request.method == "POST":
        action = form.get("action", "save")
        if action == "publish" and not (
            publication.is_blog()
            and article.has_author(current_user)
            and perms.has(current_user, "publish")
        ):
            abort(403)
        title = (form.get("title") or "").strip()
        subtitle = (form.get("subtitle") or "").strip()
        body = (form.get("body") or "").replace("\r\n", "\n")
        body_format = form.get("body_format") or article.body_format
        section_id = parse_int(form.get("section_id"))
        submitting = action in ("submit", "resubmit")
        if len(title) > 200:
            errors["title"] = "Keep the title under 200 characters."
        if len(subtitle) > 300:
            errors["subtitle"] = "Keep the subtitle under 300 characters."
        if len(body) > MAX_BODY:
            errors["body"] = "This piece is too long to save. Split it into parts."
        if body_format not in BODY_FORMATS:
            errors["body_format"] = "Choose Markdown or HTML."
        if article.source_url and not is_editor and len(form.get("newsletter_blurb", "")) > publication.MAX_NEWSLETTER_BLURB:
            errors["newsletter_blurb"] = "Keep the newsletter blurb under 5,000 characters."
        if submitting and settings.get("submissions.require_section") and not section_id:
            errors["section_id"] = "Choose a section before you submit."
        coauthors, missing = _find_coauthors(parse_lines(form.get("coauthors")))
        if missing:
            errors["coauthors"] = f"We couldn't find a confirmed account for: {', '.join(missing)}."
        cover = request.files.get("cover")
        cover_alt = (form.get("cover_alt") or "").strip()[:300]
        has_cover = bool(
            (cover and cover.filename) or (article.cover_image and not form.get("remove_cover"))
        )
        if has_cover and not cover_alt:
            errors["cover_alt"] = "Describe the cover image for people who can't see it."
        if not errors and cover and cover.filename:
            try:
                upload = uploads.save_image(cover, current_user.id)
                article.cover_image = upload.path
            except uploads.UploadError as exc:
                errors["cover"] = str(exc)

        if action == "preview" and not errors:
            preview_html = render_source(body, body_format)
        elif not errors:
            workflow.save(
                article,
                current_user,
                title=title,
                subtitle=subtitle,
                body=body,
                summary=form.get("summary", ""),
                body_format=body_format,
            )
            workflow.set_section(article, section_id)
            workflow.set_tags(article, parse_lines(form.get("tags")))
            if not is_editor:
                workflow.set_coauthors(article, coauthors)
            article.author_note = (form.get("author_note") or "").strip()[:2000]
            if article.source_url and not is_editor and "newsletter_blurb" in form:
                article.newsletter_blurb = form["newsletter_blurb"].strip()
            if form.get("remove_cover") and not (cover and cover.filename):
                article.cover_image = ""
            article.cover_alt = cover_alt
            if submitting:
                try:
                    workflow.transition(article, action, current_user, form.get("message", ""))
                except workflow.WorkflowError as exc:
                    db.session.commit()
                    flash(
                        f"Your changes were saved, but the piece wasn't submitted: {exc}", "error"
                    )
                    return redirect(url_for("write.edit", article_id=article.id))
            if action == "publish":
                try:
                    workflow.transition(article, "publish", current_user)
                except workflow.WorkflowError as exc:
                    db.session.commit()
                    flash(f"Your draft was saved: {exc}", "error")
                    return redirect(url_for("write.edit", article_id=article.id))
            db.session.commit()
            if action == "publish":
                flash("Post published. You can add it to a newsletter separately.", "success")
                return redirect(url_for("public.article", slug=article.slug))
            if submitting:
                flash(
                    "Submitted! The editors have it now. We'll email you when there's news.",
                    "success",
                )
                return redirect(url_for("write.status", article_id=article.id))
            flash("Saved.", "success")
            if is_editor:
                return redirect(url_for("dash.article", article_id=article.id))
            return redirect(url_for("write.edit", article_id=article.id))

    values = {
        "title": form.get("title", article.title),
        "subtitle": form.get("subtitle", article.subtitle),
        "body": form.get("body", article.body),
        "body_format": form.get("body_format", article.body_format),
        "section_id": form.get("section_id", article.section_id or ""),
        "tags": form.get("tags", ", ".join(t.name for t in article.tags)),
        "coauthors": form.get("coauthors", ", ".join(u.username for u in article.authors[1:])),
        "author_note": form.get("author_note", article.author_note),
        "cover_alt": form.get("cover_alt", article.cover_alt),
    }
    return render_template(
        "write/edit.html",
        article=article,
        values=values,
        errors=errors,
        sections=[s for s in _sections() if s.accepts_submissions or s.id == article.section_id],
        preview_html=preview_html,
        guidelines=guidelines_page(),
        max_words=settings.get("submissions.max_words") or 0,
        is_editor=is_editor,
        body_formats=BODY_FORMATS,
        # Markdown with HTML comes from imports, so it's offered only to pieces already using it.
        body_format_choices=[
            (key, label) for key, label in BODY_FORMATS.items()
            if key != "markdown_html" or values["body_format"] == key
        ],
        can_publish_post=publication.is_blog()
        and article.has_author(current_user)
        and perms.has(current_user, "publish")
        and any(
            move.action == "publish" for move in workflow.allowed_transitions(current_user, article)
        ),
        transitions=workflow.writer_transitions(current_user, article),
        active_nav="write",
    ), (422 if errors else 200)


@bp.get("/<int:article_id>/")
@login_required
def status(article_id: int):
    article = _writer_article(article_id)
    return render_template(
        "write/status.html",
        article=article,
        events=workflow.visible_events(article, current_user),
        transitions=workflow.writer_transitions(current_user, article),
        can_edit=workflow.can_edit(current_user, article),
        status_info=workflow.STATUSES[article.status],
        active_nav="write",
    )


@bp.post("/<int:article_id>/action")
@verified_required
def action(article_id: int):
    article = _writer_article(article_id)
    name = request.form.get("action", "")
    try:
        new_status = workflow.transition(
            article, name, current_user, request.form.get("message", "")
        )
    except workflow.WorkflowError as exc:
        flash(str(exc), "error")
    else:
        db.session.commit()
        messages = {
            "submitted": "Submitted! The editors have it now.",
            "withdrawn": "You withdrew this piece. Editors won't work on it unless you move it back to drafts.",
            "draft": "Moved back to your drafts.",
        }
        flash(messages.get(new_status, "Done."), "success")
        if new_status == "draft":
            return redirect(url_for("write.edit", article_id=article.id))
    return redirect(url_for("write.status", article_id=article.id))


@bp.post("/<int:article_id>/comment")
@verified_required
def comment(article_id: int):
    article = _writer_article(article_id)
    try:
        workflow.comment(article, current_user, request.form.get("body", ""))
        db.session.commit()
        flash("Your reply was sent to the editors.", "success")
    except workflow.WorkflowError as exc:
        flash(str(exc), "error")
    return redirect(url_for("write.status", article_id=article.id) + "#conversation")


@bp.post("/<int:article_id>/delete")
@verified_required
def delete(article_id: int):
    article = _writer_article(article_id)
    if (
        article.status != "draft"
        or article.submitted_at is not None
        or not article.has_author(current_user)
    ):
        flash(
            "Only drafts that were never submitted can be deleted. You can withdraw this piece instead.",
            "error",
        )
        return redirect(url_for("write.status", article_id=article.id))
    title = article.display_title
    db.session.delete(article)
    db.session.commit()
    flash(f"“{title}” was deleted.", "success")
    return redirect(url_for("write.index"))


@bp.get("/<int:article_id>/history")
@login_required
def history(article_id: int):
    article = _writer_article(article_id)
    return render_template(
        "write/history.html",
        article=article,
        revisions=workflow.revisions(article),
        can_edit=workflow.can_edit(current_user, article),
    )


@bp.get("/<int:article_id>/history/<int:revision_id>")
@login_required
def revision(article_id: int, revision_id: int):
    article = _writer_article(article_id)
    revs = workflow.revisions(article)
    current = next((r for r in revs if r.id == revision_id), None)
    if current is None:
        abort(404)
    against_id = parse_int(request.args.get("against"))
    index = revs.index(current)
    previous = (
        next((r for r in revs if r.id == against_id), None)
        if against_id
        else (revs[index + 1] if index + 1 < len(revs) else None)
    )
    old = previous or ArticleRevision(title="", subtitle="", body="")
    return render_template(
        "write/revision.html",
        article=article,
        revision=current,
        previous=previous,
        title_diff=diff(old.title, current.title),
        subtitle_diff=diff(old.subtitle, current.subtitle),
        body_diff=diff(old.body, current.body),
        body_formats=BODY_FORMATS,
        can_edit=workflow.can_edit(current_user, article),
        is_latest=index == 0,
    )


@bp.post("/<int:article_id>/history/<int:revision_id>/restore")
@verified_required
def restore(article_id: int, revision_id: int):
    article = get_or_404(Article, article_id)
    revision_row = db.session.get(ArticleRevision, revision_id)
    if revision_row is None or revision_row.article_id != article.id:
        abort(404)
    if not workflow.can_edit(current_user, article):
        abort(403)
    workflow.save(
        article,
        current_user,
        title=revision_row.title,
        subtitle=revision_row.subtitle,
        body=revision_row.body,
        body_format=revision_row.body_format,
        summary=f"Restored the version from {revision_row.created_at:%Y-%m-%d %H:%M} UTC",
    )
    db.session.commit()
    flash(
        "That version has been restored. The version you replaced is still in the history.",
        "success",
    )
    return redirect(url_for("write.history", article_id=article.id))


@bp.post("/preview")
@verified_required
def preview():
    data = json_object()
    if not isinstance(data.get("body", ""), str):
        abort(400, description="The article body must be text.")
    body = data.get("body", "")[:MAX_BODY]
    body_format = data.get("body_format", "markdown")
    if body_format not in BODY_FORMATS:
        abort(400, description="Choose Markdown or HTML.")
    return jsonify(
        html=str(render_source(body, body_format)), words=source_word_count(body, body_format)
    )


def _posted_body(data: dict) -> str:
    """The text to work on. A piece over the limit is refused, never cut short."""
    body = data.get("body", "")
    if not isinstance(body, str):
        abort(400, description="The article body must be text.")
    if len(body) > MAX_BODY:
        abort(413, description="This piece is too long to work with here. Split it into parts.")
    return body


@bp.post("/visual")
@verified_required
def visual():
    """Read Markdown for the visual editor, with the same parser that renders it."""
    return jsonify(markdown_to_document(_posted_body(json_object())))


@bp.post("/convert")
@verified_required
def convert():
    """Rewrite a body in another format. Nothing is saved until the writer saves."""
    data = json_object()
    source, target = data.get("source"), data.get("target")
    if source not in BODY_FORMATS or target not in BODY_FORMATS:
        abort(400, description="Choose Markdown or HTML.")
    result = body_formats.convert(_posted_body(data), source, target)
    return jsonify(body=result.body, warnings=result.warnings)


@bp.get("/<int:article_id>/download")
@login_required
def download(article_id: int):
    """The saved body as a file: .md for Markdown, .html for HTML."""
    article = get_or_404(Article, article_id)
    if not (workflow.can_see_submission(current_user, article) or workflow.can_edit(current_user, article)):
        abort(404)
    is_html = article.body_format == "html"
    response = Response(
        article.body,
        mimetype="text/html" if is_html else "text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{article.slug}.{"html" if is_html else "md"}"'},
    )
    # The file is the writer's own source, so it must never run on this site if it's opened here.
    response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


@bp.post("/upload")
@verified_required
def upload():
    if not (perms.has(current_user, "submit") or perms.has(current_user, "edit_any")):
        return jsonify(message="You don't have permission to upload images."), 403
    if too_many("upload", 60, 3600, key=str(current_user.id)):
        return jsonify(
            message="You've uploaded a lot of images recently. Please wait a while."
        ), 429
    try:
        item = uploads.save_image(request.files.get("image"), current_user.id)
    except uploads.UploadError as exc:
        return jsonify(message=str(exc)), 400
    db.session.commit()
    url = uploads.url(item.path)
    return jsonify(url=url, markdown=f"![]({url})", width=item.width, height=item.height)
