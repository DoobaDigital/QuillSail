"""The dashboard's own design, customized separately from the publication design."""

import json
from io import BytesIO

import pytest
from sqlalchemy import select

from copydesk import appearance, settings
from copydesk.db import db
from copydesk.models import AuditEntry, User
from copydesk.utils import utcnow
from test_appearance import PATH, PREVIEW, png, post, snapshot
from test_quillsail_style import body_class, tokens

DASH = PATH + "/dashboard"
THEME = "appearance.dashboard_theme"


def stored(app, prefix: str) -> dict:
    return {key: value for key, value in snapshot(app)[0].items() if key.startswith(prefix) and key != THEME}


def test_new_dashboards_have_their_own_quillsail_design(editor_client):
    page = editor_client.get(DASH).data
    assert b'name="appearance.dashboard_theme" value="own" checked' in page
    assert b'name="preset" value="quillsail" checked' in page
    assert b'data-show-if="appearance.dashboard_theme:own"' in page
    for name in ("dashboard.accent_color", "dashboard.heading_font", "dashboard.corner_radius", "dashboard.color_mode",
                 "dashboard.density", "dashboard.brand_display", "dashboard.custom_css"):
        assert f'id="f-{name}"'.encode() in page
    assert body_class(editor_client.get("/dashboard/").data) == "dashboard designed design-quillsail density-comfortable"


def test_dashboard_design_saves_without_touching_the_publication_design(app, editor_client):
    assert post(editor_client, **appearance.preset_values("canvas")).status_code == 302
    publication = stored(app, "appearance.")
    values = appearance.dashboard_preset_values("brief") | {
        THEME: "own", "dashboard.accent_color": "#0a7d50", "dashboard.corner_radius": "4", "dashboard.color_mode": "dark"}
    response = post(editor_client, DASH, **values)
    assert response.status_code == 302 and response.headers["Location"].endswith(DASH)
    assert stored(app, "appearance.") == publication
    dash = editor_client.get("/dashboard/").data
    assert body_class(dash) == "dashboard designed design-brief density-compact"
    assert b'data-default-theme="dark"' in dash
    light = tokens(dash, "dashboard")
    assert light["accent"] == "#0a7d50" and light["radius"] == "4px" and light["font-display"].startswith("-apple-system")
    assert body_class(editor_client.get("/").data).startswith("publication designed design-canvas")
    with app.app_context():
        entry = db.session.scalars(select(AuditEntry).order_by(AuditEntry.id.desc())).first()
        assert entry.target_label == "Dashboard design" and "dashboard.accent_color" in entry.details["keys"]
        assert settings.get("onboarding.appearance") == "done"
    # Matching the publication keeps the dashboard's own design for later.
    assert post(editor_client, DASH, **{THEME: "publication"}).status_code == 302
    assert body_class(editor_client.get("/dashboard/").data).startswith("dashboard publication designed design-canvas")
    with app.app_context():
        assert settings.get("dashboard.style") == "brief" and settings.get("dashboard.accent_color") == "#0a7d50"


def test_publication_saves_presets_and_files_never_change_the_dashboard_design(app, editor_client):
    assert post(editor_client, DASH, **appearance.dashboard_preset_values("reference")).status_code == 302
    dashboard = stored(app, "dashboard.")
    assert post(editor_client, action="preset", preset="brief").status_code == 200
    assert post(editor_client, **appearance.preset_values("brief"), **{"dashboard.style": "canvas", THEME: "publication"}).status_code == 302
    exported = json.loads(editor_client.get(PATH + "/export").data)["settings"]
    assert THEME not in exported and not any(key.startswith("dashboard.") for key in exported)
    document = {"format": "quillsail.appearance.v1", "settings": {"dashboard.style": "canvas"}}
    assert post(editor_client, action="import", design_file=(BytesIO(json.dumps(document).encode()), "d.json")).status_code == 422
    assert stored(app, "dashboard.") == dashboard
    with app.app_context():
        assert settings.get(THEME) == "own"


def test_dashboard_starting_styles_and_files_load_without_saving(app, editor_client):
    before = snapshot(app)
    response = post(editor_client, DASH, action="preset", preset="canvas")
    assert response.status_code == 200
    assert b'name="dashboard.background" value="#f4f0fa"' in response.data
    assert b'name="preset" value="canvas" checked' in response.data
    assert snapshot(app) == before
    exported = json.loads(editor_client.get(DASH + "/export").data)
    assert exported["format"] == "quillsail.dashboard.v1"
    assert exported["settings"][THEME] == "own" and exported["settings"]["dashboard.style"] == "quillsail"
    assert not any(key.startswith("appearance.") and key != THEME for key in exported["settings"])
    exported["settings"]["dashboard.style"] = "reference"
    exported["settings"]["dashboard.text_color"] = "#202122"
    response = post(editor_client, DASH, action="import", design_file=(BytesIO(json.dumps(exported).encode()), "d.json"))
    assert response.status_code == 200 and b'name="dashboard.text_color" value="#202122"' in response.data
    assert snapshot(app) == before
    for bad in ({"format": "quillsail.appearance.v1", "settings": {"dashboard.style": "brief"}},
                {"format": "quillsail.dashboard.v1", "settings": {"appearance.accent_color": "#123456"}},
                {"format": "quillsail.dashboard.v1", "settings": {"dashboard.corner_radius": 999}}):
        response = post(editor_client, DASH, action="import", design_file=(BytesIO(json.dumps(bad).encode()), "d.json"))
        assert response.status_code == 422
    assert b"Choose a QuillSail dashboard design JSON file." in response.data or b"Use a value from" in response.data
    assert snapshot(app) == before


