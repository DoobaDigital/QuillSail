"""QuillSail's own style as the default look, Getting started, and migration 0008."""

import re
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from copydesk import appearance, migrate, newsletter, settings
from copydesk.colors import contrast
from copydesk.db import db, make_engine
from copydesk.models import AuditEntry, User
from test_appearance import PATH, post, snapshot

THEME = "appearance.dashboard_theme"
DASH = PATH + "/dashboard"


def body_class(page: bytes) -> str:
    return re.search(rb'<body class="([^"]*)"', page).group(1).decode()


def tokens(page: bytes, selector: str) -> dict[str, str]:
    """The light-mode design tokens a page declares for .publication or .dashboard."""
    css = re.search(rb"<style nonce=\"[^\"]+\">\." + selector.encode() + rb"\{([^}]*)\}", page).group(1).decode()
    return {key.removeprefix("--"): value.lower() for key, value in (item.split(":", 1) for item in css.split(";"))}


def test_new_sites_use_quillsail_style_on_website_dashboard_and_email(app, editor_client, admin):
    home = editor_client.get("/").data
    assert body_class(home).startswith("publication designed design-quillsail")
    assert b'data-default-theme="light"' in home
    light = tokens(home, "publication")
    assert light["accent"] == "#6e4cc2" and light["text"] == "#000000" and light["border"] == "#000000"
    assert light["radius"] == "0px" and light["font-display"].startswith("amiri")
    assert light["action"] == "#6e4cc2" and light["on-action"] == "#ffffff"
    assert contrast(light["on-action"], light["action"]) >= 4.5
    dash = editor_client.get("/dashboard/").data
    assert body_class(dash) == "dashboard designed design-quillsail density-comfortable"
    assert b'data-default-theme="light"' in dash
    with app.test_request_context("/"):
        dark = appearance.design()
        # Dark mode softens white: 86% text, 40% rules, 14% fills; secondary text stays ink.
        assert (dark["dark_text"], dark["dark_muted"], dark["dark_border"], dark["dark_fill"]) == (
            "#dbdbdb", "#dbdbdb", "#666666", "#242424")
        assert contrast(dark["dark_link"], dark["dark_surface"]) >= 4.5
        issue = newsletter.create(db.session.get(User, admin), "A plain issue")
        newsletter.add_block(issue, "text", "A story", "A paragraph with a [link](https://example.test).")
        _subject, html, _text = newsletter.render(issue)
        assert "Amiri" in html and "#6e4cc2" in html.lower() and "email-classic" in html


def checklist(page: bytes) -> list[str]:
    section = re.search(rb'<ul class="checklist">(.*?)</ul>', page, re.S)
    return re.findall(r"<li>\s*(.*?)\s*</li>", section.group(1).decode(), re.S) if section else []


@pytest.mark.parametrize("mode,label", [("newsletter", "newsletter"), ("blog", "blog"), ("hybrid", "blog and newsletter")])
def test_getting_started_puts_appearance_first(app, editor_client, mode, label):
    with app.app_context():
        settings.set_value("site.mode", mode)
        db.session.commit()
    items = checklist(editor_client.get("/dashboard/").data)
    assert f"Change the appearance of your dashboard and {label}</a>" in items[0]
    assert 'href="/dashboard/settings/appearance"' in items[0]
    assert "Don&#39;t want to" in items[0] or "Don't want to" in items[0]
    assert "keep the current appearance" in items[0]
    assert all("want to" not in item for item in items[1:])


def test_skipping_appearance_completes_the_item_without_changing_the_design(app, editor_client):
    before = {key: value for key, value in snapshot(app)[0].items() if key.startswith("appearance.")}
    assert editor_client.post("/dashboard/getting-started/appearance/skip").status_code == 400
    response = post(editor_client, "/dashboard/getting-started/appearance/skip")
    assert response.status_code == 302 and response.headers["Location"].endswith("/dashboard/")
    with app.app_context():
        assert settings.get("onboarding.appearance") == "skipped"
        assert db.session.scalars(select(AuditEntry).order_by(AuditEntry.id.desc())).first().target_label == "Getting started"
    assert {key: value for key, value in snapshot(app)[0].items() if key.startswith("appearance.")} == before
    first = checklist(editor_client.get("/dashboard/").data)[0]
    assert "<s class=\"muted\">Change the appearance" in first and "want to" not in first


