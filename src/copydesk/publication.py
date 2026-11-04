"""Host-selected publication modes; changing mode preserves existing content."""

import base64
import json
from urllib.parse import urlencode, urlsplit, urlunsplit

from flask import has_request_context, request

from copydesk import settings
from copydesk.helpers import external_url, state

MODES = {
    "newsletter": "Newsletter",
    "blog": "Blog",
    "hybrid": "Blog + newsletter",
}
MAX_NEWSLETTER_BLURB = 5_000


def is_blog():
    return settings.get("site.mode") in {"blog", "hybrid"}


def has_newsletter():
    return settings.get("site.mode") != "blog"


def has_competitions():
    return not is_blog() or settings.get("blog.competitions_enabled")


def interactive_available():
    """Desktop public sites expose reading and subscriptions, not accounts."""
    return not has_request_context() or request.environ.get("quillsail.listener") != "public"


def valid_web_url(value, *, base=False):
    try:
        url = urlsplit(value)
        if url.port is not None and not 1 <= url.port <= 65535:
            return False
        return bool(
            value
            and len(value) <= 2048
            and url.scheme in {"http", "https"}
            and url.hostname
            and not url.username
            and not url.password
            and "\\" not in value
            and not any(c.isspace() or ord(c) < 32 for c in value)
            and (not base or (not url.query and not url.fragment))
        )
    except ValueError:
        return False


def external_submission_url(article):
    target = settings.get("blog.newsletter_url") or ""
    if (
        not article.is_published
        or article.visibility != "public"
        or not valid_web_url(target, base=True)
    ):
        return ""
    url = urlsplit(target)
    here = urlsplit(state().config.base_url)
    if (url.netloc.lower(), url.path.rstrip("/")) == (here.netloc.lower(), here.path.rstrip("/")):
        return ""
    query = urlencode(
        {
            "source": external_url("public.article", slug=article.slug),
            "title": article.display_title,
            "excerpt": article.summary[:400],
            "author": ", ".join(user.display_name for user in article.authors)[:200],
        }
    )
    # Fragments stay in the browser: neither server logs nor the sign-in URL
    # receive the article body. The destination still requires a normal,
    # authenticated, CSRF-protected submission after the writer reviews it.
    transfer = base64.urlsafe_b64encode(json.dumps({
        "version": 1,
        "source": external_url("public.article", slug=article.slug),
        "body": article.body,
        "body_format": article.body_format,
    }, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return urlunsplit((
        url.scheme, url.netloc, url.path.rstrip("/") + "/write/from-blog",
        query, "quillsail=" + transfer,
    ))