@pytest.mark.parametrize("values", [
    {THEME: "canvas"}, {"dashboard.background": "red;}</style>"}, {"dashboard.corner_radius": "99"},
    {"dashboard.custom_body_font": "Georgia; background:url(https://example.test)"},
    {"dashboard.heading_font": "custom", "dashboard.custom_heading_font": ""},
])
def test_invalid_dashboard_design_is_rejected_without_writes(app, editor_client, values):
    before = snapshot(app)
    response = post(editor_client, DASH, **values)
    assert response.status_code == 422
    assert snapshot(app) == before
    if THEME in values:
        assert b'aria-describedby="f-appearance.dashboard_theme-help f-appearance.dashboard_theme-error"' in response.data
        assert b'href="#f-appearance.dashboard_theme"' in response.data
    assert editor_client.post(DASH, data={THEME: "publication"}).status_code == 400
    assert snapshot(app) == before


def test_dashboard_design_requires_permission(app, client):
    with app.app_context():
        reader = User(email="design-reader2@example.test", username="design-reader2", display_name="Reader",
                      email_verified_at=utcnow())
        db.session.add(reader)
        db.session.commit()
        uid, uv = reader.id, reader.auth_version
    with client.session_transaction() as session:
        session.update(uid=uid, uv=uv, _csrf="test-csrf")
    before = snapshot(app)
    for path in (DASH, DASH + "/export"):
        assert client.get(path).status_code == 403
    assert post(client, DASH, **{THEME: "publication"}).status_code == 403
    assert post(client, "/dashboard/getting-started/appearance/skip").status_code == 403
    assert snapshot(app) == before


def test_dashboard_design_preview_is_private_and_unsaved(app, editor_client):
    assert post(editor_client, **appearance.preset_values("broadsheet")).status_code == 302
    before = snapshot(app)
    values = appearance.dashboard_preset_values("canvas") | {"dashboard.accent_color": "#aa3300", THEME: "own"}
    response = post(editor_client, PREVIEW + "?preview_format=dashboard", **values)
    assert response.status_code == 200
    assert body_class(response.data).startswith("dashboard designed design-canvas")
    assert tokens(response.data, "dashboard")["bg"] == "#f4f0fa"
    assert b"Your dashboard has its own design" in response.data
    response = post(editor_client, PREVIEW + "?preview_format=dashboard", **{THEME: "publication"})
    assert body_class(response.data).startswith("dashboard publication designed design-broadsheet")
    assert b"carry into the tools you use every day" in response.data
    response = post(editor_client, PREVIEW + "?preview_format=dashboard", **{"dashboard.text_color": "nope"})
    assert response.status_code == 422
    assert snapshot(app) == before


def test_dashboard_css_applies_only_to_the_dashboards_own_design(app, editor_client):
    css = ".dash-sidebar{border-right-width:4px}</style><script id=injected>alert(1)</script>"
    assert post(editor_client, DASH, **{"dashboard.custom_css": css}).status_code == 302
    dash = editor_client.get("/dashboard/").data
    assert b".dash-sidebar{border-right-width:4px}\\3c /style>" in dash and b"<script id=injected>" not in dash
    assert b"border-right-width:4px" not in editor_client.get("/").data
    assert b"border-right-width:4px" not in editor_client.get("/dashboard/?dashboard_style=default").data
    assert post(editor_client, DASH, **{THEME: "publication"}).status_code == 302
    assert b"border-right-width:4px" not in editor_client.get("/dashboard/").data


def test_own_dashboard_design_shows_publication_logos_with_its_own_sidebar_choices(app, editor_client):
    values = appearance.preset_values("broadsheet") | {"appearance.theme": "broadsheet", "appearance.brand_display": "name"}
    response = post(editor_client, **values, logo=(png(), "logo.png"), logo_dark=(png(), "dark.png"), favicon=(png(), "icon.png"))
    assert response.status_code == 302
    assert post(editor_client, DASH, **{"dashboard.brand_display": "both", "dashboard.logo_height": "64"}).status_code == 302
    page = editor_client.get("/dashboard/").data
    assert b"logo-light" in page and b"logo-dark" in page and b'class="dash-publication-name"' in page
    assert tokens(page, "dashboard")["logo-height"] == "64px"
    assert b'<link rel="icon" href="/uploads/' in page
    assert b"/theme/broadsheet/" not in page and b"--bg:#faf8f2" not in page
    assert b"logo-light" not in editor_client.get("/").data.split(b"</header>")[0]


def test_publication_page_points_to_the_dashboard_design(editor_client):
    page = editor_client.get(PATH).data
    assert b'href="/dashboard/settings/appearance/dashboard"' in page and b"its own design" in page
    assert b'name="appearance.dashboard_theme"' not in page
    assert b"Applies to the website and future emails." in page
    saved = editor_client.post(PATH, data={"csrf_token": "test-csrf", **appearance.preset_values("canvas")}, follow_redirects=True)
    assert b"The dashboard keeps its own design." in saved.data
