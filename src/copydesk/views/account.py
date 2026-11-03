"""Account settings: profile, groups, newsletter, notifications, security, your data."""

from __future__ import annotations

import json

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import func, select

from copydesk import audit, groups, notify, subscribers
from copydesk import permissions as perms
from copydesk.auth import (
    check_password,
    current_user,
    hash_password,
    login_required,
    login_user,
    logout_user,
    password_problem,
    read_token,
    username_problem,
)
from copydesk.db import db
from copydesk.helpers import state
from copydesk.models import (
    Article,
    ArticleAuthor,
    ArticleEvent,
    Group,
    GroupMembership,
    Subscriber,
    User,
)
from copydesk.security import too_many
from copydesk.uploads import UploadError, save_image
from copydesk.utils import is_valid_email, normalize_email, parse_int, utcnow

bp = Blueprint("account", __name__, url_prefix="/account")

NAV = [
    ("profile", "Profile", "user"),
    ("groups", "Groups", "users"),
    ("newsletter", "Newsletter", "mail"),
    ("notifications", "Notifications", "message"),
    ("security", "Email and password", "lock"),
    ("privacy", "Your data", "shield"),
]


def render(template: str, active: str, **context):
    return render_template(template, account_nav=NAV, account_active=active, **context)


@bp.get("/")
@login_required
def index():
    return redirect(url_for("account.profile"))


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user
    errors: dict[str, str] = {}
    form = request.form
    if request.method == "POST":
        name = (form.get("display_name") or "").strip()
        username = (form.get("username") or "").strip().lower()
        bio = (form.get("bio") or "").strip()
        website = (form.get("website") or "").strip()
        if not name:
            errors["display_name"] = "Enter your name."
        elif len(name) > 100:
            errors["display_name"] = "Keep your name under 100 characters."
        problem = username_problem(username, exclude_user_id=user.id) if username != user.username else None
        if problem:
            errors["username"] = problem
        if len(bio) > 1000:
            errors["bio"] = f"Keep your bio under 1,000 characters (it's {len(bio):,})."
        if website and not website.startswith(("http://", "https://")):
            errors["website"] = "Enter a full address starting with https://"
        avatar = request.files.get("avatar")
        if not errors and avatar and avatar.filename:
            try:
                upload = save_image(avatar, user.id, kind="avatar")
                user.avatar = upload.path
            except UploadError as exc:
                errors["avatar"] = str(exc)
        if not errors:
            if form.get("remove_avatar"):
                user.avatar = ""
            user.display_name, user.username, user.bio, user.website = name, username, bio, website[:255]
            db.session.commit()
            flash("Your profile has been saved.", "success")
            return redirect(url_for("account.profile"))
    return render("account/profile.html", "profile", form=form, errors=errors), (422 if errors else 200)


@bp.route("/groups", methods=["GET", "POST"], endpoint="groups")
@login_required
def groups_page():
    user = current_user
    errors: dict[str, str] = {}
    if request.method == "POST":
        action = request.form.get("action")
        if action == "request":
            group = db.session.scalar(select(Group).where(Group.slug == request.form.get("group")))
            if group is None or not group.self_service:
                abort(400)
            data, errors = groups.parse_fields(group, request.form)
            if not errors:
                try:
                    note = request.form.get(f"note-{group.slug}", "").strip()
                    membership = groups.request(user, group, data=data, note=note)
                except groups.GroupError as exc:
                    flash(str(exc), "error")
                    return redirect(url_for("account.groups"))
                db.session.commit()
                if membership.status == "active":
                    flash(f"You're now in {group.name}.", "success")
                elif user.is_verified:
                    flash("Request sent. We'll email you when an editor has reviewed it.", "success")
                else:
                    flash("Request saved. It goes to the editors once you confirm your email address.", "success")
                return redirect(url_for("account.groups"))
        elif action in ("update", "leave"):
            membership = db.session.get(GroupMembership, parse_int(request.form.get("membership"), 0))
            if membership is None or membership.user_id != user.id:
                abort(404)
            if action == "update":
                data, errors = groups.parse_fields(membership.group, request.form)
                if not errors:
                    membership.data = data
                    db.session.commit()
                    flash(f"Your {membership.group.name} details have been saved.", "success")
                    return redirect(url_for("account.groups"))
            else:
                if membership.group.slug == "admins" and groups.last_admin(user):
                    flash("You're the only administrator, so you can't leave that group. Make someone else an administrator first.", "error")
                    return redirect(url_for("account.groups"))
                name = membership.group.name
                was_pending = membership.status == "pending"
                groups.remove(membership, user)
                db.session.commit()
                flash(f"Request to join {name} withdrawn." if was_pending else f"You've left {name}.", "success")
                return redirect(url_for("account.groups"))
    mine = list(user.memberships)
    member_of = {m.group_id for m in mine}
    available = [g for g in groups.joinable_groups() if g.id not in member_of]
    return render("account/groups.html", "groups", memberships=sorted(mine, key=lambda m: m.group.position),
                  available=available, errors=errors, groups_api=groups), (422 if errors else 200)


