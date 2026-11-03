"""Importing a Jekyll site: reading it, converting it, and what importing must never do."""

import io
import json
import stat
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image
from sqlalchemy import func, select

from copydesk import jekyll_import, jobs, mail, workflow
from copydesk.cli import main as cli
from copydesk.db import db
from copydesk.jekyll_import import ImportError_, extract_zip, plan_import, run_import
from copydesk.models import (
    Article,
    ArticleEvent,
    ArticleRedirect,
    ArticleRevision,
    AuditEntry,
    Job,
    Section,
    Tag,
    Upload,
    User,
)
from test_security_boundaries import make_user

CSRF = {"X-CSRF-Token": "test-csrf"}


def write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def picture(root: Path, name: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 12), (110, 76, 194)).save(path)


@pytest.fixture
def chirpy_site(tmp_path):
    """A site shaped like the Chirpy theme: permalink in defaults, prompts, media_subpath."""
    root = tmp_path / "site"
    write(root, "_config.yml", """
title: Example Homelab
timezone: America/New_York
baseurl: ""
defaults:
  - scope: {path: "", type: posts}
    values: {layout: post, permalink: /posts/:title/}
""")
    write(root, "_data/authors.yml", "sam: {name: Test Editor}\nghost: {name: Nobody Here}\n")
    write(root, "_posts/2026-09-23-set-up-your-Own-Cluster.md", """---
title: "Set Up Your Own Cluster"
date: 2026-09-23 00:00:00 -0500
categories: [Projects, Homelab]
tags: [beginner, kubernetes]
description: How to get started.
author: sam
pin: true
image:
  path: /assets/img/cover.png
  alt: A rack of computers
---

# Overview

Some **text** and a [local link]({% post_url 2026-01-02-second-post %}).

> Check your network first.
{: .prompt-tip }

> Danger ahead.
{: .prompt-danger }

- Do this
  - `sudo systemctl disable firewalld`

```yaml
cluster-init: true
value: "{{ not_liquid }}"
token: {% raw %}{{ kept }}{% endraw %}
```

{% highlight python linenos %}
print("{{ also_code }}")
{% endhighlight %}

![Diagram](/assets/img/diagram.png){: width="972" .shadow }
_Caption_

{% raw %}Show {{ this }} literally.{% endraw %}

`{{ inline_code }}` stays.

```bash
curl -sfL <https://get.k3s.io> | sh
```
""")
    write(root, "_posts/2026-01-02-second-post.md", """---
title: Second post
date: 2026-01-02
media_subpath: /assets/img
tags: one two
---

![Relative](diagram.png)

<details markdown="1">
<summary>More</summary>

Inside.

</details>
""")
    write(root, "_posts/2026-02-03-with-problems.md", """---
title: With problems
date: 2026-02-03 10:00:00 +0000
author: Nobody Here
---

{% include figure.html path="x" %}

{{ site.description }}

{% if page.thing %}Maybe{% endif %}

Math: $$x^2$$

![Missing](/assets/img/missing.png)

![Vector](/assets/img/logo.svg)

<script>alert(1)</script>

<iframe src="https://evil.example/x"></iframe>

<!--more-->

The end.
""")
    write(root, "_posts/2099-01-01-from-the-future.md", "---\ntitle: Future\n---\n\nLater.\n")
    write(root, "_posts/2026-03-04-not-published.md", "---\ntitle: Hidden\npublished: false\n---\n\nSecret.\n")
    write(root, "_posts/2026-04-05-no-front-matter.md", "Just text.\n")
    write(root, "_posts/2026-05-06-broken.md", "---\ntitle: [unclosed\n---\n\nBody.\n")
    write(root, "_posts/not-a-post.md", "---\ntitle: Nope\n---\n")
    write(root, "_drafts/a-draft.md", "---\ntitle: A draft\n---\n\nStill writing.\n")
    for name in ("cover", "diagram"):
        picture(root, f"assets/img/{name}.png")
    write(root, "assets/img/logo.svg", "<svg xmlns='http://www.w3.org/2000/svg'></svg>")
    write(root, "_site/posts/old/index.html", "<p>built output</p>")
    return root


@pytest.fixture
def default_site(tmp_path):
    """A plain Jekyll site: the default permalink, a base path and category folders."""
    root = tmp_path / "plain"
    write(root, "_config.yml", "title: Plain\nbaseurl: /blog\n")
    write(root, "news/_posts/2020-07-21-hello-world.markdown", """---
layout: post
title: Hello world
categories: Big Stories
date: 2020-07-21 23:30:00
---

Hello. See {{ site.baseurl }}/about and {{ "/x.pdf" | relative_url }}.
""")
    write(root, "_posts/2020-08-01-page.html", "---\ntitle: Html post\npermalink: /custom/path/\nredirect_from: [/older/one, /older/two.html]\n---\n<p>Typed <mark>HTML</mark></p>\n")
    return root


def post_named(plan, title):
    return next(post for post in plan.posts if post.title == title)


def counts_of_everything():
    return {
        model.__name__: db.session.scalar(select(func.count()).select_from(model))
        for model in (Article, ArticleRevision, ArticleEvent, ArticleRedirect, Section, Tag, Upload, AuditEntry)
    }


# -------------------------------------------------------------------------- reading a site


def test_dry_run_writes_nothing(app, chirpy_site):
    with app.app_context():
        before = counts_of_everything()
        plan = plan_import(chirpy_site)
        assert plan.counts()["new"] > 0
        assert counts_of_everything() == before
        assert not list(app.extensions["copydesk"].config.uploads_dir.rglob("*.*"))


