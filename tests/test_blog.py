import base64
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from click.testing import CliRunner
from sqlalchemy import func, select

from copydesk import newsletter, publication, settings, workflow
from copydesk.cli import main
from copydesk.db import db
from copydesk.models import (
    Article,
    Delivery,
    Group,
    GroupMembership,
    Issue,
    IssueItem,
    User,
)
from copydesk.utils import utcnow

BODY = "A thoughtful original blog post explains a useful idea and shares examples with readers. It gives the newsletter editors enough context to decide whether to feature this work."


def mode(app, value):
    with app.app_context():
        settings.set_value("site.mode", value)
        db.session.commit()


def post(client, path, **data):
    return client.post(path, data={"csrf_token": "test-csrf", **data})


def make_post(app, user_id, title="A blog post", *, visibility="public", status="published"):
    with app.app_context():
        article = workflow.create_draft(db.session.get(User, user_id), title)
        workflow.save(article, db.session.get(User, user_id), title=title, subtitle="", body=BODY)
        article.status, article.visibility = status, visibility
        article.published_at = utcnow() if status == "published" else None
        db.session.commit()
        return article.id, article.slug


def member_client(app, *, publish=False, verified=True):
    with app.app_context():
        user = User(
            email="blogger@example.test",
            username="blogger",
            display_name="Blogger",
            email_verified_at=utcnow() if verified else None,
        )
        db.session.add(user)
        if publish:
            role = Group(slug="blog-publishers", name="Blog publishers", permissions=["publish"])
            db.session.add(role)
            db.session.flush()
            db.session.add(GroupMembership(user_id=user.id, group_id=role.id))
        db.session.commit()
        user_id, version = user.id, user.auth_version
    client = app.test_client()
    with client.session_transaction() as session:
        session["uid"], session["uv"], session["_csrf"] = user_id, version, "test-csrf"
    return client, user_id


@pytest.mark.parametrize("value", ["newsletter", "blog", "hybrid"])
def test_publication_modes_preserve_data_and_change_home_page(app, client, admin, value):
    _, slug = make_post(app, admin)
    with app.app_context():
        issue = newsletter.create(db.session.get(User, admin), "Existing newsletter")
        issue.published_at = utcnow()
        db.session.commit()
    mode(app, value)
    home = client.get("/").get_data(as_text=True)
    assert "A blog post" in home
    assert ("Latest posts" in home) == (value != "newsletter")
    assert ("Latest issue" in home) == (value == "newsletter")
    assert ("subscribe-box" in home) == (value != "blog")
    assert client.get(f"/articles/{slug}/").status_code == 200
    assert client.get("/feed.xml").status_code == 200
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Article)) == 1
        assert db.session.scalar(select(func.count()).select_from(Issue)) == 1
    mode(app, "newsletter")
    assert "Existing newsletter" in client.get("/").get_data(as_text=True)


def test_blog_owner_publishes_without_review_or_newsletter_and_can_edit(app, editor_client, admin):
    mode(app, "blog")
    with app.app_context():
        settings.set_value("submissions.enabled", False)
        db.session.commit()
    response = post(editor_client, "/write/new")
    assert response.status_code == 302
    editor = editor_client.get(response.location)
    assert b"Publish post" in editor.data and b"Submit for review</button>" not in editor.data
    response = post(
        editor_client, response.location, action="publish", title="Owner post", body=BODY
    )
    assert response.status_code == 302 and "/articles/owner-post/" in response.location
    with app.app_context():
        article = db.session.scalar(select(Article).where(Article.title == "Owner post"))
        assert article.is_published and article.submitted_at is None
        assert db.session.scalar(select(func.count()).select_from(Issue)) == 0
        assert db.session.scalar(select(func.count()).select_from(Delivery)) == 0
        article_id = article.id
    assert editor_client.get(f"/write/{article_id}/edit").status_code == 200
    assert b"Newsletter options" in editor_client.get(response.location).data


def test_regular_writer_cannot_bypass_review_with_publish_action(app, admin):
    mode(app, "blog")
    client, user_id = member_client(app)
    article_id, _ = make_post(app, user_id, status="draft")
    assert b"Publish post" not in client.get(f"/write/{article_id}/edit").data
    response = post(
        client, f"/write/{article_id}/edit", action="publish", title="Unauthorized", body=BODY
    )
    assert response.status_code == 403
    with app.app_context():
        assert db.session.get(Article, article_id).status == "draft"


