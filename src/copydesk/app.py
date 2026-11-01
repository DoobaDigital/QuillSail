"""The application factory: ``create_app()`` builds a configured Flask app."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, g, has_request_context, jsonify, render_template, request
from markupsafe import Markup
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from copydesk import (
    __version__,
    appearance,
    auth,
    jobs,
    launch,
    permissions,
    publication,
    security,
    settings,
    text,
    themes,
    uploads,
    workflow,
)
from copydesk.colors import accent_tokens
from copydesk.config import Config, load_config
from copydesk.db import db
from copydesk.helpers import external_url
from copydesk.hooks import Extension, Hooks, load_extensions
from copydesk.icons import icon
from copydesk.models import Page, User
from copydesk.notify import EMAIL_STYLE
from copydesk.utils import humanize_delta, pluralize, to_local, utcnow

log = logging.getLogger("copydesk")
PACKAGE_DIR = Path(__file__).parent


@dataclass
class CopydeskState:
    """Everything QuillSail keeps per app (``current_app.extensions["copydesk"]``)."""

    config: Config
    hooks: Hooks = field(default_factory=Hooks)
    themes: dict[str, themes.Theme] = field(default_factory=dict)
    active_theme: str = "default"
    extension_template_dirs: list[Path] = field(default_factory=list)
    dashboard_links: list[Any] = field(default_factory=list)
    extensions: dict[str, Extension] = field(default_factory=dict)
    markdown: Any = None
    setup_needed: bool | None = None

    def theme_chain(self) -> list[themes.Theme]:
        return themes.chain(self.themes, self.active_theme)


class PrefixMiddleware:
    """Serve the site under a path such as /newsletter when base_url includes one."""

    def __init__(self, wsgi_app, prefix: str) -> None:
        self.wsgi_app = wsgi_app
        self.prefix = prefix.rstrip("/")

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path == self.prefix or path.startswith(self.prefix + "/"):
            environ["PATH_INFO"] = path[len(self.prefix):] or "/"
        environ["SCRIPT_NAME"] = self.prefix
        return self.wsgi_app(environ, start_response)


def create_app(
    config: Config | None = None,
    *,
    config_path: str | os.PathLike | None = None,
    overrides: dict[str, Any] | None = None,
) -> Flask:
    config = config or load_config(config_path, overrides)
    _configure_logging(config)

    app = Flask(
        "copydesk",
        static_folder=str(PACKAGE_DIR / "static"),
        static_url_path="/static",
        template_folder=None,
    )
    app.config.update(
        SECRET_KEY=config.secret_key,
        DEBUG=config.debug,
        TESTING=config.testing,
        SERVER_NAME=config.server_name,
        APPLICATION_ROOT=config.url_prefix or "/",
        PREFERRED_URL_SCHEME="https" if config.is_https else "http",
        SESSION_COOKIE_NAME="copydesk_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.is_https,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        MAX_CONTENT_LENGTH=max(config.max_upload_mb, 20) * 1024 * 1024,
        RATELIMIT_ENABLED=not config.testing,
        JSON_SORT_KEYS=False,
        TEMPLATES_AUTO_RELOAD=config.debug,
    )

    state = CopydeskState(config=config)
    state.hooks.raise_errors = config.testing
    state.themes = themes.discover(config.themes_dir)
    app.extensions["copydesk"] = state
    app.jinja_options = {
        **app.jinja_options,
        "loader": themes.ThemeLoader(state),
        "trim_blocks": True,
        "lstrip_blocks": True,
    }

    db.init_app(app, config.database_url)
    _register_template_helpers(app, state)
    _register_blueprints(app)
    _register_request_hooks(app, state)
    _register_error_handlers(app)

    load_extensions(app, state, config.extensions, config.extensions_dir, config.extension_options)

    wsgi = app.wsgi_app
    if config.url_prefix:
        wsgi = PrefixMiddleware(wsgi, config.url_prefix)
    if config.proxy_hops > 0:
        hops = config.proxy_hops
        wsgi = ProxyFix(wsgi, x_for=hops, x_proto=hops, x_host=hops, x_port=hops)
    app.wsgi_app = wsgi

    state.hooks.fire("app.ready", app=app)
    if config.run_jobs_in_web and not config.testing:
        jobs.start_background_worker(app)
    return app


def _configure_logging(config: Config) -> None:
    level = getattr(logging, config.log_level, logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    logging.getLogger("copydesk").setLevel(level)


def refresh_theme(app: Flask) -> None:
    """Switch templates when an editor picks a different theme."""
    state: CopydeskState = app.extensions["copydesk"]
    name = settings.get("appearance.theme") or "default"
    if name not in state.themes:
        name = "default"
    if name != state.active_theme:
        state.active_theme = name
        if app.jinja_env.cache is not None:
            app.jinja_env.cache.clear()


def _register_blueprints(app: Flask) -> None:
    from copydesk import cloudflare, domains, edge  # noqa: F401 — registers background DNS checks
    from copydesk.views import account, api, business, competitions, public, setup, subscribe, write
    from copydesk.views import auth as auth_views
    from copydesk.views.dashboard import bp as dashboard_bp

    app.register_blueprint(setup.bp)
    app.register_blueprint(auth_views.bp)
    app.register_blueprint(account.bp)
    app.register_blueprint(subscribe.bp)
    app.register_blueprint(write.bp)
    app.register_blueprint(competitions.bp)
    app.register_blueprint(business.bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(public.bp)


SETUP_EXEMPT = {"static", "public.health", "public.theme_asset", "public.upload"}


def _register_request_hooks(app: Flask, state: CopydeskState) -> None:
    @app.before_request
    def _before():
        from copydesk.maintenance import active

        endpoint = request.endpoint or ""
        if endpoint != "public.health" and active(state.config):
            return app.response_class("This publication is being updated. Please try again shortly.",
                                      status=503, mimetype="text/plain",
                                      headers={"Cache-Control": "no-store", "Retry-After": "60"})
        if endpoint == "static":
            return None
        try:
            if state.setup_needed is not False:
                has_users = db.session.scalar(select(User.id).limit(1)) is not None
                state.setup_needed = not has_users
        except (OperationalError, ProgrammingError):
            db.session.rollback()
            return render_template("errors/not_installed.html"), 503
        refresh_theme(app)
        auth.load_user()
        security.check_csrf()
        if state.setup_needed and not endpoint.startswith("setup.") and endpoint not in SETUP_EXEMPT:
            from flask import redirect, url_for

            return redirect(url_for("setup.index"))
        from copydesk import launch

        return launch.gate()

    @app.after_request
    def _after(response):
        return security.apply_headers(response)


def _register_error_handlers(app: Flask) -> None:
    messages = {
        400: ("That request didn't make sense", "Something about that request was off. Go back and try again."),
        403: ("You don't have access to this page", "If you think you should, ask an administrator to check your groups."),
        404: ("Page not found", "The page may have moved, or the link might be mistyped."),
        405: ("That didn't work", "This page can't be used that way."),
        413: ("That file is too large", "Please choose a smaller file and try again."),
        429: ("Slow down a little", "You've tried that too many times. Please wait a few minutes and try again."),
        500: ("Something went wrong on our end", "The error has been logged. Please try again in a moment."),
    }

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        code = exc.code or 500
        if request.path.startswith("/api/"):
            return jsonify(error=exc.name, message=exc.description), code
        title, message = messages.get(code, (exc.name, exc.description or ""))
        if code == 400 and exc.description == "csrf":
            title = "This form has expired"
            message = "For your security, forms stop working after a while. Go back, reload the page and try again."
        try:
            return render_template("errors/error.html", code=code, title=title, message=message), code
        except Exception:  # noqa: BLE001 - never fail while showing an error page
            log.exception("Error page failed to render")
            return f"{code} {title}", code

    @app.errorhandler(Exception)
    def _server_error(exc: Exception):
        if isinstance(exc, HTTPException):
            return _http_error(exc)
        log.exception("Unhandled error on %s", request.path)
        db.session.rollback()
        if app.config.get("TESTING"):
            raise exc
        title, message = messages[500]
        if request.path.startswith("/api/"):
            return jsonify(error="Internal Server Error", message=message), 500
        try:
            return render_template("errors/error.html", code=500, title=title, message=message), 500
        except Exception:  # noqa: BLE001
            return "500 Internal Server Error", 500


# --------------------------------------------------------------------------- templates


def _format_date(value: datetime | None, style: str = "medium") -> str:
    local = to_local(value, settings.get("site.timezone"))
    if local is None:
        return ""
    if style == "short":
        return f"{local:%b} {local.day}"
    if style == "long":
        return f"{local:%A}, {local:%B} {local.day}, {local.year}"
    if style == "month":
        return f"{local:%B} {local.year}"
    return f"{local:%b} {local.day}, {local.year}"


def _format_time(value: datetime | None) -> str:
    local = to_local(value, settings.get("site.timezone"))
    if local is None:
        return ""
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return f"{_format_date(value)} at {_format_time(value)}"


def _time_ago(value: datetime | None) -> str:
    if value is None:
        return ""
    delta = utcnow() - value
    if delta.total_seconds() < 0:
        return "in " + humanize_delta(delta)
    phrase = humanize_delta(delta)
    return phrase if phrase == "just now" else phrase + " ago"


def _iso(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") + "Z" if value else ""


def _datetime_local(value: datetime | None) -> str:
    local = to_local(value, settings.get("site.timezone"))
    return f"{local:%Y-%m-%dT%H:%M}" if local else ""


def _register_template_helpers(app: Flask, state: CopydeskState) -> None:
    env = app.jinja_env
    env.filters.update(
        markdown=text.render_markdown,
        inline_markdown=text.render_inline,
        excerpt=text.excerpt,
        date=_format_date,
        time=_format_time,
        datetime=_format_datetime,
        time_ago=_time_ago,
        isodate=_iso,
        datetime_local=_datetime_local,
        number=lambda n: f"{n or 0:,}",
    )
    env.globals.update(
        pluralize=pluralize,
        version=__version__,
        upload_url=uploads.url,
        external_url=external_url,
        STATUSES=workflow.STATUSES,
        now=utcnow,
        icon=icon,
        es=EMAIL_STYLE,
    )

    def nav_items() -> list[tuple[str, str, str]]:
        from copydesk import launch

        if launch.is_soon() and not launch.editor():
            return []
        cached = g.get("_nav_items")
        if cached is not None:
            return cached
        from flask import url_for

        items = [
            ("articles", "Blog" if publication.is_blog() else "Articles", url_for("public.articles")),
            ("competitions", "Competitions", url_for("competitions.index")),
        ]
        if publication.has_newsletter():
            items.insert(0, ("issues", "Issues", url_for("public.issues")))
        pages = db.session.scalars(
            select(Page).where(Page.show_in_nav.is_(True), Page.is_published.is_(True)).order_by(Page.nav_position)
        ).all()
        items.extend((f"page:{p.slug}", p.title, url_for("public.page", slug=p.slug)) for p in pages)
        if settings.get("business.enabled"):
            items.append(("business", "For businesses", url_for("business.contact")))
        if settings.get("submissions.enabled") or (publication.is_blog() and permissions.has(auth.current_user, "publish")):
            items.append(("write", "My posts" if publication.is_blog() and auth.current_user.is_authenticated else "Write for us", url_for("write.index")))
        items = state.hooks.apply_filters("nav.items", items, user=auth.current_user)
        g._nav_items = items
        return items

    def theme_stylesheets() -> list[str]:
        from flask import url_for

        if request.blueprint == "dash" and request.args.get("dashboard_style") == "default" and not g.get("appearance_preview"):
            return []
        urls = []
        for theme in reversed(themes.chain(state.themes, g.get("preview_theme") or state.active_theme)):
            for sheet in theme.stylesheets:
                urls.append(url_for("public.theme_asset", theme=theme.name, filename=sheet, v=theme.version))
        return urls

    def email_markdown(source: str | None, link_color: str | None = None) -> Markup:
        """Markdown rendered with inline styles, for use inside email templates."""
        color = link_color or accent_tokens(settings.get("appearance.accent_color"))["accent"]
        return text.email_html(text.render_markdown(source), color, state.config.origin)

    def dashboard_links():
        return [
            link for link in state.dashboard_links
            if link.permission is None or permissions.has(auth.current_user, link.permission)
        ]

    @app.context_processor
    def _context() -> dict[str, Any]:
        design = appearance.design()
        in_dashboard = has_request_context() and request.blueprint == "dash"
        dash_design = appearance.dashboard_design(design) if in_dashboard else design
        return {
            "launch_soon": launch.is_soon(),
            "launch_signup_available": launch.signup_available() if launch.is_soon() else True,
            "current_user": auth.current_user,
            "blog_mode": publication.is_blog(),
            "newsletter_enabled": publication.has_newsletter(),
            "site": settings.SettingsNamespace("site"),
            "setting": settings.get,
            "can": lambda perm: permissions.has(auth.current_user, perm),
            "csrf_token": security.csrf_token,
            "csp_nonce": security.csp_nonce,
            "slot": lambda name, **kw: state.hooks.render_slot(name, **kw),
            "accent": accent_tokens(settings.get("appearance.accent_color")),
            "nav_items": nav_items,
            "email_markdown": email_markdown,
            "theme_stylesheets": theme_stylesheets,
            "extension_dashboard_links": dashboard_links,
            "Markup": Markup,
            "design": design,
            "design_tokens": appearance.web_tokens(design),
            "dash_design": dash_design,
            "dashboard_design_tokens": lambda: appearance.web_tokens(dash_design, dashboard=True),
            "appearance_image": appearance.image_url,
            "custom_css_version": appearance.css_version,
            "home_hero": appearance.home_hero,
            "email_brand": appearance.email_brand,
            "design_preview": g.get("appearance_preview", False),
            "dashboard_default": in_dashboard and request.args.get("dashboard_style") == "default" and not g.get("appearance_preview"),
            "es": appearance.email_design(design),
        }