def test_dry_run_lists_every_post_that_needs_review(app, chirpy_site):
    with app.app_context():
        plan = plan_import(chirpy_site)
    notes = " ".join(post_named(plan, "With problems").notes)
    for expected in ("include figure.html", "site.description", "{% if %}", "math", "missing.png", "SVG",
                     "<script>", "evil.example"):
        assert expected in notes
    assert "With problems" in [post.title for post in plan.needing_review]
    reasons = {item["file"]: item["reason"] for item in plan.skipped}
    assert "no front matter" in reasons["_posts/2026-04-05-no-front-matter.md"]
    assert "front matter couldn't be read" in reasons["_posts/2026-05-06-broken.md"]
    assert "doesn't start with a date" in reasons["_posts/not-a-post.md"]
    assert plan.unmatched_authors == ["Nobody Here"]
    assert plan.new_sections == ["Projects"]


def test_front_matter_maps_onto_the_article(app, chirpy_site, admin):
    with app.app_context():
        post = post_named(plan_import(chirpy_site), "Set Up Your Own Cluster")
    assert post.slug == "set-up-your-own-cluster"
    assert post.published_at == datetime(2026, 9, 23, 5, 0)  # -0500 isn't something PyYAML can read
    assert post.section == "Projects" and post.tags == ["beginner", "kubernetes", "Homelab"]
    assert post.excerpt == "How to get started." and post.featured is True
    assert post.cover == "/assets/img/cover.png" and post.cover_alt == "A rack of computers"
    assert post.authors == ["Test Editor"] and post.status == "published"


@pytest.mark.parametrize(("text", "expected"), [
    ("2026-09-23 00:00:00 -0500", datetime(2026, 9, 23, 5, 0)),
    ("2026-09-23 10:11:12 +0530", datetime(2026, 9, 23, 4, 41, 12)),
    ("2026-09-23T10:11:12Z", datetime(2026, 9, 23, 10, 11, 12)),
    ("2026-09-23 10:11", datetime(2026, 9, 23, 10, 11)),
    ("2026-9-3", datetime(2026, 9, 3)),
    ("2026-09-23 10:11:12 -5", datetime(2026, 9, 23, 15, 11, 12)),
])
def test_dates_become_naive_utc(text, expected):
    assert jekyll_import._as_utc(text, None).replace(tzinfo=None) == expected


def test_dates_without_an_offset_use_the_site_timezone(app, tmp_path):
    root = tmp_path / "zone"
    write(root, "_config.yml", "timezone: America/New_York\n")
    write(root, "_posts/2026-07-01-a.md", "---\ntitle: A\ndate: 2026-07-01 12:00:00\n---\n\nx\n")
    with app.app_context():
        assert plan_import(root).posts[0].published_at == datetime(2026, 7, 1, 16, 0)


def test_future_posts_and_unpublished_posts_come_in_as_drafts(app, chirpy_site):
    with app.app_context():
        plan = plan_import(chirpy_site)
    assert post_named(plan, "Future").status == "draft"
    assert "future" in " ".join(post_named(plan, "Future").notes)
    assert post_named(plan, "Hidden").status == "draft"
    assert post_named(plan, "A draft").status == "draft"


def test_built_site_folder_is_ignored_and_a_folder_without_a_site_is_refused(app, chirpy_site, tmp_path):
    with app.app_context():
        assert not [post for post in plan_import(chirpy_site).posts if post.source.startswith("_site")]
        empty = tmp_path / "nothing"
        empty.mkdir()
        with pytest.raises(ImportError_, match="source folder"):
            plan_import(empty)


# ----------------------------------------------------------------------------- old addresses


def test_chirpy_permalink_from_defaults(app, chirpy_site):
    with app.app_context():
        post = post_named(plan_import(chirpy_site), "Set Up Your Own Cluster")
    # Jekyll keeps the file name's capitals in :title, and hosts treat addresses as case sensitive.
    assert post.old_paths == ["/posts/set-up-your-Own-Cluster"]


def test_default_permalink_with_categories_and_base_path(app, default_site):
    with app.app_context():
        plan = plan_import(default_site)
    post = post_named(plan, "Hello world")
    # Category folders come first, categories are lowercased, and each word is its own category.
    assert post.old_paths == ["/blog/news/big/stories/2020/07/21/hello-world"]
    assert post.section == "news" and post.tags == ["Big", "Stories"]


def test_post_permalink_and_redirect_from_are_all_kept(app, default_site):
    with app.app_context():
        post = post_named(plan_import(default_site), "Html post")
    assert post.old_paths == ["/blog/custom/path", "/blog/older/one", "/blog/older/two"]
    assert post.body_format == "html"


def test_permalink_styles(app, tmp_path):
    for style, expected in (
        ("pretty", "/2020/07/21/a"), ("none", "/a"), ("ordinal", "/2020/203/a"),
        ("/:year/:i_month/:i_day/:title/", "/2020/7/21/a"), ("/:short_year/:long_month/:title", "/20/July/a"),
    ):
        root = tmp_path / style.replace("/", "_").replace(":", "")
        write(root, "_config.yml", f"permalink: {style}\n")
        write(root, "_posts/2020-07-21-a.md", "---\ntitle: A\n---\n\nx\n")
        with app.app_context():
            assert plan_import(root).posts[0].old_paths == [expected]


