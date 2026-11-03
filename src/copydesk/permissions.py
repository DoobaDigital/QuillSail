"""Permissions, and working out which ones a person has.

As in MediaWiki, permissions belong to groups and people collect them by being
in groups. Everyone gets the permissions of the implicit "Everyone" group.
People with a confirmed account also get the "Members" permissions. Being in
"Administrators" grants every permission, so a site can never lock itself out.

Extensions can add permissions with ``register()``. They appear in the
dashboard's permission editor straight away.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from functools import wraps
from typing import Any

from flask import abort, g, redirect, request, url_for
from sqlalchemy import select

from copydesk.db import db
from copydesk.models import ADMINS, EVERYONE, MEMBERS, Group


@dataclass(frozen=True)
class Permission:
    key: str
    label: str
    description: str
    area: str


_REGISTRY: OrderedDict[str, Permission] = OrderedDict()


def register(key: str, label: str, description: str, area: str = "Extensions") -> Permission:
    perm = Permission(key, label, description, area)
    _REGISTRY[key] = perm
    return perm


register("read", "Read the publication", "See published articles, issues and pages that are open to everyone.", "Reading")
register("read_members", "Read members-only articles", "See articles that editors have limited to signed-in members.", "Reading")
register("submit", "Write and submit", "Write drafts and send them to the editors for review.", "Writing")
register("review", "Review submissions", "See the submission queue, leave feedback, request changes, accept or decline.", "Editing")
register("edit_any", "Edit any article", "Change the text of any article, not only their own.", "Editing")
register("publish", "Publish articles", "Publish articles on the website, or take them down again.", "Editing")
register("manage_issues", "Put issues together", "Create newsletter issues and choose what goes in them.", "Newsletter")
register("send_issues", "Send issues", "Send issues to subscribers, or schedule them to go out later.", "Newsletter")
register("manage_subscribers", "Manage subscribers", "See, add, import, export and remove newsletter subscribers.", "Newsletter")
register("manage_users", "Manage members", "Edit accounts, approve requests to join groups, and block people.", "People")
register("manage_groups", "Manage groups and permissions", "Create groups and decide what each one is allowed to do.", "People")
register("manage_pages", "Manage pages and sections", "Edit pages such as About, and the list of sections.", "Site")
register("manage_competitions", "Host competitions", "Create competitions, moderate entries, appoint judges and publish results.", "Competitions")
register("manage_business", "Manage business outreach", "Read private business inquiries, record follow-up, and approve opportunities for editorial use.", "People")
register("manage_settings", "Change site settings", "Change the publication's name, look, email and sign-up settings.", "Site")
register("import_content", "Import a blog", "Import posts, images and old addresses from another blog. Imported posts go live without review.", "Site")
register("view_log", "See the activity log", "See who did what on the site, and when.", "Site")


def get(key: str) -> Permission | None:
    return _REGISTRY.get(key)


def all_permissions() -> list[Permission]:
    return list(_REGISTRY.values())


def all_keys() -> frozenset[str]:
    return frozenset(_REGISTRY)


def by_area() -> OrderedDict[str, list[Permission]]:
    areas: OrderedDict[str, list[Permission]] = OrderedDict()
    for perm in _REGISTRY.values():
        areas.setdefault(perm.area, []).append(perm)
    return areas


def _implicit_groups() -> dict[str, Group]:
    cache = g.get("_implicit_groups")
    if cache is None:
        rows = db.session.scalars(select(Group).where(Group.slug.in_((EVERYONE, MEMBERS)))).all()
        cache = {grp.slug: grp for grp in rows}
        g._implicit_groups = cache
    return cache


def groups_for(user: Any) -> list[Group]:
    """Every group whose permissions apply to ``user``, implicit ones included."""
    implicit = _implicit_groups()
    groups = [implicit[EVERYONE]] if EVERYONE in implicit else []
    if getattr(user, "is_authenticated", False) and user.is_active and user.is_verified:
        if MEMBERS in implicit:
            groups.append(implicit[MEMBERS])
        groups.extend(user.groups)
    return groups


def permissions_for(user: Any) -> frozenset[str]:
    cache: dict = g.setdefault("_permission_cache", {})
    key = getattr(user, "id", None)
    if key in cache:
        return cache[key]
    granted: set[str] = set()
    for group in groups_for(user):
        if group.slug == ADMINS:
            granted = set(all_keys())
            break
        granted.update(group.permissions or [])
    result = frozenset(granted)
    cache[key] = result
    return result


def has(user: Any, permission: str) -> bool:
    return permission in permissions_for(user)


def is_admin(user: Any) -> bool:
    return bool(getattr(user, "is_authenticated", False)) and user.is_verified and user.in_group(ADMINS)


def forget(user: Any = None) -> None:
    """Drop cached permissions after group membership changes in this request."""
    cache = g.get("_permission_cache")
    if cache is None:
        return
    if user is None:
        cache.clear()
    else:
        cache.pop(getattr(user, "id", None), None)


def can_manage_user(actor: Any, user: Any) -> bool:
    if not has(actor, "manage_users"):
        return False
    if is_admin(actor):
        return True
    if user.in_group(ADMINS):
        return False
    mine = permissions_for(actor)
    return all(set(group.permissions or []) <= mine for group in user.groups)


def can_manage_group(actor: Any, group: Group) -> bool:
    """Changing join rules can grant the group's permissions just like assigning it."""
    if not has(actor, "manage_groups"):
        return False
    if group.slug == ADMINS:
        return is_admin(actor)
    return set(group.permissions or []) <= permissions_for(actor)


def can_assign(actor: Any, group: Group) -> bool:
    """Can ``actor`` add people to (or remove people from) ``group``?

    You need "manage_users", and you can't hand out more than you have: every
    permission the group grants must be one you hold yourself. Only
    administrators can change who is an administrator.
    """
    if group.is_implicit or not has(actor, "manage_users"):
        return False
    if group.slug == ADMINS:
        return is_admin(actor)
    return set(group.permissions or []) <= permissions_for(actor)


def require(*needed: str):
    """View decorator: sign-in is required, then every permission in ``needed``."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            from copydesk.auth import current_user

            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
            if not current_user.is_verified:
                return redirect(url_for("auth.verify_notice"))
            for perm in needed:
                if not has(current_user, perm):
                    abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def require_any(*options: str):
    """View decorator: sign-in is required, plus at least one permission in ``options``."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            from copydesk.auth import current_user

            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
            if not current_user.is_verified:
                return redirect(url_for("auth.verify_notice"))
            if not any(has(current_user, perm) for perm in options):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator
