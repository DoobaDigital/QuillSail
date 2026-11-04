"""Reader and author journeys across blog modes and hosting boundaries."""

from datetime import timedelta

import pytest
from lxml import html
from sqlalchemy import select

from copydesk import newsletter, settings
from copydesk.db import db
from copydesk.models import Article, Competition, CompetitionEntry, Section, User
from copydesk.utils import utcnow
from test_blog import make_post, member_client, mode, post


def links(response, xpath="//a/@href"):
    assert response.status_code == 200
    return html.fromstring(response.data).xpath(xpath)


@pytest.mark.parametrize("value", ["newsletter", "blog", "hybrid"])
def test_competitions_follow_mode_and_explicit_opt_in(app, client, editor_client, admin, value):
    client = app.test_client()
    mode(app, value)
    enabled = value == "newsletter"
    assert ("/competitions/" in links(client.get("/"))) == enabled
    assert ("/dashboard/competitions/" in links(editor_client.get("/dashboard/"))) == enabled
    assert client.get("/competitions/").status_code == (200 if enabled else 404)
    assert editor_client.get("/dashboard/competitions/new").status_code == (200 if enabled else 404)
    if enabled:
        return

    # Use the real CSRF-protected settings form to opt in.
    fields = {}
    with app.app_context():
        for definition in settings.for_tab("general"):
            fields[definition.key] = settings.get(definition.key)
    fields["blog.competitions_enabled"] = "1"
    assert editor_client.post("/dashboard/settings/", data=fields).status_code == 400
    assert post(editor_client, "/dashboard/settings/", **fields).status_code == 302
    assert "/competitions/" in links(client.get("/"))
    assert client.get("/competitions/").status_code == 200
    assert editor_client.get("/dashboard/competitions/new").status_code == 200
    # Opting in never grants an ordinary reader management access.
    assert client.get("/dashboard/competitions/new").status_code == 302
    with app.app_context():
        contest = Competition(title="Existing competition", status="submissions")
        db.session.add(contest)
        db.session.flush()
        db.session.add(CompetitionEntry(competition_id=contest.id, user_id=admin,
                                       title="Existing entry", body="Private entry text"))
        contest_id = contest.id
        settings.set_value("blog.competitions_enabled", False)
        db.session.commit()
    for path in ("/competitions/", f"/competitions/{contest_id}/",
                 f"/competitions/{contest_id}/enter"):
        assert client.get(path).status_code == 404
    assert post(editor_client, f"/dashboard/competitions/{contest_id}/phase", action="judging").status_code == 404
    with app.app_context():
        contest = db.session.get(Competition, contest_id)
        assert contest.status == "submissions" and len(contest.entries) == 1
    mode(app, "newsletter")
    assert client.get(f"/competitions/{contest_id}/").status_code == 200


@pytest.mark.parametrize("value", ["newsletter", "blog", "hybrid"])
def test_local_sign_in_remains_available_and_closed_registration_has_no_prompts(app, client, value):
    mode(app, value)
    assert "/login" in links(client.get("/"))
    assert client.get("/login").status_code == 200
    with app.app_context():
        settings.set_value("accounts.registration", "closed")
        settings.set_value("submissions.enabled", False)
        db.session.commit()
    for path in ("/", "/login", "/write/"):
        hrefs = links(client.get(path))
        assert not any(href.startswith("/join") for href in hrefs)
    assert "/write/" not in links(client.get("/"))


@pytest.mark.parametrize("value", ["newsletter", "blog", "hybrid"])
def test_dashboard_and_search_use_the_selected_publication_mode(app, client, editor_client, admin, value):
    client = app.test_client()
    make_post(app, admin, title="Searchable post")
    with app.app_context():
        issue = newsletter.create(db.session.get(User, admin), "Searchable issue")
        issue.published_at = utcnow()
        db.session.commit()
    mode(app, value)
    dashboard = editor_client.get("/dashboard/")
    nav = links(dashboard, "//aside//a/@href")
    assert ("/dashboard/issues/" in nav) == (value != "blog")
    assert ("/dashboard/subscribers/" in nav) == (value != "blog")
    search = client.get("/search?q=Searchable").get_data(as_text=True)
    assert "Searchable post" in search
    assert ("Searchable issue" in search) == (value != "blog")
    assert client.get("/issues/1/").status_code == 200
    if value != "newsletter":
        assert "Published posts" in dashboard.get_data(as_text=True)
        listing = html.fromstring(editor_client.get("/dashboard/articles/").data)
        assert listing.xpath("//h1/text()") == ["Posts"]
        assert listing.xpath("//a[@aria-current='page' and contains(@href, 'tab=published')]")
        assert "Search posts" in search