def test_the_day_in_an_address_follows_the_site_timezone(app, tmp_path):
    root = tmp_path / "day"
    write(root, "_config.yml", "timezone: Asia/Tokyo\npermalink: pretty\n")
    write(root, "_posts/2020-07-21-a.md", "---\ntitle: A\ndate: 2020-07-21 20:00:00 +0000\n---\n\nx\n")
    with app.app_context():
        assert plan_import(root).posts[0].old_paths == ["/2020/07/22/a"]


@pytest.mark.parametrize("variant", [
    "/2020/07/21/a.html", "/2020/07/21/a", "/2020/07/21/a/", "/2020/07/21/a/index.html",
])
def test_every_form_of_an_old_address_redirects(app, client, admin, tmp_path, variant):
    root = tmp_path / "forms"
    write(root, "_config.yml", "title: Forms\n")
    write(root, "_posts/2020-07-21-a.md", "---\ntitle: A\n---\n\nx\n")
    with app.app_context():
        run_import(plan_import(root), db.session.get(User, admin))
    response = client.get(variant + "?utm=1")
    assert response.status_code == 301
    assert response.headers["Location"].endswith("/articles/a/?utm=1")


def test_redirects_never_reveal_a_draft_and_real_pages_win(app, client, admin, tmp_path):
    root = tmp_path / "gone"
    write(root, "_config.yml", "permalink: /:title/\n")
    write(root, "_posts/2020-07-21-about.md", "---\ntitle: Old about\n---\n\nx\n")
    write(root, "_posts/2020-07-22-secret.md", "---\ntitle: Secret\n---\n\nx\n")
    with app.app_context():
        run_import(plan_import(root), db.session.get(User, admin), as_drafts=True)
    assert client.get("/secret").status_code == 404
    assert client.get("/_drafts/nothing").status_code == 404
    assert client.get("/feed.xml").status_code == 200
    with app.app_context():
        article = db.session.scalar(select(Article).where(Article.title == "Secret"))
        workflow.publish(article, None)
        db.session.commit()
    assert client.get("/secret").status_code == 301
    assert client.post("/secret", data={"csrf_token": "x"}).status_code in (400, 404, 405)


# --------------------------------------------------------------------------- converting text


def converted(app, root, title):
    with app.app_context():
        return post_named(plan_import(root), title)


def test_code_is_left_exactly_as_written(app, chirpy_site):
    body = converted(app, chirpy_site, "Set Up Your Own Cluster").body
    assert 'value: "{{ not_liquid }}"' in body
    assert "token: {{ kept }}" in body and "raw" not in body.split("```yaml")[1].split("```")[0]
    assert 'print("{{ also_code }}")' in body
    assert "`{{ inline_code }}` stays." in body
    assert "- Do this\n  - `sudo systemctl disable firewalld`" in body
    # Even a mistake inside a command stays as the author wrote it.
    assert "curl -sfL <https://get.k3s.io> | sh" in body


def test_liquid_and_kramdown_are_converted(app, chirpy_site):
    body = converted(app, chirpy_site, "Set Up Your Own Cluster").body
    assert "[local link](/articles/second-post/)" in body
    assert "::: tip\nCheck your network first.\n:::" in body
    assert "::: warning\nDanger ahead.\n:::" in body
    assert "```python\nprint(" in body
    assert "![Diagram](/assets/img/diagram.png)\n_Caption_" in body
    assert "Show {{ this }} literally." in body
    assert "{:" not in body and "{%" not in body
    assert converted(app, chirpy_site, "Set Up Your Own Cluster").notes == []


def write_post(root, body):
    write(root, "_config.yml", "title: T\n")
    write(root, "_posts/2020-01-01-a.md", f"---\ntitle: A\n---\n\n{body}")


def test_a_tutorial_about_jekyll_keeps_its_examples(app, tmp_path):
    """Posts about Jekyll quote its own syntax, and none of that may be rewritten."""
    root = tmp_path / "tutorial"
    write_post(root, """Use `{% include x.html %}` or `<!-- a comment -->` or `{: .class }` inline.

{% raw %}
```liquid
{% highlight python %}
{{ value }}
{% endhighlight %}
```
{% endraw %}

```liquid
{% highlight ruby %}
puts 1
{% endhighlight %}
<!-- kept -->
```

    {% include indented.html %}
    <!-- also kept -->

Back to prose {{ page.title }}.
""")
    post = converted(app, root, "A")
    assert "Use `{% include x.html %}` or `<!-- a comment -->` or `{: .class }` inline." in post.body
    assert "```liquid\n{% highlight python %}\n{{ value }}\n{% endhighlight %}\n```" in post.body
    assert "{% highlight ruby %}\nputs 1\n{% endhighlight %}\n<!-- kept -->" in post.body
    assert "    {% include indented.html %}\n    <!-- also kept -->" in post.body
    assert "raw" not in post.body and "Back to prose A." in post.body
    assert post.notes == [] and post.body_format == "markdown"


def test_raw_around_prose_and_code_shows_it_literally(app, tmp_path):
    root = tmp_path / "raw"
    write_post(root, """{% raw %}{{ first }}

```
{{ second }}
```

{{ third }} {% include kept.html %}{% endraw %}

{{ page.title }}
""")
    post = converted(app, root, "A")
    for piece in ("{{ first }}", "{{ second }}", "{{ third }} {% include kept.html %}"):
        assert piece in post.body
    assert post.body.rstrip().endswith("A") and post.notes == []


def test_a_highlight_block_with_blank_lines_stays_one_block(app, tmp_path):
    root = tmp_path / "highlight"
    write_post(root, """Before.

{% highlight python linenos %}
def f():

    return "{{ x }}"
{% endhighlight %}

After {{ page.title }}.
""")
    body = converted(app, root, "A").body
    assert '```python\ndef f():\n\n    return "{{ x }}"\n```' in body
    assert "After A." in body


