"""Article bodies in Markdown, HTML and Markdown with HTML: rendering, safety and every read path."""

import re
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from copydesk import issue_previews, migrate, newsletter, text, workflow
from copydesk.db import db, make_engine
from copydesk.models import Article, ArticleRevision, User
from test_security_boundaries import make_user

CSRF = {"X-CSRF-Token": "test-csrf"}

EVERY_FEATURE = """## A heading

Some **bold**, *italic*, ~~struck~~ and `code` text with a [link](https://example.com "Title"),
an address https://example.org and a note[^1].

- one
- [x] done
- [ ] to do

1. first
2. second

> A quotation.

::: tip Worth knowing
Inside a box.
:::

| Left | Right |
|:-----|------:|
| a    | b     |

```python
print("hello")
```

![A picture](/uploads/a.png "Caption")

---

[^1]: The note.
"""


def make_article(app, user_id, body, body_format="markdown", **fields):
    with app.app_context():
        user = db.session.get(User, user_id)
        article = workflow.create_draft(user, fields.pop("title", "A piece"))
        workflow.save(article, user, title=article.title, subtitle="", body=body, body_format=body_format)
        for key, value in fields.items():
            setattr(article, key, value)
        db.session.commit()
        return article.id


def publish(app, article_id):
    with app.app_context():
        article = db.session.get(Article, article_id)
        workflow.publish(article, None)
        db.session.commit()
        return article.slug


# ----------------------------------------------------------------------- rendering


def test_markdown_format_renders_exactly_as_before(app):
    with app.app_context():
        assert text.render_source(EVERY_FEATURE, "markdown") == text.render_markdown(EVERY_FEATURE)
        assert text.render_source("<b>hi</b>", "markdown") == text.render_markdown("<b>hi</b>")
        assert "&lt;b&gt;" in text.render_source("<b>hi</b>", "markdown")


def test_markdown_with_html_matches_markdown_when_no_html_is_typed(app):
    with app.app_context():
        assert text.render_source(EVERY_FEATURE, "markdown_html") == text.render_markdown(EVERY_FEATURE)


def test_html_format_skips_markdown(app):
    with app.app_context():
        html = text.render_source("<p>**not bold**</p>\n\n# not a heading", "html")
    assert "<strong>" not in html and "<h1>" not in html and "**not bold**" in html


def test_markdown_with_html_mixes_both(app):
    with app.app_context():
        html = text.render_source("**bold**\n\n<details><summary>More</summary>\n\nHidden *text*\n\n</details>\n",
                                  "markdown_html")
    assert "<strong>bold</strong>" in html
    assert "<details><summary>More</summary>" in html and "<em>text</em>" in html


@pytest.mark.parametrize("body_format", ["html", "markdown_html"])
@pytest.mark.parametrize(("attack", "banned"), [
    ("<script>alert(1)</script>", "alert(1)"),
    ("<style>body{display:none}</style>", "display:none"),
    ('<img src="x" onerror="alert(1)">', "onerror"),
    ('<p onclick="alert(1)">x</p>', "onclick"),
    ('<p style="position:fixed;inset:0">x</p>', "position:fixed"),
    ('<a href="javascript:alert(1)">x</a>', "javascript:"),
    ('<a href=" java\nscript:alert(1)">x</a>', "alert(1)"),
    ('<a href="data:text/html,<script>1</script>">x</a>', "data:"),
    ('<img src="javascript:alert(1)">', "javascript:"),
    ('<video src="javascript:alert(1)" poster="javascript:alert(2)"></video>', "javascript:"),
    ('<form action="/login"><input name="password"><button>Sign in</button></form>', "<form"),
    ('<form action="/login"><input name="password"></form>', 'name="password"'),
    ('<iframe src="https://evil.example/login"></iframe>', "evil.example"),
    ('<iframe srcdoc="<script>alert(1)</script>"></iframe>', "srcdoc"),
    ('<iframe src="https://www.youtube.com/embed/abcdefgh"><img src=x onerror=alert(1)></iframe>', "onerror"),
    ('<object data="/x"></object><embed src="/x">', "<object"),
    ('<svg onload="alert(1)"><script>alert(1)</script></svg>', "alert(1)"),
    ('<math><mtext><script>alert(1)</script></mtext></math>', "alert(1)"),
    ('<base href="https://evil.example/">', "<base"),
    ('<meta http-equiv="refresh" content="0;url=https://evil.example">', "<meta"),
    ('<link rel="stylesheet" href="https://evil.example/x.css">', "<link"),
    ('<video src="https://example.com/a.mp4" autoplay onplay="alert(1)"></video>', "onplay"),
    ('<video src="https://example.com/a.mp4" autoplay></video>', "autoplay"),
    ('<noscript><img src=x onerror=alert(1)></noscript>', "<img"),
    ('<svg><style><img src=x onerror=alert(1)></style></svg>', "onerror="),
])
def test_typed_html_cannot_run_or_restyle(app, attack, banned, body_format):
    with app.app_context():
        assert banned not in text.render_source(attack, body_format)