def test_newsletter_mode_keeps_editorial_publish_flow(app, editor_client, admin):
    article_id, _ = make_post(app, admin, status="draft")
    assert (
        post(
            editor_client,
            f"/write/{article_id}/edit",
            action="publish",
            title="No bypass",
            body=BODY,
        ).status_code
        == 403
    )


def test_blog_publisher_role_can_edit_own_published_post_but_not_another_draft(app, admin):
    mode(app, "blog")
    client, user_id = member_client(app, publish=True)
    mine, _ = make_post(app, user_id)
    other, _ = make_post(app, admin, status="draft")
    assert client.get(f"/write/{mine}/edit").status_code == 200
    assert client.get(f"/write/{other}/edit").status_code == 404


def test_same_site_newsletter_reuses_post_and_does_not_duplicate_items(app, editor_client, admin):
    mode(app, "hybrid")
    article_id, _ = make_post(app, admin)
    page = editor_client.get(f"/write/{article_id}/newsletter")
    assert b"Add post to newsletter" in page.data
    response = post(
        editor_client, f"/write/{article_id}/newsletter", issue_id="new", display="full"
    )
    assert response.status_code == 302
    with app.app_context():
        issue = db.session.scalar(select(Issue))
        assert issue.status == "draft" and issue.items[0].article_id == article_id
        assert issue.items[0].display == "full"
        issue_id = issue.id
        assert db.session.scalar(select(func.count()).select_from(Article)) == 1
    post(
        editor_client, f"/write/{article_id}/newsletter", issue_id=str(issue_id), display="summary"
    )
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(IssueItem)) == 1
        issue = db.session.get(Issue, issue_id)
        _, html, text = newsletter.render(issue)
        assert "A blog post" in html and "A blog post" in text
        assert db.session.scalar(select(func.count()).select_from(Delivery)) == 0
        issue.status = "sent"
        db.session.commit()
    response = post(editor_client, f"/write/{article_id}/newsletter", issue_id=str(issue_id))
    assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(IssueItem)) == 1


def test_blog_only_requires_enabling_newsletter_and_authors_need_issue_permission(
    app, editor_client, admin
):
    mode(app, "blog")
    article_id, _ = make_post(app, admin)
    assert (
        b"Enable <strong>Blog + newsletter"
        in editor_client.get(f"/write/{article_id}/newsletter").data
    )
    assert post(editor_client, f"/write/{article_id}/newsletter", issue_id="new").status_code == 403
    client, user_id = member_client(app)
    own_id, _ = make_post(app, user_id)
    mode(app, "hybrid")
    assert client.get(f"/write/{own_id}/newsletter").status_code == 200
    assert post(client, f"/write/{own_id}/newsletter", issue_id="new").status_code == 403
    assert client.get(f"/write/{article_id}/newsletter").status_code == 404


def test_external_newsletter_link_uses_subpath_and_public_metadata_only(app, editor_client, admin):
    mode(app, "blog")
    article_id, slug = make_post(app, admin)
    with app.app_context():
        settings.set_value("blog.newsletter_url", "https://newsletter.example.test/community/")
        db.session.commit()
        article = db.session.get(Article, article_id)
        target = urlsplit(publication.external_submission_url(article))
        assert target.hostname == "newsletter.example.test"
        assert target.path == "/community/write/from-blog"
        query = parse_qs(target.query)
        assert query["source"][0].endswith("/articles/" + slug + "/")
        assert query["title"] == ["A blog post"] and len(query["excerpt"][0]) <= 400
        assert "email" not in query and "token" not in query
        transfer = json.loads(base64.urlsafe_b64decode(target.fragment.removeprefix("quillsail=")))
        assert transfer == {
            "version": 1, "source": query["source"][0], "body": BODY, "body_format": "markdown",
        }
        assert "body" not in query
        article.visibility = "members"
        db.session.commit()
        assert publication.external_submission_url(article) == ""
    assert (
        b"Only public posts can be offered"
        in editor_client.get(f"/write/{article_id}/newsletter").data
    )