def test_a_stray_backtick_does_not_hide_the_next_paragraph(app, tmp_path):
    root = tmp_path / "stray"
    write_post(root, "A stray ` backtick.\n\nMore {{ page.title }} and a ` second one.\n")
    assert "More A and a" in converted(app, root, "A").body


def test_prompt_mapping_covers_every_kind(app, tmp_path):
    root = tmp_path / "prompts"
    write(root, "_config.yml", "title: P\n")
    write(root, "_posts/2020-01-01-a.md", """---
title: A
---

> Info text
{: .prompt-info }

> Warn text
> second line
{: .prompt-warning }

> Plain quote
""")
    body = converted(app, root, "A").body
    assert "::: note\nInfo text\n:::" in body
    assert "::: warning\nWarn text\nsecond line\n:::" in body
    assert "> Plain quote" in body


def test_site_variables_and_urls(app, default_site):
    body = converted(app, default_site, "Hello world").body
    assert "See /about and /x.pdf." in body


def test_table_of_contents_and_comments_are_removed(app, tmp_path):
    root = tmp_path / "toc"
    write(root, "_config.yml", "title: T\n")
    write(root, "_posts/2020-01-01-a.md", """---
title: A
---

* TOC
{:toc}

{% comment %}Never shown{% endcomment %}
{::comment}Also never shown{:/comment}
<!-- Nor this -->

## Real

[a link](/x){:target="_blank"}

{{ page.title }} on {{ site.title }}
""")
    post = converted(app, root, "A")
    assert "TOC" not in post.body and "shown" not in post.body and "Nor this" not in post.body
    assert "[a link](/x)\n" in post.body and "A on T" in post.body
    assert post.body_format == "markdown"  # Comments alone don't make a post contain HTML


def test_format_follows_whether_the_post_has_html(app, chirpy_site, default_site):
    assert converted(app, chirpy_site, "Set Up Your Own Cluster").body_format == "markdown"
    assert converted(app, chirpy_site, "Second post").body_format == "markdown_html"
    assert converted(app, default_site, "Html post").body_format == "html"


def test_liquid_is_never_executed(app, tmp_path):
    marker = tmp_path / "executed"
    root = tmp_path / "evil"
    write(root, "_config.yml", "title: E\n")
    write(root, "_posts/2020-01-01-a.md", f"""---
title: !!python/object/apply:os.system ["touch {marker}"]
---

x
""")
    write(root, "_posts/2020-01-02-b.md", f"""---
title: B
---

{{{{ "x" | shell: "touch {marker}" }}}}
""")
    with app.app_context():
        plan = plan_import(root)
    assert not marker.exists()
    assert any("2020-01-01-a" in item["file"] for item in plan.skipped)


# --------------------------------------------------------------------------- importing


def run(app, root, admin, **options):
    with app.app_context():
        return run_import(plan_import(root), db.session.get(User, admin), **options)


def test_import_creates_articles_with_their_original_dates(app, client, chirpy_site, admin):
    result = run(app, chirpy_site, admin)
    assert not result.failed
    with app.app_context():
        article = db.session.scalar(select(Article).where(Article.slug == "set-up-your-own-cluster"))
        assert article.status == "published" and article.published_at == datetime(2026, 9, 23, 5, 0)
        assert article.updated_at == article.published_at
        assert article.section.name == "Projects" and article.featured and article.excerpt == "How to get started."
        assert sorted(t.name for t in article.tags) == ["Homelab", "beginner", "kubernetes"]
        assert article.cover_alt == "A rack of computers" and article.cover_image
        assert article.authors[0].id == admin
        assert article.source_url == ""
        assert [r.summary for r in workflow.revisions(article)] == ["Imported"]
        assert article.events[0].to_status == "published"
        uploads_path = f"/uploads/{article.cover_image}"
    page = client.get("/articles/set-up-your-own-cluster/")
    assert page.status_code == 200
    assert uploads_path.encode() in page.data
    assert b"Read the original blog post" not in page.data
    assert b"callout-tip" in page.data


def test_images_are_uploaded_once_and_rewritten_outside_code(app, tmp_path, admin):
    root = tmp_path / "images"
    write(root, "_config.yml", "title: I\n")
    picture(root, "assets/a.png")
    write(root, "_posts/2020-01-01-a.md", """---
title: One
image: /assets/a.png
---

![A](/assets/a.png)

<img src="/assets/a.png" alt="Same">

[ref]: /assets/a.png

```md
![Not an image](/assets/a.png)
```

`![Also not](/assets/a.png)`

![Remote](https://example.com/b.png)
""")
    write(root, "_posts/2020-01-02-b.md", "---\ntitle: Two\n---\n\n![A again](/assets/a.png)\n")
    run(app, root, admin)
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Upload)) == 1
        one = db.session.scalar(select(Article).where(Article.title == "One"))
        two = db.session.scalar(select(Article).where(Article.title == "Two"))
        stored = db.session.scalar(select(Upload)).path
    assert f"![A](/uploads/{stored})" in one.body
    assert f'<img src="/uploads/{stored}"' in one.body and f"[ref]: /uploads/{stored}" in one.body
    assert "![Not an image](/assets/a.png)" in one.body
    assert "`![Also not](/assets/a.png)`" in one.body
    assert "![Remote](https://example.com/b.png)" in one.body
    assert one.cover_image == stored and f"/uploads/{stored}" in two.body
    with app.app_context():
        assert one.body_format == "markdown_html"


