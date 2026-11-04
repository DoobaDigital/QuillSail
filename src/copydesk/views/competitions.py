"""Public competition pages, entries, reader ballots and assigned judging."""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from sqlalchemy import select

from copydesk import audit, publication
from copydesk import competitions as contest
from copydesk.auth import current_user, verified_required
from copydesk.db import db
from copydesk.helpers import get_or_404, paginate
from copydesk.models import Competition, CompetitionEntry, CompetitionScore, CompetitionVote
from copydesk.security import too_many
from copydesk.utils import parse_int, utcnow
from copydesk.views.public import require_read

bp = Blueprint("competitions", __name__, url_prefix="/competitions")


@bp.before_request
def _enabled():
    if not publication.has_competitions():
        abort(404)


@bp.context_processor
def context():
    return {
        "competition_phase": contest.phase,
        "competition_phases": contest.PHASES,
        "competition_modes": contest.MODES,
        "active_nav": "competitions",
    }


@bp.errorhandler(contest.CompetitionProblem)
def problem(error):
    db.session.rollback()
    return render_template(
        "errors/error.html",
        code=422,
        title="That competition action is unavailable",
        message=str(error),
    ), 422


def visible(competition_id):
    require_read()
    item = get_or_404(Competition, competition_id)
    if item.status == "draft" and not contest.can_manage(current_user):
        abort(404)
    return item


@bp.get("/")
def index():
    require_read()
    page = paginate(
        select(Competition)
        .where(Competition.status != "draft")
        .order_by(Competition.created_at.desc(), Competition.id.desc()),
        per_page=12,
    )
    return render_template("competitions/index.html", page=page)


@bp.get("/<int:competition_id>/")
def detail(competition_id):
    item = visible(competition_id)
    current_phase = contest.phase(item)
    entries = (
        db.session.scalars(
            select(CompetitionEntry)
            .where(
                CompetitionEntry.competition_id == item.id, CompetitionEntry.status == "approved"
            )
            .order_by(CompetitionEntry.created_at, CompetitionEntry.id)
        ).all()
        if current_phase in {"judging", "closed", "results"}
        else []
    )
    own = (
        db.session.scalar(
            select(CompetitionEntry).where(
                CompetitionEntry.competition_id == item.id,
                CompetitionEntry.user_id == current_user.id,
            )
        )
        if current_user.is_authenticated
        else None
    )
    vote = (
        db.session.scalar(
            select(CompetitionVote).where(
                CompetitionVote.competition_id == item.id,
                CompetitionVote.user_id == current_user.id,
            )
        )
        if current_user.is_authenticated
        else None
    )
    return render_template(
        "competitions/detail.html",
        competition=item,
        phase=current_phase,
        entries=entries,
        entry_map={entry.id: entry for entry in entries},
        own_entry=own,
        vote=vote,
        is_judge=contest.is_judge(current_user, item),
        managing=contest.can_manage(current_user),
    )


@bp.route("/<int:competition_id>/enter", methods=["GET", "POST"])
@verified_required
def enter(competition_id):
    item = visible(competition_id)
    if request.method == "POST":
        if too_many("competition-entry", 30, 3600, key=str(current_user.id)):
            abort(429)
        item = contest.lock(item.id)
    entry = db.session.scalar(
        select(CompetitionEntry).where(
            CompetitionEntry.competition_id == item.id, CompetitionEntry.user_id == current_user.id
        )
    )
    if contest.phase(item) != "submissions":
        if request.method == "GET" and entry:
            return redirect(
                url_for("competitions.entry", competition_id=item.id, entry_id=entry.id)
            )
        raise contest.CompetitionProblem(
            "Entries can only be submitted or edited while submissions are open."
        )
    errors = {}
    if request.method == "POST":
        values, errors = contest.validate_entry(request.form)
        if not errors:
            if entry is None:
                entry = CompetitionEntry(competition_id=item.id, user_id=current_user.id)
                db.session.add(entry)
            for key, value in values.items():
                setattr(entry, key, value)
            entry.status, entry.moderation_note, entry.updated_at = "pending", "", utcnow()
            db.session.flush()
            audit.record("competition.entry_submitted", entry, actor=current_user)
            db.session.commit()
            flash("Entry submitted for approval. Changes require a new approval.", "success")
            return redirect(
                url_for("competitions.entry", competition_id=item.id, entry_id=entry.id)
            )
        db.session.rollback()
    return render_template(
        "competitions/enter.html",
        competition=item,
        entry=entry,
        errors=errors,
        values=request.form if request.method == "POST" else {},
    ), 422 if errors else 200