@bp.route("/newsletter", methods=["GET", "POST"])
@login_required
def newsletter():
    user = current_user
    subscriber = subscribers.for_user(user)
    audience = subscribers.signup_groups()
    if request.method == "POST":
        action = request.form.get("action")
        chosen = [g for g in audience if g.slug in request.form.getlist("groups")]
        if action == "subscribe":
            subscriber, outcome = subscribers.subscribe(
                user.email, name=user.display_name, groups=chosen, source="account", user=user,
                confirmed=user.is_verified, send_confirmation=False,
            )
            db.session.commit()
            if outcome == "pending":
                flash("You'll start getting the newsletter once you confirm your email address.", "success")
            else:
                flash("You're subscribed. The next issue will land in your inbox.", "success")
        elif action == "update" and subscriber is not None:
            subscriber.groups = chosen
            db.session.commit()
            flash("Your newsletter preferences have been saved.", "success")
        elif action == "unsubscribe" and subscriber is not None:
            subscribers.unsubscribe(subscriber)
            db.session.commit()
            flash("You've been unsubscribed. You won't get any more issues.", "success")
        return redirect(url_for("account.newsletter"))
    return render("account/newsletter.html", "newsletter", subscriber=subscriber, audience=audience)


NOTIFICATION_OPTIONS = [
    ("submission_updates", "Updates on my writing",
     "When an editor comments, asks for changes, accepts or publishes something you wrote.", None),
    ("new_submissions", "New submissions",
     "When a writer submits or resubmits a piece for review.", "review"),
    ("group_requests", "Requests to join groups",
     "When someone asks to join a group that needs approval.", "manage_users"),
]


@bp.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications():
    user = current_user
    options = [o for o in NOTIFICATION_OPTIONS if o[3] is None or perms.has(user, o[3])]
    if request.method == "POST":
        prefs = dict(user.notification_prefs or {})
        for key, *_ in options:
            prefs[key] = bool(request.form.get(key))
        user.notification_prefs = prefs
        db.session.commit()
        flash("Your notification settings have been saved.", "success")
        return redirect(url_for("account.notifications"))
    return render("account/notifications.html", "notifications", options=options)