def test_images_are_re_encoded_and_a_bad_file_is_reported(app, tmp_path, admin):
    root = tmp_path / "bad"
    write(root, "_config.yml", "title: B\n")
    write(root, "assets/fake.png", "not an image at all")
    write(root, "_posts/2020-01-01-a.md", "---\ntitle: A\n---\n\n![Fake](/assets/fake.png)\n")
    with app.app_context():
        plan = plan_import(root)
        result = run_import(plan, db.session.get(User, admin))
        assert not result.failed and result.images == 0
        assert any("couldn't be used" in note for note in plan.posts[0].notes)
        article = db.session.scalar(select(Article))
        assert "![Fake](/assets/fake.png)" in article.body


def test_images_outside_the_site_are_never_read(app, tmp_path, admin):
    outside = tmp_path / "outside.png"
    Image.new("RGB", (4, 4)).save(outside)
    root = tmp_path / "escape"
    write(root, "_config.yml", "title: E\n")
    (root / "assets").mkdir()
    (root / "assets" / "link.png").symlink_to(outside)
    write(root, "_posts/2020-01-01-a.md", "---\ntitle: A\nimage: ../outside.png\n---\n\n![A](../../outside.png)\n\n![B](/assets/link.png)\n")
    with app.app_context():
        plan = plan_import(root)
        assert plan.posts[0].images == {}
        run_import(plan, db.session.get(User, admin))
        assert db.session.scalar(select(func.count()).select_from(Upload)) == 0


def test_import_fires_no_hooks_and_sends_no_email(app, chirpy_site, admin):
    fired = []
    with app.app_context():
        hooks = app.extensions["copydesk"].hooks
        for name in ("article.created", "article.saved", "article.submitted", "article.status_changed", "article.published"):
            hooks.on(name, lambda name=name, **_kwargs: fired.append(name))
        before_jobs = db.session.scalar(select(func.count()).select_from(Job))
    result = run(app, chirpy_site, admin)
    assert result.imported
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Job)) == before_jobs
        jobs.run_pending()
    assert fired == [] and mail.outbox == []


def test_co_authors_get_no_email_either(app, tmp_path, admin):
    with app.app_context():
        make_user(email="coauthor@example.edu", username="coauthor")
    root = tmp_path / "authors"
    write(root, "_config.yml", "title: A\n")
    write(root, "_posts/2020-01-01-a.md", "---\ntitle: A\nauthors: [coauthor, Nobody]\n---\n\nx\n")
    run(app, root, admin)
    with app.app_context():
        jobs.run_pending()
        article = db.session.scalar(select(Article))
        assert [user.username for user in article.authors] == ["coauthor"]
    assert mail.outbox == []


def test_timeline_and_activity_log_still_record_the_import(app, chirpy_site, admin):
    run(app, chirpy_site, admin)
    with app.app_context():
        article = db.session.scalar(select(Article).where(Article.slug == "set-up-your-own-cluster"))
        assert article.events[0].body == "Imported from another blog."
        entries = db.session.scalars(select(AuditEntry).where(AuditEntry.action == "article.imported")).all()
        assert len(entries) >= 3 and all(entry.actor_id == admin for entry in entries)


def test_running_again_creates_no_duplicates(app, chirpy_site, admin):
    first = run(app, chirpy_site, admin)
    assert first.imported
    with app.app_context():
        before = counts_of_everything()
        plan = plan_import(chirpy_site)
        assert plan.counts()["new"] == 0 and plan.counts()["already_imported"] == len(first.imported)
    second = run(app, chirpy_site, admin)
    assert second.imported == [] and second.skipped == len(first.imported)
    with app.app_context():
        assert counts_of_everything() == before


def test_links_to_posts_already_imported_keep_working(app, tmp_path, admin):
    root = tmp_path / "later"
    write(root, "_config.yml", "title: L\n")
    write(root, "_posts/2020-01-01-first.md", "---\ntitle: First\n---\n\nx\n")
    run(app, root, admin)
    with app.app_context():
        article = db.session.scalar(select(Article))
        article.slug = "renamed-later"
        db.session.commit()
    write(root, "_posts/2020-02-02-second.md", "---\ntitle: Second\n---\n\n[First]({% post_url 2020-01-01-first %})\n")
    run(app, root, admin)
    with app.app_context():
        second = db.session.scalar(select(Article).where(Article.title == "Second"))
        assert "[First](/articles/renamed-later/)" in second.body


def test_one_bad_post_does_not_stop_the_others(app, tmp_path, admin, monkeypatch):
    root = tmp_path / "partial"
    write(root, "_config.yml", "title: P\n")
    for name in ("a", "b", "c"):
        write(root, f"_posts/2020-01-0{ord(name) - 96}-{name}.md", f"---\ntitle: {name}\n---\n\nx\n")
    original = workflow.import_article

    def fail_once(**kwargs):
        if kwargs["title"] == "b":
            raise RuntimeError("boom")
        return original(**kwargs)

    monkeypatch.setattr(workflow, "import_article", fail_once)
    result = run(app, root, admin)
    assert {item["title"] for item in result.imported} == {"a", "c"}
    assert result.failed == [{"file": "_posts/2020-01-02-b.md", "reason": "boom"}]
    monkeypatch.setattr(workflow, "import_article", original)
    # Running it again finishes the job without repeating anything.
    result = run(app, root, admin)
    assert [item["title"] for item in result.imported] == ["b"] and result.skipped == 2


