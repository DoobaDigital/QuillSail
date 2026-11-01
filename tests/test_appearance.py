import json
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import func, select

from copydesk import appearance, newsletter, settings
from copydesk.db import db
from copydesk.models import Job, Setting, Upload, User
from copydesk.utils import utcnow

PATH = "/dashboard/settings/appearance"
PREVIEW = PATH + "/preview"


def post(client, path=PATH, **values):
    return client.post(path, data={"csrf_token": "test-csrf", **values})


def png():
    image = Image.new("P", (20, 20), 0)
    image.putpalette([255, 0, 255, 0, 0, 0] + [0] * 762)
    image.putpixel((10, 10), 1)
    stream = BytesIO()
    image.save(stream, "PNG", transparency=0)
    stream.seek(0)
    return stream


def snapshot(app):
    with app.app_context():
        return ({row.key: row.value for row in db.session.scalars(select(Setting))},
                db.session.scalar(select(func.count()).select_from(Upload)),
                db.session.scalar(select(func.count()).select_from(Job)),
                sorted(app.extensions["copydesk"].config.uploads_dir.rglob("*")))


def test_designer_requires_permission_and_csrf(app, client, editor_client):
    assert editor_client.get(PATH).status_code == 200
    assert editor_client.post(PREVIEW).status_code == 400
    assert editor_client.post(PATH).status_code == 400
    with app.app_context():
        reader = User(email="design-reader@example.test", username="design-reader", display_name="Reader", email_verified_at=utcnow())
        db.session.add(reader)
        db.session.commit()
        uid, uv = reader.id, reader.auth_version
    with client.session_transaction() as session:
        session.update(uid=uid, uv=uv, _csrf="test-csrf")
    for path in (PATH, PREVIEW, PATH + "/export"):
        assert client.get(path).status_code == 403
    assert post(client, PREVIEW).status_code == 403


@pytest.mark.parametrize("name,layout", [("quillsail", "classic"), ("classic", "classic"), ("broadsheet", "editorial"),
                                         ("brief", "digest"), ("reference", "reference"), ("canvas", "cards")])
def test_presets_preview_website_and_email_without_writes(app, editor_client, name, layout):
    before = snapshot(app)
    values = appearance.preset_values(name)
    response = post(editor_client, PREVIEW, **values)
    assert response.status_code == 200
    assert f"design-{name}".encode() in response.data
    assert b"Ideas worth sharing" in response.data
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "noindex" in response.headers["X-Robots-Tag"]
    email = post(editor_client, PREVIEW, preview_format="email", **values)
    assert email.status_code == 200
    assert f"email-{layout}".encode() in email.data
    assert f"max-width:{values['appearance.email_width']}px".encode() in email.data
    assert "style-src 'unsafe-inline'" in email.headers["Content-Security-Policy"]
    assert snapshot(app) == before
    live = editor_client.get("/").data
    assert b"publication designed design-quillsail" in live
    if name != "quillsail":
        assert f"design-{name}".encode() not in live


def test_unsaved_theme_preview_does_not_change_active_loader(app, editor_client):
    editor_client.get("/")
    original = app.extensions["copydesk"].active_theme
    loader = app.jinja_env.loader
    response = post(editor_client, PREVIEW, **{"appearance.theme": "broadsheet"})
    assert response.status_code == 200
    assert b"/theme/broadsheet/" in response.data
    assert app.extensions["copydesk"].active_theme == original
    assert app.jinja_env.loader is loader
    assert b"/theme/broadsheet/" not in editor_client.get("/").data


def test_preset_and_import_load_without_saving(app, editor_client):
    before = snapshot(app)
    response = post(editor_client, action="preset", preset="canvas")
    assert response.status_code == 200
    assert b'value="#f4f0fa"' in response.data
    document = {"format": "quillsail.appearance.v1", "settings": appearance.preset_values("reference")}
    response = post(editor_client, action="import", design_file=(BytesIO(json.dumps(document).encode()), "design.json"))
    assert response.status_code == 200
    assert b'value="reference"' in response.data
    assert snapshot(app) == before