@pytest.mark.parametrize("markup", [
    '<div class="alert alert-error">Your account is locked</div>',
    '<a class="button button-primary" href="/login">Sign in</a>',
    '<span class="visually-hidden">x</span>',
    '<p class="flashes">x</p>',
    '<aside class="panel card">x</aside>',
])
def test_typed_html_cannot_reuse_site_interface_classes(app, markup):
    with app.app_context():
        assert "class=" not in text.render_source(markup, "html")


def test_typed_html_keeps_only_content_ids(app):
    with app.app_context():
        html = text.render_source('<h2 id="plans">x</h2><div id="main">y</div><p id="f-email">z</p>', "html")
    assert 'id="plans"' in html
    assert 'id="main"' not in html and 'id="f-email"' not in html


def test_typed_inputs_are_only_ever_inert_checkboxes(app):
    with app.app_context():
        html = str(text.render_source('<input><input type="password" value="x"><input type="checkbox" checked>', "html"))
    assert html.count('type="checkbox"') == 3 and html.count('disabled="disabled"') == 3
    assert "password" not in html and "value=" not in html


def test_safe_html_survives(app):
    source = (
        '<h2 id="top">Title</h2><p>Some <mark>marked</mark> <kbd>Ctrl</kbd> <small>small</small></p>'
        '<details open><summary>More</summary><p>Inside</p></details>'
        '<figure><img src="https://example.com/a.png" alt="A" width="640" height="480">'
        "<figcaption>Caption</figcaption></figure>"
        '<table><caption>T</caption><tr><th scope="col" colspan="2">H</th></tr></table>'
        '<aside class="callout callout-tip"><p class="callout-title">Tip</p><p>x</p></aside>'
    )
    with app.app_context():
        html = str(text.render_source(source, "html"))
    for piece in ("<mark>", "<kbd>", "<small>", "<details open", "<summary>", 'width="640"',
                  "<figcaption>", "<caption>", 'colspan="2"', 'class="callout callout-tip"'):
        assert piece in html


def test_oversized_dimensions_are_dropped(app):
    with app.app_context():
        html = text.render_source('<img src="/a.png" alt="" width="99999" height="100%">', "html")
    assert "width=" not in html and "height=" not in html


def test_media_keeps_controls_and_cannot_autoplay(app):
    with app.app_context():
        html = str(text.render_source(
            '<video src="https://example.com/a.mp4" autoplay muted></video>'
            '<audio src="https://example.com/a.mp3" autoplay></audio>', "html"))
    assert html.count('controls="controls"') == 2 and "autoplay" not in html