def test_taken_slugs_get_a_new_one(app, tmp_path, admin):
    with app.app_context():
        user = db.session.get(User, admin)
        workflow.create_draft(user, "Hello")
        db.session.commit()
    root = tmp_path / "taken"
    write(root, "_config.yml", "title: T\n")
    write(root, "_posts/2020-01-01-hello.md", "---\ntitle: Hello again\n---\n\nx\n")
    with app.app_context():
        assert plan_import(root).posts[0].slug == "hello-2"


def test_tags_over_the_limit_are_reported(app, tmp_path):
    root = tmp_path / "tags"
    write(root, "_config.yml", "title: T\n")
    tags = ", ".join(f"tag{i}" for i in range(15))
    write(root, "_posts/2020-01-01-a.md", f"---\ntitle: A\ntags: [{tags}]\n---\n\nx\n")
    with app.app_context():
        post = plan_import(root).posts[0]
    assert len(post.tags) == 12 and "first 12 of its 15 tags" in " ".join(post.notes)


def test_as_drafts_keeps_every_post_private(app, client, chirpy_site, admin):
    run(app, chirpy_site, admin, as_drafts=True)
    with app.app_context():
        assert not db.session.scalars(select(Article).where(Article.status != "draft")).all()
    assert client.get("/posts/set-up-your-Own-Cluster/").status_code == 404


def test_a_post_brought_in_as_a_draft_keeps_its_date_when_published(app, tmp_path, admin):
    root = tmp_path / "keep"
    write(root, "_config.yml", "title: K\n")
    write(root, "_posts/2020-07-21-a.md", "---\ntitle: A\n---\n\nx\n")
    write(root, "_posts/2099-07-21-later.md", "---\ntitle: Later\n---\n\nx\n")
    run(app, root, admin, as_drafts=True)
    with app.app_context():
        article = db.session.scalar(select(Article).where(Article.title == "A"))
        assert article.status == "draft" and not article.is_published
        workflow.publish(article, None)
        assert article.published_at == datetime(2020, 7, 21)
        later = db.session.scalar(select(Article).where(Article.title == "Later"))
        assert later.published_at is None


def test_imported_posts_are_not_in_the_visual_editor_when_they_have_html(app, editor_client, chirpy_site, admin):
    run(app, chirpy_site, admin)
    with app.app_context():
        article_id = db.session.scalar(select(Article.id).where(Article.title == "Second post"))
    page = editor_client.get(f"/write/{article_id}/edit").data.decode()
    assert '<option value="markdown_html" selected>Markdown with HTML</option>' in page


# ------------------------------------------------------------------------------- zip safety


def zip_bytes(entries: dict[str, bytes], *, mode: int | None = None) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if mode is not None:
                info.external_attr = mode << 16
            bundle.writestr(info, data)
    buffer.seek(0)
    return buffer


GOOD_SITE = {
    "my-blog-main/_config.yml": b"title: Zipped\n",
    "my-blog-main/_posts/2020-01-01-a.md": b"---\ntitle: A\n---\n\nx\n",
}


def test_a_github_style_zip_works(app, tmp_path):
    extract_zip(zip_bytes(GOOD_SITE), tmp_path / "out", max_unpacked=10_000)
    with app.app_context():
        assert plan_import(tmp_path / "out").site_title == "Zipped"


@pytest.mark.parametrize("name", [
    "../evil.txt", "a/../../evil.txt", "/etc/evil.txt", "C:/evil.txt", "a\\..\\evil.txt",
])
def test_paths_that_leave_the_folder_reject_the_whole_zip(tmp_path, name):
    entries = {**GOOD_SITE, name: b"owned"}
    with pytest.raises(ImportError_, match="unsafe path"):
        extract_zip(zip_bytes(entries), tmp_path / "out", max_unpacked=10_000)
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "out").exists()


def test_symbolic_links_reject_the_whole_zip(tmp_path):
    bundle = zip_bytes({"link": b"/etc/passwd"}, mode=stat.S_IFLNK | 0o777)
    with pytest.raises(ImportError_, match="symbolic link"):
        extract_zip(bundle, tmp_path / "out", max_unpacked=10_000)


def test_oversized_zips_are_rejected_before_unpacking(tmp_path):
    bundle = zip_bytes({"big.bin": b"0" * 5_000_000})
    assert len(bundle.getvalue()) < 100_000  # It compresses well, which is the point of a zip bomb.
    with pytest.raises(ImportError_, match="unpacks to more than"):
        extract_zip(bundle, tmp_path / "out", max_unpacked=1_000_000)
    assert not (tmp_path / "out").exists()


def test_a_zip_lying_about_its_size_is_rejected(tmp_path):
    raw = bytearray(zip_bytes({"_config.yml": b"0" * 3_000_000}).getvalue())
    # Claim the file is tiny in the central directory, which is what the size check reads.
    central = raw.index(b"PK\x01\x02")
    raw[central + 24 : central + 28] = (10).to_bytes(4, "little")
    with pytest.raises(ImportError_, match="damaged"):
        extract_zip(io.BytesIO(bytes(raw)), tmp_path / "out", max_unpacked=1_000_000)


def test_too_many_files_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(jekyll_import, "MAX_ZIP_FILES", 3)
    with pytest.raises(ImportError_, match="more than 3 files"):
        extract_zip(zip_bytes({f"f{i}": b"x" for i in range(4)}), tmp_path / "out", max_unpacked=10_000)


