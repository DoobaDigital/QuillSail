"""The appearance studio. Loading, importing and previewing are read-only."""

from __future__ import annotations

import base64
from types import SimpleNamespace

from flask import current_app, flash, g, make_response, redirect, render_template, request, url_for

from copydesk import appearance, audit, publication, settings, text
from copydesk import permissions as perms
from copydesk.auth import current_user
from copydesk.db import db
from copydesk.helpers import external_url, state
from copydesk.subscribers import signup_groups
from copydesk.themes import ThemeLoader
from copydesk.uploads import UploadError, prepare_image, store_image
from copydesk.utils import utcnow
from copydesk.views.dashboard import bp


def _values(tab: str = "appearance"):
    values, errors = {}, {}
    for d in settings.for_tab(tab):
        checkbox_form = request.form.get("full_design") and (
            not d.key.startswith("appearance.hero_") or request.form.get("hero_controls"))
        raw = request.form.get(d.key, False if d.type == "bool" and checkbox_form else settings.get(d.key))
        value, error = settings.parse_form_value(d, raw)
        values[d.key] = value
        if error:
            errors[d.key] = error
    errors.update(appearance.validate(values, appearance.DESIGN_FILES[tab][1]))
    return values, errors


def _images():
    prepared, errors, previews = {}, {}, {}
    for role in appearance.UPLOADS:
        file = request.files.get(role)
        if file and file.filename:
            try:
                image = prepare_image(file, kind="logo" if role != "favicon" else "avatar")
                prepared[role] = (image, file.filename)
                previews[role] = f"data:{image[1]};base64," + base64.b64encode(image[0]).decode("ascii")
            except UploadError as exc:
                errors[f"appearance.{role}"] = str(exc)
        elif request.form.get(f"remove_{role}"):
            previews[role] = ""
    return prepared, errors, previews


def appearance_page():
    values = {d.key: settings.get(d.key) for d in settings.for_tab("appearance")}
    errors = {}
    dashboard_matches = settings.get("appearance.dashboard_theme") == "publication"
    if request.method == "POST":
        values, errors = _values()
        action = request.form.get("action", "save")
        if action == "preset":
            name = request.form.get("preset", "")
            if name in appearance.PRESETS:
                values.update(appearance.preset_values(name))
                errors = appearance.validate(values)
                flash("Starting style loaded. Preview and save when you're ready.", "info")
            else:
                errors["preset"] = "Choose a starting style."
        elif action == "import":
            file = request.files.get("design_file")
            try:
                if not file or not file.filename:
                    raise ValueError("Choose a design file to import.")
                values.update(appearance.import_design(file.read(100_001)))
                errors = appearance.validate(values)
                flash("Design loaded. Preview and save to apply it. Logos are uploaded separately.", "info")
            except ValueError as exc:
                errors["design_file"] = str(exc) or "Choose a QuillSail appearance JSON file."
        else:
            prepared, image_errors, previews = _images()
            errors.update(image_errors)
            if not errors:
                for role, (image, name) in prepared.items():
                    values[f"appearance.{role}"] = store_image(image, name, current_user.id).path
                for role, value in previews.items():
                    if not value:
                        values[f"appearance.{role}"] = ""
                changed = [key for key, value in values.items() if settings.get(key, None) != value]
                settings.set_values(values | {"onboarding.appearance": "done"})
                if settings.get("appearance.core_styles"):
                    settings.set_value("appearance.core_styles", False)
                audit.record("settings.updated", None, actor=current_user, label="Publication appearance",
                             details={"tab": "appearance", "keys": changed})
                db.session.commit()
                if dashboard_matches:
                    flash("Publication design saved. The website, dashboard and future emails now use these settings.", "success")
                else:
                    flash("Publication design saved. The website and future emails now use these settings. "
                          "The dashboard keeps its own design.", "success")
                return redirect(url_for("dash.settings", tab="appearance"))
    groups = [
        ("identity", "Your identity", "Upload your publication's own branding.", ["brand_display", "logo_height"]),
        ("hero", "Homepage hero", "Choose the title, subtitle and logo for the top of your homepage. These controls leave the publication name, navigation and emails unchanged.",
         ["hero_display", "hero_align", "hero_title", "hero_subtitle", "hero_show_subtitle", "hero_overline", "hero_show_overline", "hero_logo_width"]),
        ("type", "Typography", "System font stacks work without external font services. Custom stacks use fonts installed on readers' devices.",
         ["article_font", "heading_font", "custom_body_font", "custom_heading_font", "body_size", "line_height"]),
        ("palette", "Color palette", "Choose your paper, ink and accent. Links and buttons adjust for contrast.",
         ["accent_color", "background", "surface", "text_color", "muted_color", "border_color", "color_mode", "dark_background", "dark_surface", "dark_text"]),
        ("layout", "Website layout", "Shape the masthead, reading column and story presentation.",
         ["masthead", "content_width", "reading_width", "issue_layout", "density", "corner_radius", "home_intro", "show_subscriber_count"]),
        ("email", "Newsletter email", "Shares your colors and typography. Email clients may simplify fonts and advanced CSS.",
         ["email_layout", "email_width", "email_size", "email_padding"]),
        ("advanced", "Advanced design", "Add your own CSS or install template themes. Website CSS also applies to the dashboard; use .dashboard for dashboard-specific rules.",
         ["theme", "custom_css", "email_css"]),
    ]
    response = make_response(render_template("dashboard/settings/appearance.html", values=values, errors=errors,
        dashboard_matches=dashboard_matches,
        groups=groups, definitions=settings.REGISTRY, presets=appearance.PRESETS,
        preset_data={key: appearance.preset_values(key) for key in appearance.PRESETS},
        logo_roles=appearance.UPLOADS, appearance_image=appearance.image_url, tabs=settings.TABS,
        dash_active="settings"), 422 if errors else 200)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.route("/settings/appearance/dashboard", methods=["GET", "POST"])