@bp.route("/security", methods=["GET", "POST"])
@login_required
def security():
    user = current_user
    errors: dict[str, str] = {}
    if request.method == "POST":
        action = request.form.get("action")
        if too_many("account-security", 10, 900, key=str(user.id)):
            flash("Too many attempts. Please wait 15 minutes and try again.", "error")
            return redirect(url_for("account.security"))
        if action == "password":
            if not check_password(user, request.form.get("current") or ""):
                errors["current"] = "That isn't your current password."
            new = request.form.get("new") or ""
            problem = password_problem(new, user.email)
            if problem:
                errors["new"] = problem
            elif new != request.form.get("confirm"):
                errors["confirm"] = "The two new passwords don't match."
            if not errors:
                user.password_hash = hash_password(new)
                user.auth_version += 1
                audit.record("user.password_changed", user, actor=user)
                notify.password_changed(user)
                login_user(user)
                db.session.commit()
                flash("Your password has been changed. You've been signed out everywhere else.", "success")
                return redirect(url_for("account.security"))
        elif action == "email":
            new_email = normalize_email(request.form.get("email"))
            if not is_valid_email(new_email):
                errors["email"] = "Enter a valid email address."
            elif new_email == user.email:
                errors["email"] = "That's already your email address."
            elif db.session.scalar(select(User.id).where(func.lower(User.email) == new_email)):
                errors["email"] = "Another account already uses that address."
            if not check_password(user, request.form.get("email_password") or ""):
                errors["email_password"] = "That isn't your current password."
            if not errors:
                if not user.is_verified:
                    user.email = new_email
                    notify.verify_email(user)
                    db.session.commit()
                    flash(f"Your email address is now {new_email}. We've sent a confirmation link there.", "success")
                    return redirect(url_for("auth.verify_notice"))
                notify.change_email(user, new_email)
                db.session.commit()
                flash(f"We sent a link to {new_email}. Click it to finish changing your address.", "success")
                return redirect(url_for("account.security"))
        elif action == "signout_everywhere":
            user.auth_version += 1
            login_user(user)
            db.session.commit()
            flash("You've been signed out on every other device.", "success")
            return redirect(url_for("account.security"))
    return render("account/security.html", "security", errors=errors), (422 if errors else 200)


@bp.get("/confirm-email/<token>")
def confirm_email(token: str):
    data = read_token("change-email", token)
    user = db.session.get(User, data.get("uid")) if data else None
    new_email = normalize_email(data.get("email")) if data else ""
    if (user is None or user.is_deleted or not user.is_active or not new_email
            or user.email != data.get("old_email") or user.auth_version != data.get("uv")):
        return render_template("auth/link_problem.html", kind="email"), 400
    if db.session.scalar(select(User.id).where(func.lower(User.email) == new_email, User.id != user.id)):
        flash("Another account started using that address in the meantime, so we couldn't switch to it.", "error")
        return redirect(url_for("account.security"))
    old_email = user.email
    user.email = new_email
    user.email_verified_at = utcnow()
    user.auth_version += 1
    subscriber = db.session.scalar(select(Subscriber).where(Subscriber.user_id == user.id))
    target_subscriber = subscribers.find(new_email)
    if subscriber is not None:
        if target_subscriber is None:
            subscriber.email = new_email
            subscriber.token = subscribers.new_token()
        else:
            subscriber.user_id = None
            db.session.flush()
    if target_subscriber is not None:
        target_subscriber.user_id = user.id
    if current_user.is_authenticated and current_user.id == user.id:
        login_user(user)
    groups.after_verification(user)
    audit.record("user.updated", user, actor=user, details={"email": [old_email, new_email]})
    db.session.commit()
    flash(f"Your email address is now {new_email}.", "success")
    return redirect(url_for("account.security") if current_user.is_authenticated else url_for("auth.login"))


@bp.get("/privacy")
@login_required
def privacy():
    return render("account/privacy.html", "privacy", is_last_admin=groups.last_admin(current_user))