def test_saving_either_appearance_choice_completes_getting_started(app, editor_client):
    assert "<a href" in checklist(editor_client.get("/dashboard/").data)[0]
    assert post(editor_client, DASH, **{THEME: "own"}).status_code == 302
    assert "<s class" in checklist(editor_client.get("/dashboard/").data)[0]
    with app.app_context():
        settings.set_value("onboarding.appearance", "")
        db.session.commit()
    assert post(editor_client, **appearance.preset_values("quillsail")).status_code == 302
    assert "<s class" in checklist(editor_client.get("/dashboard/").data)[0]


# --- Migration 0008 ---------------------------------------------------------------

SETTINGS = sa.table("settings", sa.column("key", sa.String()), sa.column("value", sa.JSON()),
                    sa.column("updated_at", sa.DateTime()))
# What the designer stored for Classic before QuillSail's style became the default.
OLD_CLASSIC = appearance.preset_values("classic")


def upgrade_from_0007(tmp_path, rows: dict) -> dict:
    engine = make_engine(f"sqlite:///{tmp_path}/upgrade.db")
    try:
        migrate.upgrade(engine, "0007")
        with engine.begin() as conn:
            for key, value in rows.items():
                conn.execute(SETTINGS.insert().values(key=key, value=value, updated_at=datetime(2026, 10, 1)))
        migrate.upgrade(engine)
        with engine.connect() as conn:
            return dict(conn.execute(sa.select(SETTINGS.c.key, SETTINGS.c.value)).all())
    finally:
        engine.dispose()


def test_migration_moves_untouched_defaults_to_quillsail_and_keeps_branding(tmp_path):
    rows = OLD_CLASSIC | {"appearance.accent_color": "#1f5bd8", "appearance.logo": "2026/10/logo.png",
                          "appearance.brand_display": "both", "appearance.hero_title": "Welcome", "site.name": "Existing"}
    stored = upgrade_from_0007(tmp_path, rows)
    for key in ("appearance.style", "appearance.accent_color", "appearance.heading_font", "appearance.corner_radius",
                "appearance.color_mode", "appearance.text_color", "appearance.dark_background"):
        assert key not in stored
    assert stored["appearance.logo"] == "2026/10/logo.png" and stored["appearance.hero_title"] == "Welcome"
    assert stored["appearance.brand_display"] == "both" and stored["site.name"] == "Existing"
    assert THEME not in stored and "onboarding.appearance" not in stored and "appearance.core_styles" not in stored


def test_migration_keeps_a_saved_design_and_its_dashboard(tmp_path):
    rows = appearance.preset_values("canvas")
    stored = upgrade_from_0007(tmp_path, rows)
    assert {key: stored[key] for key in rows} == rows
    assert stored[THEME] == "publication" and stored["onboarding.appearance"] == "done"
    assert stored["appearance.core_styles"] is False


@pytest.mark.parametrize("change", [{"appearance.accent_color": "#123456"}, {"appearance.custom_css": "h1{color:red}"},
                                    {"appearance.theme": "broadsheet"}, {"appearance.article_font": "sans"}])
def test_migration_keeps_built_in_styles_for_sites_changed_before_the_designer(tmp_path, change):
    stored = upgrade_from_0007(tmp_path, change)
    assert stored["appearance.core_styles"] is True and stored[THEME] == "publication"
    expected = {"appearance.style": "classic", "appearance.text_color": "#16181d", "appearance.corner_radius": 10,
                "appearance.color_mode": "auto", "appearance.heading_font": "inherit", "appearance.dark_text": ""}
    expected = expected | {"appearance.accent_color": "#1F5BD8", "appearance.article_font": "serif"} | change
    assert {key: stored[key] for key in expected} == expected


def test_sites_kept_on_built_in_styles_look_as_before(app, editor_client):
    with app.app_context():
        settings.set_values(appearance.CLASSIC | {
            "appearance.style": "classic", "appearance.accent_color": "#123456", "appearance.core_styles": True,
            THEME: "publication", "onboarding.appearance": "done"})
        db.session.commit()
    home = editor_client.get("/").data
    assert body_class(home) == "publication" and b'data-default-theme="auto"' in home
    assert b"--accent: #123456" in home
    dash = editor_client.get("/dashboard/").data
    assert body_class(dash) == "dashboard publication" and "<s class" in checklist(dash)[0]
    assert b'name="preset" value="classic" checked' in editor_client.get(PATH).data
    assert b'name="appearance.dashboard_theme" value="publication" checked' in editor_client.get(DASH).data


def test_dashboard_navigation_counts_stay_readable_in_designed_dashboards():
    """Counts sit on the accent color, so their text must not use the accent too."""
    from pathlib import Path

    import copydesk

    css = (Path(copydesk.__file__).parent / "static/css/dashboard.css").read_text()
    assert not re.search(r"\.count[^{}]*\{[^}]*color:var\(--on-accent-soft", css)