def submission(client, **changes):
    return post(
        client,
        "/write/from-blog",
        **{
            "title": "Offered blog post",
            "source_url": "https://blog.example.test/original",
            "source_author": "Original Author",
            "body": BODY,
            "permission": "1",
            **changes,
        },
    )


def test_external_post_goes_through_review_preserves_credit_and_never_fetches_url(
    app, editor_client, monkeypatch
):
    client = app.test_client()
    writer, user_id = member_client(app)
    import requests

    monkeypatch.setattr(
        requests, "get", lambda *a, **kw: pytest.fail("Blog submissions must not fetch remote URLs")
    )
    landing = writer.get(
        "/write/from-blog?source=https://blog.example.test/original&title=Prefilled&excerpt=An%20excerpt&author=Source"
    )
    assert landing.status_code == 200 and b"Prefilled" in landing.data
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Article)) == 0
    response = submission(writer)
    assert response.status_code == 302
    with app.app_context():
        article = db.session.scalar(select(Article))
        assert article.status == "submitted" and not article.is_published
        assert article.source_url == "https://blog.example.test/original"
        assert article.source_author == "Original Author"
        assert article.has_author(db.session.get(User, user_id))
        article_id, slug = article.id, article.slug
        assert db.session.scalar(select(func.count()).select_from(Issue)) == 0
    assert client.get(f"/articles/{slug}/").status_code == 404
    assert (
        b"Review the original post" in editor_client.get(f"/dashboard/articles/{article_id}/").data
    )
    assert submission(writer).status_code == 302
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Article)) == 1
        article = db.session.get(Article, article_id)
        admin_user = db.session.scalar(select(User).where(User.email == "editor@example.edu"))
        workflow.transition(article, "publish", admin_user)
        issue = newsletter.create(admin_user)
        newsletter.add_article(issue, article)
        db.session.commit()
        _, html, text = newsletter.render(issue)
        assert article.source_url in html and article.source_url in text
        assert "Original Author" in html and "Original Author" in text
    published = client.get(f"/articles/{slug}/").get_data(as_text=True)
    assert "Original Author" in published and "Read the original blog post" in published
    exported = writer.get("/account/export").get_json()
    assert exported["articles"][0]["source_url"] == "https://blog.example.test/original"


@pytest.mark.parametrize(
    "changes",
    [
        {"source_url": "javascript:alert(1)"},
        {"source_url": "https://user:password@example.test/post"},
        {"body": "Too short"},
        {"permission": ""},
        {"title": ""},
    ],
)
def test_bad_external_submissions_do_not_create_articles(app, changes):
    writer, _ = member_client(app)
    assert submission(writer, **changes).status_code == 422
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Article)) == 0


def test_external_submissions_respect_verification_csrf_and_closed_submissions(app, editor_client):
    writer, _ = member_client(app)
    assert writer.post("/write/from-blog", data={"title": "CSRF"}).status_code == 400
    with app.app_context():
        settings.set_value("submissions.enabled", False)
        db.session.commit()
    assert submission(writer).status_code == 302
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Article)) == 0
        user = db.session.scalar(select(User).where(User.username == 'blogger'))
        user.email_verified_at = None
        db.session.commit()
    landing = writer.get('/write/from-blog')
    assert landing.status_code == 200 and b'data-blog-transfer' in landing.data
    assert b'Confirm your email' in landing.data
    assert submission(writer).location.endswith('/verify-email')


def test_host_can_choose_mode_and_external_newsletter_settings(app, editor_client):
    fields = {}
    with app.app_context():
        for definition in settings.for_tab("general"):
            fields[definition.key] = settings.get(definition.key)
    fields["site.mode"] = "hybrid"
    fields["blog.newsletter_url"] = "https://newsletter.example.test/newsletter"
    response = post(editor_client, "/dashboard/settings/", **fields)
    assert response.status_code == 302
    with app.app_context():
        assert settings.get("site.mode") == "hybrid"
    fields["blog.newsletter_url"] = "https://user:secret@example.test/path"
    assert post(editor_client, "/dashboard/settings/", **fields).status_code == 422


