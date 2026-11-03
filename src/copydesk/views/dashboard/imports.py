"""Importing a blog: upload a zip, check what would happen, then confirm."""

from __future__ import annotations

import shutil

from flask import abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from copydesk import audit, jekyll_import, jobs
from copydesk import permissions as perms
from copydesk.auth import current_user
from copydesk.db import db
from copydesk.helpers import state
from copydesk.models import Job
from copydesk.security import too_many
from copydesk.views.dashboard import bp


def _folder(token: str):
    folder = jekyll_import.import_folder(token)
    if folder is None:
        abort(404)
    return folder


def _running(token: str) -> bool:
    jobs_waiting = db.session.scalars(
        select(Job).where(Job.kind == "jekyll.import", Job.status.in_(("queued", "running")))
    ).all()
    return any((job.payload or {}).get("token") == token for job in jobs_waiting)


@bp.route("/import/jekyll", methods=["GET", "POST"])
@perms.require("import_content")
def import_jekyll():
    error = None
    if request.method == "POST":
        upload = request.files.get("site")
        if upload is None or not upload.filename:
            error = "Choose a zip file of your Jekyll site's source folder."
        elif too_many("jekyll-import", 20, 3600, key=str(current_user.id)):
            abort(429)
        else:
            token = None
            try:
                token = jekyll_import.save_upload(upload.stream)
                jekyll_import.plan_import(jekyll_import.import_folder(token) / "source")
            except jekyll_import.ImportError_ as exc:
                error = str(exc)
                folder = jekyll_import.import_folder(token) if token else None
                if folder:
                    shutil.rmtree(folder, ignore_errors=True)
            else:
                return redirect(url_for("dash.import_jekyll_review", token=token))
    return render_template(
        "dashboard/import/jekyll.html", error=error, max_mb=state().config.max_import_mb,
    ), (422 if error else 200)


@bp.get("/import/jekyll/<token>")
@perms.require("import_content")
def import_jekyll_review(token: str):
    folder = _folder(token)
    status = jekyll_import.read_status(folder)
    if status is not None:
        return render_template(
            "dashboard/import/status.html", token=token, status=status, running=_running(token),
        )
    try:
        plan = jekyll_import.plan_import(folder / "source")
    except jekyll_import.ImportError_ as exc:
        flash(str(exc), "error")
        return redirect(url_for("dash.import_jekyll"))
    return render_template("dashboard/import/review.html", token=token, plan=plan, counts=plan.counts())


@bp.post("/import/jekyll/<token>/start")
@perms.require("import_content")
def import_jekyll_start(token: str):
    folder = _folder(token)
    if jekyll_import.read_status(folder) is not None:
        return redirect(url_for("dash.import_jekyll_review", token=token))
    jekyll_import.write_status(folder, state="queued")
    jobs.enqueue(
        "jekyll.import",
        {"token": token, "actor_id": current_user.id, "as_drafts": bool(request.form.get("as_drafts"))},
        max_attempts=3,
    )
    audit.record("article.imported_site", None, actor=current_user, label="started a blog import")
    db.session.commit()
    flash("The import has started. It keeps running if you leave this page.", "success")
    return redirect(url_for("dash.import_jekyll_review", token=token))


@bp.post("/import/jekyll/<token>/cancel")
@perms.require("import_content")
def import_jekyll_cancel(token: str):
    folder = _folder(token)
    if jekyll_import.read_status(folder) is None:
        shutil.rmtree(folder, ignore_errors=True)
        flash("The upload was removed. Nothing was imported.", "info")
    return redirect(url_for("dash.import_jekyll"))