@perms.require("manage_settings")
def dashboard_design():
    """The dashboard's own design. Saving it never changes the publication design."""
    values = {d.key: settings.get(d.key) for d in settings.for_tab("dashboard_design")}
    errors = {}
    if request.method == "POST":
        values, errors = _values("dashboard_design")
        action = request.form.get("action", "save")
        if action == "preset":
            name = request.form.get("preset", "")
            if name in appearance.PRESETS:
                values.update(appearance.dashboard_preset_values(name))
                errors = appearance.validate(values, "dashboard")
                flash("Starting style loaded. Preview and save when you're ready.", "info")
            else:
                errors["preset"] = "Choose a starting style."
        elif action == "import":
            file = request.files.get("design_file")
            try:
                if not file or not file.filename:
                    raise ValueError("Choose a design file to import.")
                values.update(appearance.import_design(file.read(100_001), "dashboard_design"))
                errors = appearance.validate(values, "dashboard")
                flash("Dashboard design loaded. Preview and save to apply it.", "info")
            except ValueError as exc:
                errors["design_file"] = str(exc)
        elif not errors:
            changed = [key for key, value in values.items() if settings.get(key, None) != value]
            settings.set_values(values | {"onboarding.appearance": "done"})
            audit.record("settings.updated", None, actor=current_user, label="Dashboard design",
                         details={"tab": "dashboard_design", "keys": changed})
            db.session.commit()
            flash("Dashboard design saved. Your website and emails haven't changed.", "success")
            return redirect(url_for("dash.dashboard_design"))
    groups = [
        ("identity", "Sidebar identity", "Shows your publication's logos. Upload them under Publication.",
         ["brand_display", "logo_height"]),
        ("type", "Typography", "System font stacks work without external font services. Custom stacks use fonts installed on each device.",
         ["article_font", "heading_font", "custom_body_font", "custom_heading_font", "body_size", "line_height"]),
        ("palette", "Color palette", "Choose the paper, ink and accent. Links and buttons adjust for contrast.",
         ["accent_color", "background", "surface", "text_color", "muted_color", "border_color", "color_mode", "dark_background", "dark_surface", "dark_text"]),
        ("layout", "Layout", "Spacing between panels and the shape of corners.", ["density", "corner_radius"]),
        ("advanced", "Advanced design", "Add CSS for dashboard pages only. Website CSS rules for .dashboard also still apply.",
         ["custom_css"]),
    ]
    response = make_response(render_template("dashboard/settings/dashboard_design.html", values=values, errors=errors,
        groups=groups, definitions=settings.REGISTRY, presets=appearance.PRESETS, sources=appearance.DASHBOARD_SOURCES,
        preset_data={key: appearance.dashboard_preset_values(key) for key in appearance.PRESETS},
        tabs=settings.TABS, dash_active="settings"), 422 if errors else 200)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/settings/appearance/export")