def test_cli_initialization_supports_blog_mode(tmp_path):
    site = tmp_path / "blog"
    result = CliRunner().invoke(
        main,
        [
            "init",
            "--dir",
            str(site),
            "--mode",
            "blog",
            "--site-name",
            "My Blog",
            "--base-url",
            "http://localhost:5055",
            "--admin-name",
            "Owner",
            "--admin-email",
            "owner@example.test",
            "--admin-password",
            "correct-horse-battery-123",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    from copydesk.app import create_app
    from copydesk.config import load_config

    app = create_app(load_config(site / "copydesk.toml"))
    with app.app_context():
        assert settings.get("site.mode") == "blog"
    assert b"Latest posts" in app.test_client().get("/").data


def test_creator_blurb_is_separate_reviewed_private_and_exported(app, editor_client):
    writer, _ = member_client(app)
    blurb = "A creator-selected passage for newsletter readers."
    response = submission(writer, newsletter_blurb=blurb)
    assert response.status_code == 302
    with app.app_context():
        article = db.session.scalar(select(Article))
        assert article.body == BODY and article.newsletter_blurb == blurb
        assert article.status == "submitted" and not article.is_published
        article_id, slug = article.id, article.slug
    assert app.test_client().get(f"/articles/{slug}/").status_code == 404
    assert app.test_client().get(f"/api/v1/articles/{slug}").status_code == 404
    assert blurb in editor_client.get(f"/dashboard/articles/{article_id}/").get_data(as_text=True)
    exported = writer.get("/account/export").get_json()["articles"][0]
    assert exported["body"] == BODY and exported["newsletter_blurb"] == blurb
    # Editors use their own per-issue custom summary; they cannot overwrite the
    # text attributed to the creator by forging the writer's edit field.
    post(editor_client, f"/write/{article_id}/edit", title="Edited", body=BODY,
         newsletter_blurb="Not the creator's words")
    with app.app_context():
        assert db.session.get(Article, article_id).newsletter_blurb == blurb
        article = db.session.get(Article, article_id)
        article.status = "changes_requested"
        db.session.commit()
    assert b'Your newsletter blurb' in writer.get(f"/write/{article_id}/edit").data
    assert post(writer, f"/write/{article_id}/edit", title="Edited", body=BODY,
                newsletter_blurb="Revised by the creator").status_code == 302
    with app.app_context():
        assert db.session.get(Article, article_id).newsletter_blurb == "Revised by the creator"


def test_blurb_length_and_submission_confirmation_are_validated(app):
    writer, _ = member_client(app)
    for changes in ({"newsletter_blurb": "x" * 5001}, {"permission": ""}):
        response = submission(writer, **changes)
        assert response.status_code == 422
        assert BODY.encode() in response.data
        assert b'data-transfer-fill' not in response.data
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Article)) == 0


@pytest.mark.parametrize("display", ["full", "blurb", "summary"])
def test_editor_selects_full_creator_or_custom_text_per_issue(app, editor_client, display):
    writer, _ = member_client(app)
    submission(writer, newsletter_blurb="The creator's chosen blurb.")
    with app.app_context():
        article = db.session.scalar(select(Article))
        article.status, article.published_at = "published", utcnow()
        article.excerpt = "The usual article summary."
        admin = db.session.scalar(select(User).where(User.email == "editor@example.edu"))
        issue = newsletter.create(admin)
        entry = newsletter.add_article(issue, article)
        db.session.commit()
        issue_id, item_id, article_id = issue.id, entry.id, article.id
    path = f"/dashboard/issues/{issue_id}/items/{item_id}"
    assert writer.post(path, data={"csrf_token": "test-csrf", "display": display}).status_code == 403
    assert editor_client.post(path, data={"display": display}).status_code == 400
    assert post(editor_client, path, display=display, body="The editor's custom summary.").status_code == 302
    with app.app_context():
        issue = db.session.get(Issue, issue_id)
        entry = issue.items[0]
        assert entry.display == display
        assert db.session.get(Article, article_id).body == BODY
        _, html, plain = newsletter.render(issue)
        web = newsletter.prepare_items(issue, "#6E4CC2", email=False)[0]
        expected = {"full": BODY, "blurb": "The creator's chosen blurb.",
                    "summary": "The editor's custom summary."}[display]
        assert expected in plain
        # Typography can change apostrophes in Markdown; use distinctive text.
        assert ("useful idea" in html) == (display == "full")
        assert ("chosen blurb" in html) == (display == "blurb")
        assert ("custom summary" in html) == (display == "summary")
        assert (web.text if display == "full" else web.summary) == expected
        assert article_id == entry.article_id
        assert "blog.example.test/original" in html and "blog.example.test/original" in plain
        assert "Original Author" in html and "Original Author" in plain
        if display == "blurb":
            entry.article.newsletter_blurb = ""
            assert any("no creator blurb" in problem for problem in newsletter.problems(issue))