def test_post_navigation_skips_private_work_and_handles_equal_dates(app, client, editor_client, admin):
    client = app.test_client()
    mode(app, "blog")
    ids = [make_post(app, admin, title=f"Public post {n}")[0] for n in range(3)]
    restricted, _ = make_post(app, admin, title="Members only neighbor", visibility="members")
    draft, _ = make_post(app, admin, title="Secret unfinished draft", status="draft")
    with app.app_context():
        stamp = utcnow() - timedelta(days=1)
        for article_id in ids:
            db.session.get(Article, article_id).published_at = stamp
        db.session.get(Article, restricted).published_at = stamp
        slug = db.session.get(Article, ids[1]).slug
        draft_slug = db.session.get(Article, draft).slug
        db.session.commit()
    for reader in (client, editor_client):
        page = html.fromstring(reader.get(f"/articles/{slug}/").data)
        nav = page.xpath("//nav[@aria-label='Post navigation']")[0]
        assert "Newer post: Public post 2" in nav.text_content()
        assert "Older post: Public post 0" in nav.text_content()
        assert "Members only neighbor" not in nav.text_content()
        assert "Secret unfinished draft" not in nav.text_content()
    preview = editor_client.get(f"/articles/{draft_slug}/")
    assert not html.fromstring(preview.data).xpath("//nav[@aria-label='Post navigation']")
    assert client.get(f"/articles/{draft_slug}/").status_code == 404


def test_blog_home_discovers_public_sections_and_has_reader_and_owner_empty_states(app, client, editor_client, admin):
    client = app.test_client()
    mode(app, "blog")
    assert b"No posts yet" in client.get("/").data
    assert b"Your first post starts here" in editor_client.get("/").data
    article_id, _ = make_post(app, admin)
    restricted, _ = make_post(app, admin, title="Restricted section post", visibility="groups")
    with app.app_context():
        sections = db.session.scalars(select(Section).order_by(Section.position)).all()
        db.session.get(Article, article_id).section_id = sections[0].id
        db.session.get(Article, restricted).section_id = sections[1].id
        public_slug, private_slug = sections[0].slug, sections[1].slug
        db.session.commit()
    for path in ("/", "/articles/"):
        response = client.get(path)
        hrefs = links(response, "//nav[@aria-label='Browse posts by section' or @aria-label='Sections']//a/@href")
        assert f"/sections/{public_slug}/" in hrefs
        assert f"/sections/{private_slug}/" not in hrefs
        assert "/search" in links(response)


def test_blog_pagination_metadata_and_publisher_copy(app, client, editor_client, admin):
    mode(app, "blog")
    for number in range(11):
        make_post(app, admin, title=f"Post {number}")
    page = html.fromstring(client.get("/?page=2").data)
    assert "Page 2" in page.xpath("string(//title)")
    assert page.xpath("//link[@rel='canonical']/@href") == ["http://localhost/?page=2"]
    assert not page.xpath("//link[@rel='alternate' and contains(@href, '/issues/')]")
    writing = editor_client.get("/write/").get_data(as_text=True)
    assert "Newsletter inclusion" not in writing and "Offer an existing blog post" not in writing


def test_private_desktop_publication_does_not_redirect_to_blocked_login(app, client):
    from copydesk.models import Group

    with app.app_context():
        everyone = db.session.scalar(select(Group).where(Group.slug == "everyone"))
        everyone.permissions = []
        db.session.commit()
    assert client.get("/", environ_overrides={"quillsail.listener": "public"}).status_code == 403
    assert client.get("/").location.startswith("/login")


def test_restricted_post_on_desktop_explains_access_without_dead_account_links(app, client, admin):
    mode(app, "blog")
    _, slug = make_post(app, admin, visibility="members")
    response = client.get(f"/articles/{slug}/", environ_overrides={"quillsail.listener": "public"})
    assert b"Account access is unavailable" in response.data
    assert b"A thoughtful original blog post" not in response.data
    assert not any(href.startswith(("/login", "/join")) for href in links(response))


def test_closed_blog_dashboard_focuses_on_posts_and_counts_only_own_drafts(app, editor_client, admin):
    mode(app, "blog")
    _, other_id = member_client(app)
    make_post(app, admin, title="Owner draft", status="draft")
    make_post(app, other_id, title="Another writer's secret draft", status="draft")
    make_post(app, other_id, title="Another secret draft", status="draft")
    with app.app_context():
        settings.set_value("submissions.enabled", False)
        db.session.commit()
    response = editor_client.get("/dashboard/")
    page = html.fromstring(response.data)
    draft_stat = page.xpath("//a[contains(@class, 'stat') and contains(@href, '#bucket-drafts')]")[0]
    assert draft_stat.xpath(".//span[@class='stat-value']/text()") == ["1"]
    assert b"Latest posts" in response.data
    assert b"Oldest submissions first" not in response.data
    assert b"ACCEPTED, NOT YET PUBLISHED" not in response.data.upper()
    assert b"Another writer's secret draft" not in response.data
    assert b"no real email is" not in response.data