@bp.get("/export")
@login_required
def export():
    """Everything QuillSail stores about you, as JSON."""
    user = current_user
    subscriber = subscribers.for_user(user)
    article_ids = db.session.scalars(select(ArticleAuthor.article_id).where(ArticleAuthor.user_id == user.id)).all()
    articles = db.session.scalars(select(Article).where(Article.id.in_(article_ids))).all() if article_ids else []
    comments = db.session.scalars(
        select(ArticleEvent).where(ArticleEvent.user_id == user.id, ArticleEvent.kind == "comment")
    ).all()
    data = {
        "account": {
            "email": user.email,
            "username": user.username,
            "display_name": user.display_name,
            "bio": user.bio,
            "website": user.website,
            "created_at": user.created_at.isoformat(),
            "email_verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
            "notification_prefs": user.notification_prefs,
        },
        "groups": [
            {"group": m.group.name, "status": m.status, "details": m.data, "since": m.created_at.isoformat()}
            for m in user.memberships
        ],
        "newsletter": None if subscriber is None else {
            "email": subscriber.email,
            "status": subscriber.status,
            "groups": [g.name for g in subscriber.groups],
            "subscribed_at": subscriber.created_at.isoformat(),
        },
        "articles": [
            {"title": a.title, "subtitle": a.subtitle, "status": a.status, "body": a.body, "body_format": a.body_format,
             "source_url": a.source_url, "source_author": a.source_author,
             "newsletter_blurb": a.newsletter_blurb,
             "created_at": a.created_at.isoformat(),
             "published_at": a.published_at.isoformat() if a.published_at else None}
            for a in articles
        ],
        "comments": [
            {"article": c.article.title, "body": c.body, "created_at": c.created_at.isoformat()} for c in comments
        ],
    }
    from copydesk.models import CompetitionEntry, CompetitionScore, CompetitionVote
    data["competition_entries"] = [
        {"competition_id": row.competition_id, "title": row.title, "body": row.body, "project_url": row.project_url, "status": row.status, "moderation_note": row.moderation_note}
        for row in db.session.scalars(select(CompetitionEntry).where(CompetitionEntry.user_id == user.id))
    ]
    data["competition_votes"] = [{"competition_id": row.competition_id, "entry_id": row.entry_id} for row in db.session.scalars(select(CompetitionVote).where(CompetitionVote.user_id == user.id))]
    data["competition_scores"] = [{"entry_id": row.entry_id, "score": row.score, "notes": row.notes} for row in db.session.scalars(select(CompetitionScore).where(CompetitionScore.judge_id == user.id))]
    response = Response(json.dumps(data, indent=2, ensure_ascii=False), mimetype="application/json")
    response.headers["Content-Disposition"] = f'attachment; filename="{user.username}-data.json"'
    return response


@bp.route("/delete", methods=["GET", "POST"])
@login_required
def delete():
    user = current_user
    if groups.last_admin(user):
        flash("You're the only administrator. Make someone else an administrator before deleting your account.", "error")
        return redirect(url_for("account.privacy"))
    error = None
    if request.method == "POST":
        if not check_password(user, request.form.get("password") or ""):
            error = "That isn't your password."
        else:
            anonymize(user, actor=user)
            db.session.commit()
            logout_user()
            flash("Your account has been deleted. Thanks for being part of the community.", "success")
            return redirect(url_for("public.home"))
    return render("account/delete.html", "privacy", error=error)


def anonymize(user: User, actor) -> None:
    """Delete personal data but keep published writing (credited to "Former contributor")."""
    from copydesk.competitions import erase_user_data
    erase_user_data(user)
    links = db.session.scalars(select(ArticleAuthor).where(ArticleAuthor.user_id == user.id)).all()
    for link in links:
        article = db.session.get(Article, link.article_id)
        if article is not None and article.status != "published" and len(article.author_links) == 1:
            db.session.delete(article)
    subscriber = db.session.scalar(select(Subscriber).where(Subscriber.user_id == user.id))
    if subscriber is not None:
        db.session.delete(subscriber)
    for membership in list(user.memberships):
        db.session.delete(membership)
    user.email = f"deleted-{user.id}@deleted.invalid"
    user.username = f"deleted-{user.id}"
    user.display_name = "Former contributor"
    user.bio = user.website = user.avatar = user.password_hash = ""
    user.notification_prefs = {}
    user.is_active = False
    user.deleted_at = utcnow()
    user.auth_version += 1
    audit.record("user.deleted", user, actor=actor, label=f"#{user.id}")
    state().hooks.fire("user.deleted", user=user)