def test_save_applies_to_website_dashboard_and_actual_newsletter_render(app, editor_client, admin):
    response = post(editor_client, **appearance.preset_values("canvas"), **{"appearance.email_css": ".email-story h2 { color: #123456 !important; }", "appearance.custom_css": ".dashboard .panel {border-width:2px;}"})
    assert response.status_code == 302
    assert b"designed design-canvas" in editor_client.get("/").data
    with app.test_request_context("/"):
        issue = newsletter.create(db.session.get(User, admin), "A styled issue")
        newsletter.add_block(issue, "text", "A story", "A paragraph with a [useful link](https://example.test).")
        subject, html, plain = newsletter.render(issue)
        assert "email-cards" in html and "max-width:600px" in html
        assert "#123456" in html and "Rockwell" in html
        assert "Unsubscribe" in html and "Choose what you get" in html
        assert "A story" in plain and "A paragraph" in plain
        assert subject.endswith("A styled issue")
    # The dashboard keeps its own theme until someone chooses to match the publication.
    dash = editor_client.get(PATH).data
    assert b'<body class="dashboard designed design-quillsail' in dash and b"--bg:#f4f0fa" not in dash
    assert post(editor_client, PATH + "/dashboard", **{"appearance.dashboard_theme": "publication"}).status_code == 302
    dash = editor_client.get(PATH).data
    assert b"dashboard publication designed design-canvas" in dash
    assert b"css/publication.css" in dash and b"css/dashboard.css" in dash
    assert b"<link rel=\"stylesheet\" href=\"/custom.css" in dash
    assert b"--bg:#f4f0fa" in dash and b"Rockwell" in dash


@pytest.mark.parametrize("name", appearance.PRESETS)
def test_dashboard_preview_is_private_isolated_and_has_no_live_actions(app, editor_client, name):
    from html.parser import HTMLParser

    class Actions(HTMLParser):
        def handle_starttag(self, tag, attrs):
            fields = dict(attrs)
            if tag == "a" and fields.get("href", "").startswith("/"):
                assert fields["href"] == "#cd-main"
            if tag == "form":
                assert fields.get("action") == "#"
            if tag == "button" and fields.get("type") == "submit":
                assert "disabled" in fields

    before = snapshot(app)
    response = post(editor_client, PREVIEW, preview_format="dashboard", **appearance.preset_values(name),
                    logo=(png(), "sample.png"), **{"appearance.dashboard_theme": "publication"})
    assert response.status_code == 200, response.data[:300]
    assert f"dashboard publication designed design-{name}".encode() in response.data
    assert b"Dashboard preview" in response.data and b"Sample audience" in response.data
    assert b"data:image/png;base64," in response.data
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "noindex" in response.headers["X-Robots-Tag"]
    Actions().feed(response.get_data(as_text=True))
    assert snapshot(app) == before
    actual = editor_client.get(PATH).data
    assert b'<body class="dashboard designed design-quillsail' in actual
    assert b"data:image/png;base64," not in actual


def test_dashboard_uses_saved_branding_dark_variant_icon_and_template_styles(app, editor_client):
    values = appearance.preset_values("broadsheet") | {"appearance.theme": "broadsheet", "appearance.brand_display": "both", "appearance.color_mode": "light"}
    response = post(editor_client, **values,
                    logo=(png(), "logo.png"), logo_dark=(png(), "dark.png"), favicon=(png(), "icon.png"))
    assert response.status_code == 302
    assert post(editor_client, PATH + "/dashboard", **{"appearance.dashboard_theme": "publication"}).status_code == 302
    page = editor_client.get("/dashboard/").data
    assert b"/theme/broadsheet/" in page
    assert b"dash-brand-identity" in page and b"logo-light" in page and b"logo-dark" in page
    assert b'<link rel="icon" href="/uploads/' in page
    assert b'data-default-theme="light"' in page
    assert b'data-theme-toggle' in page
    assert b'action="/logout"' in page and b'name="csrf_token"' in page