def test_encrypted_and_junk_files_are_rejected(tmp_path):
    with pytest.raises(ImportError_, match="isn't a zip"):
        extract_zip(io.BytesIO(b"this is not a zip"), tmp_path / "out", max_unpacked=10_000)
    buffer = zip_bytes({"a.txt": b"x"})
    raw = bytearray(buffer.getvalue())
    # Set the "encrypted" flag on both the local header and the central directory entry.
    raw[6] |= 1
    raw[raw.index(b"PK\x01\x02") + 8] |= 1
    with pytest.raises(ImportError_, match="password"):
        extract_zip(io.BytesIO(bytes(raw)), tmp_path / "out", max_unpacked=10_000)


def test_junk_folders_are_not_unpacked(app, tmp_path):
    entries = {**GOOD_SITE, "my-blog-main/node_modules/x/index.js": b"x", "my-blog-main/.git/config": b"x",
               "__MACOSX/._a": b"x", "my-blog-main/.DS_Store": b"x"}
    extract_zip(zip_bytes(entries), tmp_path / "out", max_unpacked=10_000)
    assert sorted(p.name for p in (tmp_path / "out").rglob("*") if p.is_file()) == ["2020-01-01-a.md", "_config.yml"]


# ------------------------------------------------------------------------ the dashboard


def upload(client, bundle, name="site.zip"):
    return client.post("/dashboard/import/jekyll", data={"csrf_token": "test-csrf", "site": (bundle, name)},
                       content_type="multipart/form-data")


def test_dashboard_upload_review_confirm_and_finish(app, editor_client, tmp_path):
    entries = {
        **GOOD_SITE,
        "my-blog-main/_posts/2020-02-02-b.md": b"---\ntitle: Needs work\n---\n\n{% include x.html %}\n",
    }
    response = upload(editor_client, zip_bytes(entries))
    assert response.status_code == 302
    review_url = response.headers["Location"]
    token = review_url.rsplit("/", 1)[-1]
    page = editor_client.get(review_url).data.decode()
    assert "Nothing has changed yet" in page and "Needs work" in page and "include x.html" in page
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Article)) == 0

    response = editor_client.post(f"/dashboard/import/jekyll/{token}/start", data={"csrf_token": "test-csrf"})
    assert response.status_code == 302
    assert "Your import is waiting to start" in editor_client.get(review_url).data.decode()
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Article)) == 0
        job = db.session.scalar(select(Job).where(Job.kind == "jekyll.import"))
        assert job.payload["token"] == token
        jobs.run_pending()
        assert db.session.scalar(select(func.count()).select_from(Article)) == 2
        assert db.session.scalar(select(AuditEntry).where(AuditEntry.action == "article.imported_site", AuditEntry.target_label == "Zipped"))
        folder = jekyll_import.import_folder(token)
        assert not (folder / "source").exists()  # The upload is gone once it's been used.
    page = editor_client.get(review_url).data.decode()
    assert "Import finished" in page and "include x.html" in page
    # Asking again changes nothing.
    assert editor_client.post(f"/dashboard/import/jekyll/{token}/start", data={"csrf_token": "test-csrf"}).status_code == 302
    with app.app_context():
        assert db.session.scalar(select(func.count()).select_from(Job).where(Job.kind == "jekyll.import")) == 1


def test_dashboard_import_can_bring_everything_in_as_drafts(app, editor_client):
    token = upload(editor_client, zip_bytes(GOOD_SITE)).headers["Location"].rsplit("/", 1)[-1]
    editor_client.post(f"/dashboard/import/jekyll/{token}/start", data={"csrf_token": "test-csrf", "as_drafts": "1"})
    with app.app_context():
        jobs.run_pending()
        assert db.session.scalar(select(Article)).status == "draft"


def test_cancelling_removes_the_upload(app, editor_client):
    token = upload(editor_client, zip_bytes(GOOD_SITE)).headers["Location"].rsplit("/", 1)[-1]
    response = editor_client.post(f"/dashboard/import/jekyll/{token}/cancel", data={"csrf_token": "test-csrf"})
    assert response.status_code == 302
    assert editor_client.get(f"/dashboard/import/jekyll/{token}").status_code == 404


def test_dashboard_reports_unsafe_zips_and_keeps_nothing(app, editor_client):
    response = upload(editor_client, zip_bytes({**GOOD_SITE, "../evil": b"x"}))
    assert response.status_code == 422 and b"unsafe path" in response.data
    response = upload(editor_client, io.BytesIO(b"not a zip"))
    assert response.status_code == 422 and b"isn&#39;t a zip" in response.data
    response = upload(editor_client, zip_bytes({"readme.txt": b"hello"}))
    assert response.status_code == 422 and b"look like a Jekyll site" in response.data
    with app.app_context():
        folder = jekyll_import.imports_dir()
        assert not folder.exists() or not list(folder.iterdir())


def test_tokens_cannot_walk_the_filesystem(app, editor_client):
    for token in ("..", "..%2f..%2f", "short", "a/b"):
        assert editor_client.get(f"/dashboard/import/jekyll/{token}").status_code == 404
    with app.app_context():
        assert jekyll_import.import_folder("../..") is None
        assert jekyll_import.import_folder("") is None


def test_uploads_larger_than_the_import_limit_are_refused(app, editor_client):
    app.extensions["copydesk"].config.max_import_mb = 1
    response = upload(editor_client, io.BytesIO(b"0" * (2 * 1024 * 1024)))
    assert response.status_code == 413