def test_invalid_blurb_choice_does_not_modify_item_and_restricted_body_stays_private(
    app, editor_client, admin
):
    article_id, _ = make_post(app, admin, visibility="members")
    with app.app_context():
        article = db.session.get(Article, article_id)
        article.excerpt = "An intentional public summary."
        issue = newsletter.create(db.session.get(User, admin))
        entry = newsletter.add_article(issue, article)
        entry.body = "Existing custom summary."
        db.session.commit()
        issue_id, item_id = issue.id, entry.id
    path = f"/dashboard/issues/{issue_id}/items/{item_id}"
    for display in ("blurb", "unknown"):
        post(editor_client, path, display=display, body="Should not be saved")
        with app.app_context():
            item = db.session.get(IssueItem, item_id)
            assert item.display == "summary" and item.body == "Existing custom summary."
    post(editor_client, path, display="full", body="Safe public introduction.")
    with app.app_context():
        issue = db.session.get(Issue, issue_id)
        _, html, plain = newsletter.render(issue)
        assert BODY not in plain and "useful idea" not in html
        assert "Safe public introduction." in html and "Safe public introduction." in plain


def test_full_transfer_preserves_unicode_and_blocks_drafts(app):
    with app.app_context():
        settings.set_value("blog.newsletter_url", "https://newsletter.example.test/nested/")
        # Exercise the browser payload limit independently of database TEXT
        # byte limits (MariaDB's existing body column holds 64 KiB).
        article = Article(
            slug="unicode-post", title="Unicode post", body="مرحبا 🌊 café " * 10000,
            status="published", published_at=utcnow(), visibility="public",
        )
        transfer_url = publication.external_submission_url(article)
        url = urlsplit(transfer_url)
        data = json.loads(base64.urlsafe_b64decode(url.fragment.removeprefix("quillsail=")))
        assert data["body"] == article.body
        assert url.path == "/nested/write/from-blog"
        assert len(transfer_url) < 1100000
        article.status = "draft"
        assert publication.external_submission_url(article) == ""


def test_upgrade_adds_empty_blurbs_without_changing_existing_articles(tmp_path):
    from sqlalchemy import create_engine, text

    from copydesk import migrate

    engine = create_engine(f"sqlite:///{tmp_path}/upgrade-blurb.db")
    try:
        migrate.upgrade(engine, "0005")
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO articles (slug, title, body, subtitle, excerpt, cover_image,
                    cover_alt, status, visibility, author_note, featured, word_count,
                    created_at, updated_at)
                VALUES ('kept', 'Existing article', 'Original body', '', '', '', '',
                    'accepted', 'public', '', 0, 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """))
        migrate.upgrade(engine)
        with engine.connect() as connection:
            row = connection.execute(text("SELECT title, body, newsletter_blurb FROM articles WHERE slug = 'kept'")).one()
        assert tuple(row) == ("Existing article", "Original body", "")
        assert migrate.current_revision(engine) == migrate.head_revision()
    finally:
        engine.dispose()


def test_transferred_relative_links_and_images_resolve_to_original_site(app):
    from copydesk.text import render_markdown

    with app.app_context():
        html = str(render_markdown(
            "![Chart](/uploads/chart.png) [Other post](../next/) [Jump](#section) <script>alert(1)</script>",
            base_url="https://blog.example.test/articles/post/",
        ))
    assert 'src="https://blog.example.test/uploads/chart.png"' in html
    assert 'href="https://blog.example.test/articles/next/"' in html
    assert 'href="#section"' in html
    assert '<script>' not in html