def test_same_length_custom_css_edits_invalidate_the_dashboard_and_public_cache(editor_client):
    import re

    def url(path):
        return re.search(rb'href="([^"]*custom.css\?[^"]*)"', editor_client.get(path).data).group(1)

    assert post(editor_client, **{"appearance.custom_css": ".publication{color:#123456}"}).status_code == 302
    first = url(PATH)
    assert first == url("/")
    assert post(editor_client, **{"appearance.custom_css": ".publication{color:#654321}"}).status_code == 302
    assert url(PATH) != first and url(PATH) == url("/")


def test_dashboard_tokens_keep_text_readable_on_different_page_and_panel_colors(app):
    import re

    from copydesk.colors import contrast

    with app.test_request_context("/"):
        appearance.override({**appearance.preset_values("classic"), "appearance.background": "#ffffff", "appearance.surface": "#000000", "appearance.text_color": "#ffffff"})
        css = str(appearance.web_tokens(appearance.design(), dashboard=True))
        light = dict(re.findall(r"--([a-z-]+):([^;}]+)", css.split("@media")[0]))
        assert contrast(light["text"], light["bg"]) >= 4.5
        assert contrast(light["panel-text"], light["surface"]) >= 4.5
        assert contrast(light["on-accent-soft"], light["accent-soft"]) >= 4.5


def test_default_dashboard_view_recovers_controls_without_resetting_the_saved_design(app, editor_client):
    assert post(editor_client, PATH + "/dashboard", **{"appearance.dashboard_theme": "publication"}).status_code == 302
    assert post(editor_client, **appearance.preset_values("canvas"), **{"appearance.theme": "broadsheet", "appearance.custom_css": ".publication{display:none}"}).status_code == 302
    before = snapshot(app)
    response = editor_client.get(PATH + "?dashboard_style=default")
    assert response.status_code == 200
    assert b'<body class="dashboard">' in response.data
    assert b'css/publication.css' not in response.data and b'/theme/broadsheet/' not in response.data
    assert b'<link rel="stylesheet" href="/custom.css' not in response.data
    assert b'.publication{display:none}' in response.data  # editable textarea value
    assert b'Save publication design' in response.data
    assert snapshot(app) == before
    assert app.test_client().get(PATH + "?dashboard_style=default").status_code == 302
    assert b'designed design-canvas' in editor_client.get(PATH).data


@pytest.mark.parametrize("values", [
    {"appearance.content_width": "999999"}, {"appearance.text_color": "red;}</style>"},
    {"appearance.custom_body_font": "Georgia; background:url(https://example.test)"},
    {"appearance.heading_font": "custom", "appearance.custom_heading_font": ""},
    {"appearance.email_layout": "unknown"},
])
def test_invalid_design_does_not_partially_save_or_upload(app, editor_client, values):
    before = snapshot(app)
    response = post(editor_client, logo=(png(), "logo.png"), **values)
    assert response.status_code == 422
    assert snapshot(app) == before


def test_logos_preview_without_storage_then_save_and_remove(app, editor_client):
    before = snapshot(app)
    response = post(editor_client, PREVIEW, logo=(png(), "logo.png"), **{"appearance.brand_display": "both"})
    assert response.status_code == 200
    assert b"data:image/png;base64," in response.data
    assert snapshot(app) == before
    response = post(editor_client, **{role: (png(), role + ".png") for role in appearance.UPLOADS})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Upload)) == len(appearance.UPLOADS)
        for role in appearance.UPLOADS:
            path = app.extensions["copydesk"].config.uploads_dir / settings.get("appearance." + role)
            with Image.open(path) as image:
                assert image.convert("RGBA").getpixel((0, 0))[3] == 0
    home = editor_client.get("/").data
    assert b"logo-light" in home and b"logo-dark" in home
    assert b'<link rel="icon" href="/uploads/' in home
    assert post(editor_client, **{f"remove_{role}": "1" for role in appearance.UPLOADS}).status_code == 302
    with app.app_context():
        assert all(settings.get("appearance." + role) == "" for role in appearance.UPLOADS)