def test_the_import_limit_is_larger_than_the_normal_upload_limit_only_on_this_page(app, editor_client):
    app.extensions["copydesk"].config.max_import_mb = 60
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
    assert upload(editor_client, io.BytesIO(b"0" * (2 * 1024 * 1024))).status_code == 422
    response = editor_client.post("/write/upload", data={"image": (io.BytesIO(b"0" * (2 * 1024 * 1024)), "a.png")},
                                  headers=CSRF, content_type="multipart/form-data")
    assert response.status_code == 413


def test_csrf_and_permissions_protect_the_import(app, client, editor_client):
    with app.app_context():
        reader = make_user(email="reader@example.edu", username="reader", permissions=("review",))
        version = db.session.get(User, reader).auth_version
    other = app.test_client()
    with other.session_transaction() as session:
        session["uid"], session["uv"], session["_csrf"] = reader, version, "reader-csrf"
    assert other.get("/dashboard/import/jekyll").status_code == 403
    response = other.post("/dashboard/import/jekyll", data={"csrf_token": "reader-csrf", "site": (zip_bytes(GOOD_SITE), "s.zip")},
                          content_type="multipart/form-data")
    assert response.status_code == 403
    assert app.test_client().get("/dashboard/import/jekyll").status_code == 302
    # A valid session without the form's token gets nowhere.
    response = editor_client.post("/dashboard/import/jekyll", data={"site": (zip_bytes(GOOD_SITE), "s.zip")},
                                  content_type="multipart/form-data")
    assert response.status_code == 400
    assert b"Import a blog" in editor_client.get("/dashboard/").data
    assert b"Import a blog" not in other.get("/dashboard/").data


def test_stale_uploads_are_cleaned_up(app, editor_client):
    import os

    token = upload(editor_client, zip_bytes(GOOD_SITE)).headers["Location"].rsplit("/", 1)[-1]
    with app.app_context():
        folder = jekyll_import.import_folder(token)
        jekyll_import.remove_stale_imports()
        assert folder.exists()
        old = datetime(2020, 1, 1).timestamp()
        os.utime(folder, (old, old))
        jobs.maintenance()
        assert not folder.exists()


# ------------------------------------------------------------------------------- the command


@pytest.fixture
def config_file(tmp_path, database_url):
    from copydesk import migrate, seed
    from copydesk.app import create_app
    from copydesk.views.setup import create_admin

    path = tmp_path / "copydesk.toml"
    path.write_text(f"""
[site]
secret_key = "test-secret-key-that-is-at-least-32-characters"
base_url = "http://localhost"
data_dir = "{tmp_path}/cli-data"

[database]
url = "{database_url}"

[mail]
backend = "memory"
""", encoding="utf-8")
    app = create_app(overrides={
        "site": {"secret_key": "test-secret-key-that-is-at-least-32-characters", "base_url": "http://localhost",
                 "data_dir": str(tmp_path / "cli-data")},
        "database": {"url": database_url}, "mail": {"backend": "memory"}, "testing": True,
    })
    with app.app_context():
        migrate.upgrade(db.engine)
        seed.seed("Example")
        create_admin(email="editor@example.edu", name="Test Editor", password="correct-horse-battery-123")
        db.session.commit()
        db.session.remove()
        db.engine.dispose()
    return path


def test_command_dry_run_changes_nothing(config_file, chirpy_site):
    result = CliRunner().invoke(cli, ["--config", str(config_file), "import-jekyll", str(chirpy_site), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "This was a dry run. Nothing was changed." in result.output
    assert "Set Up Your Own Cluster" in result.output and "/posts/set-up-your-Own-Cluster" in result.output
    assert "! Replace {% include figure.html %}" in result.output
    assert "Skipped _posts/2026-04-05-no-front-matter.md" in result.output
    again = CliRunner().invoke(cli, ["--config", str(config_file), "import-jekyll", str(chirpy_site), "--dry-run"])
    assert "0 already imported" in again.output


def test_command_imports_folders_and_zips_and_can_repeat(config_file, chirpy_site, tmp_path):
    result = CliRunner().invoke(cli, ["--config", str(config_file), "import-jekyll", str(chirpy_site), "--yes"])
    assert result.exit_code == 0, result.output
    assert "Imported 6 posts" in result.output
    again = CliRunner().invoke(cli, ["--config", str(config_file), "import-jekyll", str(chirpy_site), "--yes"])
    assert "There's nothing new to import." in again.output
    archive = tmp_path / "site.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in chirpy_site.rglob("*"):
            if path.is_file():
                bundle.write(path, Path("blog") / path.relative_to(chirpy_site))
    from_zip = CliRunner().invoke(cli, ["--config", str(config_file), "import-jekyll", str(archive), "--dry-run"])
    assert from_zip.exit_code == 0, from_zip.output
    assert "6 already imported" in from_zip.output


def test_command_names_the_problem(config_file, tmp_path):
    (tmp_path / "empty").mkdir()
    result = CliRunner().invoke(cli, ["--config", str(config_file), "import-jekyll", str(tmp_path / "empty")])
    assert result.exit_code != 0 and "doesn't look like a Jekyll site" in result.output


def test_status_file_is_valid_json_with_results(app, editor_client):
    token = upload(editor_client, zip_bytes(GOOD_SITE)).headers["Location"].rsplit("/", 1)[-1]
    editor_client.post(f"/dashboard/import/jekyll/{token}/start", data={"csrf_token": "test-csrf"})
    with app.app_context():
        jobs.run_pending()
        status = json.loads((jekyll_import.import_folder(token) / "status.json").read_text())
    assert status["state"] == "done" and status["result"]["imported"][0]["slug"] == "a"