@bp.get("/<int:competition_id>/entries/<int:entry_id>/")
def entry(competition_id, entry_id):
    item = visible(competition_id)
    entry = get_or_404(CompetitionEntry, entry_id)
    if entry.competition_id != item.id or not contest.entry_visible(current_user, item, entry):
        abort(404)
    judge = contest.is_judge(current_user, item)
    score = (
        db.session.scalar(
            select(CompetitionScore).where(
                CompetitionScore.entry_id == entry.id, CompetitionScore.judge_id == current_user.id
            )
        )
        if judge
        else None
    )
    vote = (
        db.session.scalar(
            select(CompetitionVote).where(
                CompetitionVote.competition_id == item.id,
                CompetitionVote.user_id == current_user.id,
            )
        )
        if current_user.is_authenticated
        else None
    )
    return render_template(
        "competitions/entry.html",
        competition=item,
        entry=entry,
        phase=contest.phase(item),
        is_judge=judge,
        score=score,
        vote=vote,
        managing=contest.can_manage(current_user),
    )


@bp.post("/<int:competition_id>/entries/<int:entry_id>/withdraw")
@verified_required
def withdraw(competition_id, entry_id):
    item = visible(competition_id)
    item = contest.lock(item.id)
    entry = get_or_404(CompetitionEntry, entry_id)
    if entry.competition_id != item.id or entry.user_id != current_user.id:
        abort(404)
    if contest.phase(item) != "submissions":
        raise contest.CompetitionProblem("Entries are frozen once submissions close.")
    entry.status, entry.updated_at = "withdrawn", utcnow()
    audit.record("competition.entry_withdrawn", entry, actor=current_user)
    db.session.commit()
    flash("Your entry was withdrawn.", "success")
    return redirect(url_for("competitions.detail", competition_id=item.id))


@bp.post("/<int:competition_id>/vote")
@verified_required
def vote(competition_id):
    item = visible(competition_id)
    if too_many("competition-vote", 60, 60, key=str(current_user.id)):
        abort(429)
    item = contest.lock(item.id)
    if item.mode not in {"readers", "both"} or contest.phase(item) != "judging":
        raise contest.CompetitionProblem("Reader voting is not open for this competition.")
    ballot = db.session.scalar(
        select(CompetitionVote).where(
            CompetitionVote.competition_id == item.id, CompetitionVote.user_id == current_user.id
        )
    )
    if request.form.get("action") == "remove":
        if ballot:
            db.session.delete(ballot)
    else:
        entry = get_or_404(CompetitionEntry, parse_int(request.form.get("entry_id"), 0))
        if entry.competition_id != item.id or entry.status != "approved":
            abort(404)
        if entry.user_id == current_user.id:
            raise contest.CompetitionProblem("You cannot vote for your own entry.")
        if ballot is None:
            ballot = CompetitionVote(competition_id=item.id, user_id=current_user.id)
            db.session.add(ballot)
        ballot.entry_id, ballot.updated_at = entry.id, utcnow()
    db.session.commit()
    flash("Your vote was updated.", "success")
    return redirect(url_for("competitions.detail", competition_id=item.id))


@bp.post("/<int:competition_id>/entries/<int:entry_id>/score")
@verified_required
def score(competition_id, entry_id):
    item = visible(competition_id)
    if not contest.is_judge(current_user, item):
        abort(403)
    item = contest.lock(item.id)
    if item.mode not in {"judges", "both"} or contest.phase(item) != "judging":
        raise contest.CompetitionProblem("Judging is not open for this competition.")
    entry = get_or_404(CompetitionEntry, entry_id)
    if entry.competition_id != item.id or entry.status != "approved":
        abort(404)
    if entry.user_id == current_user.id:
        raise contest.CompetitionProblem("You cannot judge your own entry.")
    value = parse_int(request.form.get("score"))
    notes = str(request.form.get("notes") or "").strip()
    if value is None or not 0 <= value <= 100 or len(notes) > 10000:
        raise contest.CompetitionProblem(
            "Use a whole-number score from 0 to 100 and notes of up to 10,000 characters."
        )
    score = db.session.scalar(
        select(CompetitionScore).where(
            CompetitionScore.entry_id == entry.id, CompetitionScore.judge_id == current_user.id
        )
    )
    if score is None:
        score = CompetitionScore(entry_id=entry.id, judge_id=current_user.id)
        db.session.add(score)
    score.score, score.notes, score.updated_at = value, notes, utcnow()
    audit.record("competition.scored", entry, actor=current_user)
    db.session.commit()
    flash("Your score was saved. Judge notes stay private.", "success")
    return redirect(url_for("competitions.entry", competition_id=item.id, entry_id=entry.id))