def test_email_logo_has_own_fallback(app, editor_client):
    assert post(editor_client, logo=(png(), "main.png"), email_logo=(png(), "email.png")).status_code == 302
    email = editor_client.get(PREVIEW + "?preview_format=email").data
    with app.test_request_context("/"):
        assert settings.get("appearance.email_logo").encode() in email
        assert settings.get("appearance.logo").encode() not in email


def test_wide_email_logo_preserves_aspect_ratio_in_preview_and_saved_output(app, editor_client):
    def wide():
        stream = BytesIO()
        Image.new("RGBA", (800, 50), (0, 0, 0, 0)).save(stream, "PNG")
        stream.seek(0)
        return stream

    response = post(editor_client, PREVIEW, email_logo=(wide(), "wide.png"), preview_format="email")
    assert response.status_code == 200
    assert b'width="240" height="15"' in response.data
    assert post(editor_client, email_logo=(wide(), "wide.png")).status_code == 302
    response = editor_client.get(PREVIEW + "?preview_format=email")
    assert b'width="240" height="15"' in response.data


def test_export_is_portable_and_import_rejects_non_design_settings(app, editor_client):
    with app.app_context():
        settings.set_values({"site.contact_email": "private@example.test", "appearance.logo": "private/logo.png"})
        db.session.commit()
    response = editor_client.get(PATH + "/export")
    assert response.status_code == 200
    assert b"private@example.test" not in response.data and b"private/logo.png" not in response.data
    assert response.json["format"] == "quillsail.appearance.v1"
    before = snapshot(app)
    for bad in ({"site.name": "Changed"}, {"appearance.logo": "../secret"}, {"appearance.body_size": 999}, {"appearance.style": []}):
        document = {"format": "quillsail.appearance.v1", "settings": bad}
        assert post(editor_client, action="import", design_file=(BytesIO(json.dumps(document).encode()), "bad.json")).status_code == 422
    assert snapshot(app) == before


def test_custom_css_is_not_html_and_email_imports_never_fetch(app, editor_client, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Design rendering must not fetch network resources")

    import requests
    monkeypatch.setattr(requests.sessions.Session, "get", no_network)
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    css = '@import "https://example.test/private.css"; @import "file:///etc/passwd"; .email-story { background-color:#abcdef !important; }'
    response = post(editor_client, PREVIEW, preview_format="email", **{"appearance.email_css": css})
    assert response.status_code == 200 and b"#abcdef" in response.data
    assert b"@import" not in response.data
    response = post(editor_client, PREVIEW, **{"appearance.custom_css": '</style><script id="injected">alert(1)</script>'})
    assert response.status_code == 200
    assert b'<script id="injected">' not in response.data


def test_legacy_appearance_and_partial_posts_preserve_existing_values(app, editor_client):
    with app.app_context():
        settings.set_values({"appearance.core_styles": True} | appearance.CLASSIC)
        db.session.commit()
    with app.test_request_context("/"):
        assert not appearance.design()["enabled"]
    assert post(editor_client, **{"appearance.accent_color": "#765432", "appearance.home_intro": "Welcome here"}).status_code == 302
    assert post(editor_client, **{"appearance.email_width": "720"}).status_code == 302
    with app.test_request_context("/"):
        assert settings.get("appearance.accent_color") == "#765432"
        assert settings.get("appearance.home_intro") == "Welcome here"
        assert settings.get("appearance.text_color") == "#16181d"
        assert appearance.design()["enabled"]