@perms.require("manage_settings")
def appearance_export():
    response = make_response(appearance.export_design())
    response.headers.update({"Content-Type": "application/json", "Content-Disposition": 'attachment; filename="quillsail-design.json"',
                             "Cache-Control": "private, no-store"})
    return response


@bp.get("/settings/appearance/dashboard/export")
@perms.require("manage_settings")
def dashboard_design_export():
    response = make_response(appearance.export_design("dashboard_design"))
    response.headers.update({"Content-Type": "application/json", "Content-Disposition": 'attachment; filename="quillsail-dashboard-design.json"',
                             "Cache-Control": "private, no-store"})
    return response


@bp.route("/settings/appearance/preview", methods=["GET", "POST"])
@perms.require("manage_settings")
def appearance_preview():
    values, errors = _values() if request.method == "POST" else ({}, {})
    if request.method == "POST":
        # Either designer can preview; fields the form doesn't hold keep their saved values.
        dashboard_values, dashboard_errors = _values("dashboard_design")
        values.update(dashboard_values)
        errors.update(dashboard_errors)
    prepared, image_errors, images = _images() if request.method == "POST" else ({}, {}, {})
    errors.update(image_errors)
    if errors:
        response = make_response(render_template("dashboard/settings/design_errors.html", errors=errors), 422)
    else:
        appearance.override(values, images)
        g.appearance_sizes = {role: (image[3], image[4]) for role, (image, name) in prepared.items()}
        # A separate environment keeps concurrent readers on the saved theme.
        env = current_app.jinja_env.overlay(loader=ThemeLoader(state(), theme_name=settings.get("appearance.theme")))
        issue = SimpleNamespace(number=42, display_title="Ideas worth sharing", title="Ideas worth sharing",
                                intro="A small collection of stories, practical ideas and community notes. This is sample content for your design preview.",
                                preheader="Your next edition, in your own style.", sent_at=utcnow(), send_started_at=None)
        items = []
        for title, body in [
            ("A place to exchange ideas", "Great publications give their readers something useful to carry into the week. Start with a clear idea, give it room to breathe, and make it your own.\n\n**In this edition:** perspectives, resources and a note from the community."),
            ("Three things to explore this week", "- A fresh perspective on a familiar challenge\n- A practical guide worth bookmarking\n- A conversation you can contribute to\n\n[Explore the archive](" + external_url("public.issues") + ")."),
            ("From the community", "> Progress often starts with a good question.\n\nShare a project, celebrate a milestone or invite readers to get involved."),
        ]:
            rendered = text.render_markdown(body)
            items.append(SimpleNamespace(kind="text", title=title, web_html=rendered,
                                         html=text.email_html(rendered, appearance.design()["link"], state().config.origin), section="", article=None))
        kind = request.args.get("preview_format") or request.form.get("preview_format", "web")
        if kind == "dashboard":
            html = render_template(env.get_template("dashboard/design_preview.html"), dash_active="overview")
        elif kind == "home":
            template = "public/blog_home.html" if publication.is_blog() else "public/home.html"
            html = render_template(env.get_template(template), latest_issue=None, featured=None, recent=[],
                                   subscriber_count=0, groups=signup_groups() if settings.get("newsletter.ask_audience") else [],
                                   page=SimpleNamespace(items=[]), active_nav="home")
        elif kind == "email":
            g.csp_override = "default-src 'none'; img-src 'self' https: data:; style-src 'unsafe-inline'; frame-ancestors 'self'; base-uri 'none'"
            template = env.get_template("email/issue.html")
            html = render_template(template, issue=issue, items=items, intro_text=issue.intro,
                intro_html=text.email_html(text.render_markdown(issue.intro), appearance.design()["link"], state().config.origin),
                shared_preview=True, test=False, web_url=url_for("dash.appearance_preview"),
                email_subject=issue.title, subscriber_groups=[], manage_url="#", unsubscribe_url="#")
            html = appearance.inline_email_css(html)
        else:
            html = render_template(env.get_template("public/design_preview.html"), issue=issue, items=items)
        response = make_response(html)
    response.headers.update({"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer",
                             "X-Robots-Tag": "noindex, nofollow, noarchive"})
    return response