@pytest.mark.parametrize(("source", "expected"), [
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
    ("https://youtube.com/embed/dQw4w9WgXcQ?start=30&autoplay=1", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?start=30"),
    ("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
    ("https://player.vimeo.com/video/12345", "https://player.vimeo.com/video/12345"),
])
def test_approved_embeds_are_framed_in_a_sandbox(app, source, expected):
    with app.app_context():
        html = str(text.render_source(f'<iframe src="{source}" title="A video"></iframe>', "html"))
    assert f'src="{expected}"'.replace("&", "&amp;") in html
    assert 'sandbox="allow-same-origin allow-scripts allow-presentation allow-popups"' in html
    assert 'title="A video"' in html and html.endswith("</iframe>")


@pytest.mark.parametrize("source", [
    "http://www.youtube.com/embed/dQw4w9WgXcQ",
    "https://www.youtube.com.evil.example/embed/dQw4w9WgXcQ",
    "https://evil.example/www.youtube.com/embed/dQw4w9WgXcQ",
    "https://www.youtube.com@evil.example/embed/dQw4w9WgXcQ",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://player.vimeo.com/video/abc",
    "https://www.youtube.com:8443/embed/dQw4w9WgXcQ",
    "/dashboard/",
    "javascript:alert(1)",
])
def test_other_frames_are_removed_entirely(app, source):
    with app.app_context():
        assert "<iframe" not in text.render_source(f'<iframe src="{source}"></iframe><p>after</p>', "html")


def test_every_embed_host_is_allowed_by_the_content_security_policy(app):
    with app.test_request_context("/"):
        from copydesk.security import default_csp

        policy = default_csp()
    frames = next(part for part in policy.split(";") if part.strip().startswith("frame-src"))
    for host in text.EMBED_HOSTS:
        assert host in frames
    assert "https:" not in frames.replace("https://www.youtube-nocookie.com", "").replace("https://player.vimeo.com", "")


def test_base_url_resolves_links_in_every_format(app):
    with app.app_context():
        for body, body_format in (("[a](/x)", "markdown"), ('<a href="/x">a</a>', "html"),
                                  ('<a href="/x">a</a>', "markdown_html")):
            assert 'href="https://blog.example/x"' in text.render_source(
                body, body_format, base_url="https://blog.example/post/")


def test_extension_filter_runs_for_every_format(app):
    with app.app_context():
        app.extensions["copydesk"].hooks.add_filter("markdown.html", lambda html: html + "<!--seen-->")
        for body_format in text.BODY_FORMATS:
            assert text.render_source("x", body_format).endswith("<!--seen-->")


# ------------------------------------------------------------------- word counts and excerpts


def test_word_count_ignores_tags(app):
    with app.app_context():
        assert text.source_word_count('<p class="x" data-long-attribute="a b c">one two</p><p>three</p>', "html") == 3
        assert text.source_word_count("<p>one</p><p>two</p>", "markdown_html") == 2
        # Markdown keeps counting the way it always has.
        assert text.source_word_count("one **two** three", "markdown") == 3


def test_saving_counts_words_for_the_format(app, admin):
    article_id = make_article(app, admin, '<div class="ignored"><p>one two three</p></div>', "html")
    with app.app_context():
        assert db.session.get(Article, article_id).word_count == 3


def test_submitting_html_needs_real_words(app, admin):
    article_id = make_article(app, admin, "<p>" + "<b></b>" * 40 + "</p>", "html")
    with app.app_context():
        article = db.session.get(Article, article_id)
        with pytest.raises(workflow.WorkflowError, match="much here"):
            workflow.transition(article, "submit", db.session.get(User, admin))


def test_excerpts_use_the_format(app, admin):
    article_id = make_article(app, admin, "<div>Lead text <b>bold</b></div><p>A paragraph.</p>", "html")
    with app.app_context():
        article = db.session.get(Article, article_id)
        assert text.body_excerpt(article) == "A paragraph."
        assert article.summary == "A paragraph."
        assert text.source_excerpt("<div>No paragraphs <b>here</b></div>", "html") == "No paragraphs here"
        assert text.source_excerpt("**Hello**", "markdown") == "Hello"


def test_plain_text_keeps_structure_and_link_addresses(app):
    plain = text.html_to_plain(
        '<h2>Title</h2><p>Read <a href="https://example.com">this</a> &amp; that.</p>'
        "<ul><li>one</li><li>two</li></ul><pre><code>a  b\nc</code></pre>"
        '<table><tr><th>H1</th><th>H2</th></tr><tr><td>a</td><td>b</td></tr></table>'
        '<p>Note<a href="#fn1">1</a></p>'
    )
    assert "Title\n\nRead this (https://example.com) & that." in plain
    assert "- one\n- two" in plain and "a  b\nc" in plain
    assert "H1 | H2\na | b" in plain and "#fn1" not in plain


# --------------------------------------------------------------------------- every read path

HTML_BODY = '<p>Hello <b>there</b> <mark>reader</mark>.</p><details><summary>More</summary><p>Inside.</p></details>'


def test_public_article_renders_the_format(app, client, admin):
    slug = publish(app, make_article(app, admin, HTML_BODY, "html"))
    page = client.get(f"/articles/{slug}/").data.decode()
    assert "<mark>reader</mark>" in page and "<details>" in page and "&lt;mark&gt;" not in page


def test_review_and_status_pages_render_the_format(app, editor_client, admin):
    article_id = make_article(app, admin, HTML_BODY, "html")
    assert "<mark>reader</mark>" in editor_client.get(f"/write/{article_id}/").data.decode()
    with app.app_context():
        article = db.session.get(Article, article_id)
        article.status = "submitted"
        db.session.commit()
    assert "<mark>reader</mark>" in editor_client.get(f"/dashboard/articles/{article_id}/").data.decode()


def test_feed_renders_the_format(app, client, admin):
    publish(app, make_article(app, admin, HTML_BODY, "html", title="Html"))
    publish(app, make_article(app, admin, "**bold**", "markdown", title="Md"))
    feed = client.get("/feed.xml").data.decode()
    assert "&lt;mark&gt;reader&lt;/mark&gt;" in feed
    assert "&lt;strong&gt;bold&lt;/strong&gt;" in feed
    assert "&amp;lt;mark" not in feed


def test_issue_feed_still_renders_its_markdown_intro(app, client, admin):
    with app.app_context():
        issue = newsletter.create(db.session.get(User, admin))
        issue.intro, issue.status, issue.published_at = "An **intro**", "published", datetime(2026, 1, 1)
        db.session.commit()
    assert "&lt;strong&gt;intro&lt;/strong&gt;" in client.get("/issues/feed.xml").data.decode()


def test_api_reports_the_format_and_source(app, client, admin):
    html_slug = publish(app, make_article(app, admin, HTML_BODY, "html", title="Html one"))
    md_slug = publish(app, make_article(app, admin, "**bold**", "markdown", title="Md one"))
    html_item = client.get(f"/api/v1/articles/{html_slug}").get_json()
    md_item = client.get(f"/api/v1/articles/{md_slug}").get_json()
    html_item, md_item = html_item.get("article", html_item), md_item.get("article", md_item)
    assert html_item["body_format"] == "html" and html_item["source"] == HTML_BODY
    assert "<mark>reader</mark>" in html_item["html"] and html_item["markdown"] is None
    assert md_item["body_format"] == "markdown" and md_item["markdown"] == "**bold**"


@pytest.mark.parametrize("body_format", ["html", "markdown_html"])
def test_newsletter_gets_html_and_readable_text(app, admin, body_format):
    body = HTML_BODY + (
        '<video src="https://example.com/a.mp4">Your browser can\'t play this.</video>'
        '<video><source src="https://example.com/b.mp4"></video>'
        '<audio src="https://example.com/a.mp3"></audio>'
        '<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ" title="Clip"></iframe>'
        '<iframe src="https://player.vimeo.com/video/12345"></iframe>'
    )
    if body_format == "markdown_html":
        body = re.sub(r"(<(?:details|video|audio|iframe))", r"\n\n\1", body)
    article_id = make_article(app, admin, body, body_format)
    publish(app, article_id)
    with app.app_context():
        issue = newsletter.create(db.session.get(User, admin))
        entry = newsletter.add_article(issue, db.session.get(Article, article_id))
        entry.display = "full"
        db.session.commit()
        _subject, html, plain = newsletter.render(issue, audience_ids=set())
    # Email apps can't play media or fold a section, so readers get links and the open text.
    for tag in ("<video", "<audio", "<iframe", "<details", "<summary", "<source"):
        assert tag not in html
    assert "can't play this" not in html
    assert 'href="https://example.com/a.mp4"' in html and 'href="https://example.com/b.mp4"' in html
    assert 'href="https://example.com/a.mp3"' in html
    assert 'href="https://www.youtube.com/watch?v=dQw4w9WgXcQ"' in html
    assert 'href="https://vimeo.com/12345"' in html
    assert "More" in html and "Inside." in html
    # The plain-text part reads as text, not as markup.
    assert "<p>" not in plain and "<mark>" not in plain
    assert "Hello there reader." in plain and "Inside." in plain
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in plain


def test_markdown_newsletter_text_is_unchanged(app, admin):
    article_id = make_article(app, admin, "A **bold** word.")
    publish(app, article_id)
    with app.app_context():
        issue = newsletter.create(db.session.get(User, admin))
        entry = newsletter.add_article(issue, db.session.get(Article, article_id))
        entry.display = "full"
        db.session.commit()
        _subject, html, plain = newsletter.render(issue, audience_ids=set())
    assert "A **bold** word." in plain and "<strong" in html


def test_issue_previews_render_unpublished_html(app, admin):
    article_id = make_article(app, admin, HTML_BODY, "html")
    with app.app_context():
        issue = newsletter.create(db.session.get(User, admin))
        newsletter.add_article(issue, db.session.get(Article, article_id))
        db.session.commit()
        item = next(i for i in issue_previews.public_items(issue, "#000000") if i.article)
    assert "<mark>reader</mark>" in item.web_html and "<mark>" not in item.text


def test_submission_email_excerpt_uses_the_format(app, admin):
    from copydesk import mail
    from copydesk.jobs import run_pending

    with app.app_context():
        writer_id = make_user(email="writer@example.edu", username="writer", permissions=("submit",))
    article_id = make_article(app, writer_id, "<p>" + "plain words " * 15 + "<mark>end</mark></p>", "html")
    with app.app_context():
        workflow.transition(db.session.get(Article, article_id), "submit", db.session.get(User, writer_id))
        db.session.commit()
        run_pending()
    assert mail.outbox
    bodies = [message.get_body(preferencelist=(kind,)).get_content()
              for message in mail.outbox for kind in ("html", "plain")]
    assert any("plain words" in body for body in bodies)
    assert not any("&lt;p&gt;" in body or "<mark>" in body for body in bodies)


def test_account_export_includes_the_format(app, editor_client, admin):
    make_article(app, admin, HTML_BODY, "html")
    response = editor_client.get("/account/export")
    if response.status_code == 405:
        response = editor_client.post("/account/export", headers=CSRF)
    assert response.get_json()["articles"][0]["body_format"] == "html"


# ----------------------------------------------------------------- the editor and revisions


def post_edit(client, article_id, **fields):
    data = {"csrf_token": "test-csrf", "title": "A piece", "subtitle": "", "action": "save", **fields}
    return client.post(f"/write/{article_id}/edit", data=data)


def test_editor_saves_the_chosen_format(app, editor_client, admin):
    article_id = make_article(app, admin, "**old**")
    assert post_edit(editor_client, article_id, body=HTML_BODY, body_format="html").status_code == 302
    with app.app_context():
        article = db.session.get(Article, article_id)
        assert (article.body, article.body_format) == (HTML_BODY, "html")
        assert workflow.revisions(article)[0].body_format == "html"


def test_saving_without_a_format_keeps_the_current_one(app, editor_client, admin):
    article_id = make_article(app, admin, HTML_BODY, "html")
    assert post_edit(editor_client, article_id, body="<p>new</p>").status_code == 302
    with app.app_context():
        assert db.session.get(Article, article_id).body_format == "html"


def test_editor_rejects_an_unknown_format(app, editor_client, admin):
    article_id = make_article(app, admin, "text")
    response = post_edit(editor_client, article_id, body="x", body_format="javascript")
    assert response.status_code == 422
    with app.app_context():
        assert db.session.get(Article, article_id).body == "text"


def test_changing_only_the_format_keeps_a_revision(app, editor_client, admin):
    article_id = make_article(app, admin, "<b>same</b>")
    assert post_edit(editor_client, article_id, body="<b>same</b>", body_format="html").status_code == 302
    with app.app_context():
        rows = workflow.revisions(db.session.get(Article, article_id))
        assert [r.body_format for r in rows] == ["html", "markdown"]
    page = editor_client.get(f"/write/{article_id}/history/{rows[0].id}").data.decode()
    assert "changed the format from Markdown to HTML" in page


def test_restoring_a_revision_restores_its_format(app, editor_client, admin):
    article_id = make_article(app, admin, "**markdown**")
    post_edit(editor_client, article_id, body=HTML_BODY, body_format="html")
    with app.app_context():
        first = workflow.revisions(db.session.get(Article, article_id))[-1].id
    response = editor_client.post(f"/write/{article_id}/history/{first}/restore", data={"csrf_token": "test-csrf"})
    assert response.status_code == 302
    with app.app_context():
        article = db.session.get(Article, article_id)
        assert (article.body, article.body_format) == ("**markdown**", "markdown")
        assert workflow.revisions(article)[0].body_format == "markdown"


def test_preview_uses_the_format(editor_client):
    response = editor_client.post("/write/preview", json={"body": "<mark>x</mark>", "body_format": "html"}, headers=CSRF)
    assert "<mark>x</mark>" in response.get_json()["html"]
    response = editor_client.post("/write/preview", json={"body": "<mark>x</mark>"}, headers=CSRF)
    assert "&lt;mark&gt;" in response.get_json()["html"]
    response = editor_client.post("/write/preview", json={"body": "x", "body_format": "nope"}, headers=CSRF)
    assert response.status_code == 400


def test_no_javascript_preview_uses_the_posted_format(app, editor_client, admin):
    article_id = make_article(app, admin, "text")
    page = post_edit(editor_client, article_id, body="<mark>x</mark>", body_format="html", action="preview")
    assert b"<mark>x</mark>" in page.data
    with app.app_context():
        assert db.session.get(Article, article_id).body == "text"


def test_blog_handoff_keeps_the_format(app, editor_client, admin):
    words = "<p>" + "word " * 25 + "</p>"
    response = editor_client.post("/write/from-blog", data={
        "csrf_token": "test-csrf", "source_url": "https://blog.example/post", "title": "From a blog",
        "source_author": "A writer", "body": words, "body_format": "html", "permission": "1",
    })
    assert response.status_code == 302
    with app.app_context():
        article = db.session.scalar(select(Article).where(Article.source_url == "https://blog.example/post"))
        assert article.body_format == "html" and article.word_count == 25


# ------------------------------------------------------------------------------ migration


def test_upgrade_keeps_existing_articles_as_markdown(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/upgrade.db")
    now = datetime(2026, 1, 1)
    try:
        migrate.upgrade(engine, "0008")
        with engine.begin() as connection:
            metadata = sa.MetaData()
            metadata.reflect(connection)
            connection.execute(metadata.tables["articles"].insert(), {
                "id": 1, "slug": "old", "title": "Old", "source_url": "", "source_author": "",
                "newsletter_blurb": "", "subtitle": "", "body": "**old** <b>text</b>", "excerpt": "",
                "cover_image": "", "cover_alt": "", "status": "published", "visibility": "public",
                "author_note": "", "featured": False, "word_count": 3, "created_at": now, "updated_at": now,
            })
            connection.execute(metadata.tables["article_revisions"].insert(), {
                "id": 1, "article_id": 1, "created_at": now, "title": "Old", "subtitle": "",
                "body": "**old** <b>text</b>", "summary": "", "word_count": 3,
            })
        migrate.upgrade(engine)
        with engine.connect() as connection:
            assert connection.execute(sa.text("SELECT body, body_format FROM articles")).one() == (
                "**old** <b>text</b>", "markdown")
            assert connection.execute(sa.text("SELECT body_format FROM article_revisions")).scalar() == "markdown"
            assert connection.execute(sa.text("SELECT COUNT(*) FROM article_redirects")).scalar() == 0
    finally:
        engine.dispose()


def test_migration_downgrades_cleanly(tmp_path):
    from alembic import command

    engine = make_engine(f"sqlite:///{tmp_path}/down.db")
    try:
        migrate.upgrade(engine)
        config = migrate.alembic_config(engine.url.render_as_string(hide_password=False))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0008")
        inspector = sa.inspect(engine)
        assert "article_redirects" not in inspector.get_table_names()
        assert "body_format" not in {c["name"] for c in inspector.get_columns("articles")}
        assert "body_format" not in {c["name"] for c in inspector.get_columns("article_revisions")}
    finally:
        engine.dispose()


def test_old_json_exports_still_load_without_the_format(app, admin):
    """`quillsail import` inserts rows from older exports that have no body_format."""
    from sqlalchemy import insert

    with app.app_context():
        table = Article.__table__
        db.session.execute(insert(table), [{"slug": "old-export", "title": "Old", "body": "x"}])
        table = ArticleRevision.__table__
        article_id = db.session.scalar(select(Article.id).where(Article.slug == "old-export"))
        db.session.execute(insert(table), [{"article_id": article_id, "body": "x"}])
        db.session.commit()
        assert db.session.get(Article, article_id).body_format == "markdown"
