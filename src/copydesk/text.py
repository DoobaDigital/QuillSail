"""Turning Markdown into safe HTML, for the web and for email.

Writers use Markdown with a few extras: tables, footnotes, task lists, ~~strike~~,
automatic links, syntax-highlighted code blocks, and callouts::

    ::: tip Optional title
    Callouts come in three kinds: note, tip and warning.
    :::

Raw HTML in Markdown is never rendered, and the output is sanitized as a second
line of defense. Extensions can add Markdown plugins (see ``hooks``).

An article's body can also be typed as HTML, or be Markdown with HTML mixed in
(see ``BODY_FORMATS``). There the sanitizer is the only safeguard, so typed HTML
goes through the stricter ``sanitize_authored``. Writers can be strangers, so it
never allows scripts, styles, forms or the classes the site's interface uses.
"""

from __future__ import annotations

import difflib
import re
from html import escape, unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import nh3
from flask import current_app, has_app_context
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markupsafe import Markup
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.token import STANDARD_TYPES
from pygments.util import ClassNotFound

from copydesk.utils import slugify, truncate, word_count

CALLOUTS = ("note", "tip", "warning")

ALLOWED_TAGS = {
    "a", "abbr", "aside", "b", "blockquote", "br", "code", "dd", "del", "div", "dl", "dt",
    "em", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img",
    "input", "ins", "kbd", "li", "mark", "ol", "p", "pre", "s", "section", "span",
    "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "id", "class"},
    "img": {"src", "alt", "title", "loading", "width", "height"},
    "abbr": {"title"},
    "aside": {"class"},
    "code": {"class"},
    "div": {"class"},
    "hr": {"class"},
    "input": {"checked", "disabled", "class"},
    "li": {"id", "class"},
    "ol": {"start", "class"},
    "p": {"class"},
    "pre": {"class"},
    "section": {"class"},
    "span": {"class"},
    "sup": {"id", "class"},
    "td": {"class"},
    "th": {"class"},
    "ul": {"class"},
    **{f"h{n}": {"id"} for n in range(1, 7)},
}
URL_SCHEMES = {"http", "https", "mailto"}

BODY_FORMATS = {
    "markdown": "Markdown",
    "html": "HTML",
    "markdown_html": "Markdown with HTML",
}
DEFAULT_BODY_FORMAT = "markdown"

AUTHORED_TAGS = ALLOWED_TAGS | {
    "audio", "caption", "cite", "details", "dfn", "iframe", "q", "samp", "small", "source",
    "summary", "time", "track", "u", "var", "video", "wbr",
}
AUTHORED_ATTRIBUTES = {
    **ALLOWED_ATTRIBUTES,
    "audio": {"src", "controls", "preload", "loop"},
    "details": {"open"},
    "dfn": {"title"},
    "iframe": {"src", "title", "width", "height"},
    "source": {"src", "type"},
    "td": {"class", "colspan", "rowspan"},
    "th": {"class", "colspan", "rowspan", "scope"},
    "time": {"datetime"},
    "track": {"src", "kind", "srclang", "label", "default"},
    "video": {"src", "poster", "controls", "width", "height", "preload", "loop", "muted", "playsinline"},
}
# Values typed HTML can't choose: checkboxes stay inert, media shows its controls,
# and an embed gets no more access to the page or the reader's browser than it needs.
AUTHORED_FORCED_ATTRIBUTES = {
    "audio": {"controls": "controls"},
    "iframe": {
        "allowfullscreen": "allowfullscreen",
        "loading": "lazy",
        "referrerpolicy": "strict-origin-when-cross-origin",
        "sandbox": "allow-same-origin allow-scripts allow-presentation allow-popups",
    },
    "img": {"loading": "lazy"},
    "input": {"disabled": "disabled", "type": "checkbox"},
    "video": {"controls": "controls"},
}
# Only classes the Markdown renderer itself produces. Everything else on the site
# (buttons, alerts, forms, navigation) must not be reachable from an article.
AUTHORED_CLASSES = {
    "a": {"footnote-backref"},
    "aside": {"callout", "callout-note", "callout-tip", "callout-warning"},
    "hr": {"footnotes-sep"},
    "input": {"task-list-item-checkbox"},
    "li": {"footnote-item", "task-list-item"},
    "ol": {"contains-task-list", "footnotes-list"},
    "p": {"callout-title"},
    "pre": {"highlight"},
    "section": {"footnotes"},
    "span": {name for name in STANDARD_TYPES.values() if name},
    "sup": {"footnote-ref"},
    "td": {"align-center", "align-left", "align-right"},
    "th": {"align-center", "align-left", "align-right"},
    "ul": {"contains-task-list"},
}
_CODE_CLASS_RE = re.compile(r"language-[\w+#.-]{1,40}", re.A)
_FOOTNOTE_IDS = {
    "a": re.compile(r"fnref\d+(:\d+)?", re.A),
    "li": re.compile(r"fn\d+", re.A),
    "sup": re.compile(r"fnref\d+(:\d+)?", re.A),
}
_HEADING_ID_RE = re.compile(r"[\w-]{1,100}", re.A)
_DIMENSION_RE = re.compile(r"\d{1,4}", re.A)
_YOUTUBE_RE = re.compile(r"/embed/([\w-]{6,20})/?", re.A)
_VIMEO_RE = re.compile(r"/video/(\d{1,20})/?", re.A)
# Keep these hosts in step with frame-src in security.default_csp.
EMBED_HOSTS = ("https://www.youtube-nocookie.com", "https://player.vimeo.com")

_ALIGN_RE = re.compile(r'style="text-align:(left|right|center)"')
_CELL_ALIGN_RE = re.compile(r'<(td|th) style="text-align:(left|right|center)"')
_IFRAME_RE = re.compile(r"<iframe\b([^>]*)>.*?</iframe>", re.S)
_PARAGRAPH_RE = re.compile(r"<p>(.*?)</p>", re.S)
_WEB_FORMATTER = HtmlFormatter(nowrap=True)


def _highlight(code: str, lang: str, _attrs: Any) -> str:
    lang = (lang or "").strip().lower()
    if not lang:
        return ""
    try:
        lexer = get_lexer_by_name(lang, stripnl=False, ensurenl=False)
    except ClassNotFound:
        return ""
    body = pygments_highlight(code, lexer, _WEB_FORMATTER)
    return f'<pre class="highlight"><code class="language-{escape(lang)}">{body}</code></pre>'


def _callout_renderer(name: str):
    def render(self, tokens, idx, _options, _env):
        token = tokens[idx]
        if token.nesting == 1:
            title = token.info.strip()[len(name):].strip() or name.capitalize()
            return (
                f'<aside class="callout callout-{name}">\n'
                f'<p class="callout-title">{escape(title)}</p>\n'
            )
        return "</aside>\n"

    return render


def _render_image(self, tokens, idx, options, env):
    tokens[idx].attrSet("loading", "lazy")
    return RendererHTML.image(self, tokens, idx, options, env)


def build_markdown(
    setups: list | tuple = (), *, html: bool = False, typographer: bool = True
) -> MarkdownIt:
    md = MarkdownIt(
        "commonmark",
        {"html": html, "linkify": True, "typographer": typographer, "highlight": _highlight},
    )
    md.enable(["table", "strikethrough", "linkify", "replacements", "smartquotes"])
    md.use(footnote_plugin)
    md.use(tasklists_plugin)
    md.use(anchors_plugin, min_level=2, max_level=4, slug_func=lambda s: slugify(s, 60, "section"))
    for name in CALLOUTS:
        md.use(container_plugin, name, render=_callout_renderer(name))
    md.add_render_rule("image", _render_image)
    for setup in setups:
        setup(md)
    return md


_default_markdown: dict[str, MarkdownIt] = {}
# markdown renders pieces; markdown_html also lets typed HTML through to the sanitizer;
# markdown_source keeps the text as written, for tools that read the source.
_MARKDOWN_OPTIONS = {
    "markdown": {},
    "markdown_html": {"html": True},
    "markdown_source": {"typographer": False},
}


def _markdown(kind: str = "markdown") -> MarkdownIt:
    if has_app_context():
        state = current_app.extensions.get("copydesk")
        if state is not None:
            parser = getattr(state, kind)
            if parser is None:
                parser = build_markdown(state.hooks.markdown_setups, **_MARKDOWN_OPTIONS[kind])
                setattr(state, kind, parser)
            return parser
    if kind not in _default_markdown:
        _default_markdown[kind] = build_markdown(**_MARKDOWN_OPTIONS[kind])
    return _default_markdown[kind]


def markdown_tokens(text: str | None, *, kind: str = "markdown_source") -> tuple[list[Any], dict]:
    """Parse Markdown with the site's plugins, without rendering it."""
    env: dict = {}
    return _markdown(kind).parse(text or "", env), env


def sanitize(html: str) -> str:
    return nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        tag_attribute_values={"input": {"type": {"checkbox"}}},
        url_schemes=URL_SCHEMES,
        link_rel=None,
        strip_comments=True,
    )


def embed_url(value: str) -> str | None:
    """The address to frame for an approved video embed, or None for anything else."""
    url = urlsplit(value)
    if url.scheme != "https" or url.username or url.password or url.port:
        return None
    if url.hostname in ("www.youtube.com", "youtube.com", "www.youtube-nocookie.com"):
        match = _YOUTUBE_RE.fullmatch(url.path)
        if not match:
            return None
        start = parse_qs(url.query).get("start", [""])[0]
        query = f"?start={start}" if start.isdecimal() else ""
        return f"https://www.youtube-nocookie.com/embed/{match.group(1)}{query}"
    if url.hostname == "player.vimeo.com":
        match = _VIMEO_RE.fullmatch(url.path)
        return f"https://player.vimeo.com/video/{match.group(1)}" if match else None
    return None


def _authored_attribute(tag: str, name: str, value: str, base_url: str = "") -> str | None:
    """Decide what happens to one attribute of typed HTML. None removes it."""
    if name == "class":
        allowed = AUTHORED_CLASSES.get(tag, ())
        kept = [
            item for item in value.split()
            if item in allowed or (tag == "code" and _CODE_CLASS_RE.fullmatch(item))
        ]
        return " ".join(kept) or None
    if name == "id":
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            return value if _HEADING_ID_RE.fullmatch(value) else None
        pattern = _FOOTNOTE_IDS.get(tag)
        return value if pattern and pattern.fullmatch(value) else None
    if name in ("width", "height"):
        return value if _DIMENSION_RE.fullmatch(value) else None
    if tag == "iframe" and name == "src":
        return embed_url(value)
    if base_url and name in ("href", "src", "poster") and not value.startswith("#"):
        return urljoin(base_url, value)
    return value


def _clean_iframe(match: re.Match) -> str:
    # Text inside <iframe> stays unescaped through the sanitizer, so never keep it. A frame
    # whose address wasn't approved has nothing to show, so it goes too.
    return f"<iframe{match.group(1)}></iframe>" if " src=" in match.group(1) else ""


def sanitize_authored(html: str, *, base_url: str = "") -> str:
    """Clean HTML a person typed, or Markdown output that has typed HTML mixed in."""
    cleaned = nh3.clean(
        html,
        tags=AUTHORED_TAGS,
        attributes=AUTHORED_ATTRIBUTES,
        attribute_filter=lambda tag, name, value: _authored_attribute(tag, name, value, base_url),
        set_tag_attribute_values=AUTHORED_FORCED_ATTRIBUTES,
        url_schemes=URL_SCHEMES,
        link_rel=None,
        strip_comments=True,
    )
    return _IFRAME_RE.sub(_clean_iframe, cleaned)


def render_markdown(text: str | None, *, base_url: str = "") -> Markup:
    """Markdown to sanitized HTML for the website."""
    md = _markdown()
    env: dict = {}
    tokens = md.parse(text or "", env)
    if base_url:
        def resolve_links(tokens):
            for token in tokens:
                for attr in ("href", "src"):
                    value = token.attrGet(attr)
                    if value and not value.startswith("#"):
                        token.attrSet(attr, urljoin(base_url, value))
                if token.children:
                    resolve_links(token.children)
        resolve_links(tokens)
    html = md.renderer.render(tokens, md.options, env)
    html = _ALIGN_RE.sub(r'class="align-\1"', html)
    html = sanitize(html)
    if has_app_context() and "copydesk" in current_app.extensions:
        html = current_app.extensions["copydesk"].hooks.apply_filters("markdown.html", html)
    return Markup(html)


def render_source(
    text: str | None, body_format: str | None = DEFAULT_BODY_FORMAT, *, base_url: str = ""
) -> Markup:
    """Sanitized HTML for a body written in any of ``BODY_FORMATS``."""
    if (body_format or DEFAULT_BODY_FORMAT) == DEFAULT_BODY_FORMAT:
        return render_markdown(text, base_url=base_url)
    if body_format == "markdown_html":
        md = _markdown("markdown_html")
        env: dict = {}
        html = md.renderer.render(md.parse(text or "", env), md.options, env)
    else:
        html = text or ""
    html = sanitize_authored(_CELL_ALIGN_RE.sub(r'<\1 class="align-\2"', html), base_url=base_url)
    if has_app_context() and "copydesk" in current_app.extensions:
        html = current_app.extensions["copydesk"].hooks.apply_filters("markdown.html", html)
    return Markup(html)


def render_body(article: Any) -> Markup:
    """An article's text as sanitized HTML, whichever format it was written in."""
    return render_source(article.body, article.body_format, base_url=article.source_url or "")


def render_inline(text: str | None) -> Markup:
    """Markdown for one line (no paragraphs), e.g. a short bio."""
    html = _markdown().renderInline(text or "")
    return Markup(sanitize(html))


def html_to_text(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(nh3.clean(str(html), tags=set()))).strip()


def _html_excerpt(html: str, length: int) -> str:
    for match in _PARAGRAPH_RE.finditer(html):
        plain = html_to_text(match.group(1))
        if plain:
            return truncate(plain, length)
    return truncate(html_to_plain(html, links=False), length)


def excerpt(text: str | None, length: int = 220) -> str:
    """The first paragraph of some Markdown as plain text, cut to ``length``."""
    return _html_excerpt(str(render_markdown(text)), length)


def source_excerpt(text: str | None, body_format: str | None, length: int = 220) -> str:
    return _html_excerpt(str(render_source(text, body_format)), length)


def body_excerpt(article: Any, length: int = 220) -> str:
    """The first paragraph of an article as plain text, whichever format it was written in."""
    return source_excerpt(article.body, article.body_format, length)


def source_word_count(text: str | None, body_format: str | None = DEFAULT_BODY_FORMAT) -> int:
    """Count the words a reader sees, so tags in typed HTML don't count."""
    if (body_format or DEFAULT_BODY_FORMAT) == DEFAULT_BODY_FORMAT:
        return word_count(text or "")
    return word_count(html_to_plain(str(render_source(text, body_format)), links=False))


def body_text(article: Any) -> str:
    """An article for the plain-text part of an email. Markdown already reads as plain text."""
    if (article.body_format or DEFAULT_BODY_FORMAT) == DEFAULT_BODY_FORMAT:
        return article.body
    return html_to_plain(str(render_body(article)))


def stats(text: str | None) -> dict[str, int]:
    words = word_count(text or "")
    return {"words": words, "minutes": max(1, round(words / 230)) if words else 0}


class _PlainText(HTMLParser):
    """Sanitized HTML as readable text, keeping paragraphs, list items and link addresses."""

    BLOCKS = {
        "aside", "blockquote", "caption", "dd", "details", "div", "dl", "dt", "figcaption", "figure",
        "h1", "h2", "h3", "h4", "h5", "h6", "hr", "ol", "p", "pre", "section", "summary", "table",
        "ul",
    }
    SILENT = {"audio", "iframe", "video"}

    def __init__(self, links: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.links = links
        self.out: list[str] = []
        self.href: list[str] = []
        self.pre = 0
        self.silent = 0

    def _block(self) -> None:
        if self.out and not self.out[-1].endswith("\n\n"):
            self.out.append("\n\n")

    def _media(self, attrs: dict[str, str | None]) -> None:
        if self.links and attrs.get("src"):
            self._block()
            self.out.append(media_link(attrs["src"] or ""))
            self._block()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in self.SILENT:
            self._media(values)
            self.silent += 1
        elif tag == "source" and self.silent:
            self._media(values)
        elif tag in self.BLOCKS:
            self._block()
            self.pre += tag == "pre"
        elif tag == "br":
            self.out.append("\n")
        elif tag == "li":
            if self.out and not self.out[-1].endswith("\n"):
                self.out.append("\n")
            self.out.append("- ")
        elif tag in ("td", "th"):
            self.out.append(" | " if self.out and not self.out[-1].endswith("\n") else "")
        elif tag == "tr":
            if self.out and not self.out[-1].endswith("\n"):
                self.out.append("\n")
        elif tag == "img":
            self.out.append(values.get("alt") or "")
        elif tag == "a":
            self.href.append(values.get("href") or "")

    def handle_endtag(self, tag):
        if tag in self.SILENT:
            self.silent = max(0, self.silent - 1)
        elif tag in self.BLOCKS:
            self.pre -= tag == "pre"
            self._block()
        elif tag == "a" and self.href:
            href = self.href.pop()
            if self.links and href and not href.startswith("#"):
                self.out.append(f" ({href})")

    def handle_data(self, data):
        if self.silent:
            return
        text = data if self.pre else re.sub(r"\s+", " ", data)
        if not self.pre and text.strip() == "" and (not self.out or self.out[-1].endswith("\n")):
            return
        self.out.append(text)


def media_link(src: str) -> str:
    """A link readers can open from a message that can't play video."""
    url = urlsplit(src)
    if url.hostname == "www.youtube-nocookie.com":
        match = _YOUTUBE_RE.fullmatch(url.path)
        if match:
            return f"https://www.youtube.com/watch?v={match.group(1)}"
    if url.hostname == "player.vimeo.com":
        match = _VIMEO_RE.fullmatch(url.path)
        if match:
            return f"https://vimeo.com/{match.group(1)}"
    return src


def html_to_plain(html: str, *, links: bool = True) -> str:
    """Sanitized HTML as plain text, with a blank line between blocks."""
    parser = _PlainText(links)
    parser.feed(str(html))
    parser.close()
    return "".join(parser.out).strip()


# --------------------------------------------------------------------------- email


class _EmailStyler(HTMLParser):
    """Rewrites sanitized HTML with inline styles, because many email apps ignore <style>."""

    VOID = {"br", "hr", "img", "input", "source", "track", "wbr"}
    # Most email apps can't play media or fold a section, so readers get a link or the open text.
    MEDIA = {"audio": "Listen", "iframe": "Watch the video", "video": "Watch the video"}
    RENAMED = {"details": "div", "summary": "p"}

    def __init__(self, styles: dict[str, str], token_styles: dict[str, str], origin: str) -> None:
        super().__init__(convert_charrefs=True)
        self.styles = styles
        self.token_styles = token_styles
        self.origin = origin.rstrip("/")
        self.out: list[str] = []
        self.stack: list[str] = []
        self.media: dict[str, str] | None = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in self.MEDIA and self.media is None:
            self.media = {"tag": tag, "src": values.get("src") or ""}
            return
        if self.media is not None:
            if tag == "source" and not self.media["src"]:
                self.media["src"] = values.get("src") or ""
            return
        if tag == "track":
            return
        name = self.RENAMED.get(tag, tag)
        self.out.append(self._open(name, values, style_as=tag))
        if tag not in self.VOID:
            self.stack.append(name)

    def handle_startendtag(self, tag, attrs):
        if self.media is None:
            self.out.append(self._open(tag, dict(attrs)))

    def handle_endtag(self, tag):
        if self.media is not None:
            if tag == self.media["tag"]:
                media, self.media = self.media, None
                if media["src"]:
                    self.out.append(self._media_link(tag, media["src"]))
            return
        if tag in self.VOID:
            return
        tag = self.RENAMED.get(tag, tag)
        if tag in self.stack:
            while self.stack:
                if self.stack.pop() == tag:
                    break
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.media is None:
            self.out.append(escape(data, quote=False))

    def _media_link(self, tag: str, src: str) -> str:
        link = self._open("a", {"href": media_link(src)})
        return f'{self._open("p", {})}{link}{self.MEDIA[tag]}</a></p>'

    def _open(self, tag: str, attrs: dict[str, str | None], style_as: str = "") -> str:
        classes = (attrs.pop("class", None) or "").split()
        style = self.styles.get(style_as or tag, "") or self.styles.get(tag, "")
        if tag == "code":
            style = self.styles["pre code"] if "pre" in self.stack else self.styles["code"]
        elif tag == "aside" and "callout" in classes:
            kind = next((c.split("-", 1)[1] for c in classes if c.startswith("callout-")), "note")
            style = self.styles.get(f"callout {kind}", self.styles["callout note"])
        elif tag == "p" and "callout-title" in classes:
            style = self.styles["callout title"]
        elif tag in ("th", "td"):
            for cls in classes:
                if cls.startswith("align-"):
                    style += f"text-align:{cls[6:]};"
        elif tag == "span":
            style = "".join(self.token_styles.get(cls, "") for cls in classes)
        for key in ("href", "src"):
            value = attrs.get(key)
            if value and value.startswith("/") and not value.startswith("//"):
                attrs[key] = self.origin + value
        if style:
            attrs["style"] = style
        parts = [tag]
        for key, value in attrs.items():
            parts.append(key if value is None else f'{key}="{escape(value)}"')
        return "<" + " ".join(parts) + ">"


def email_styles(accent: str) -> dict[str, str]:
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
    mono = "SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
    styles = {
        "p": "margin:0 0 16px;font-size:16px;line-height:1.65;",
        "h1": f"margin:28px 0 12px;font-family:{font};font-size:26px;line-height:1.25;font-weight:700;",
        "h2": f"margin:28px 0 12px;font-family:{font};font-size:21px;line-height:1.3;font-weight:700;",
        "h3": f"margin:24px 0 10px;font-family:{font};font-size:18px;line-height:1.35;font-weight:700;",
        "h4": f"margin:20px 0 8px;font-family:{font};font-size:16px;line-height:1.4;font-weight:700;",
        "a": f"color:{accent};text-decoration:underline;",
        "blockquote": "margin:0 0 16px;padding:2px 0 2px 16px;border-left:3px solid #c9ced8;color:#4a505c;",
        "pre": "margin:0 0 16px;padding:12px 14px;background:#f4f5f7;border-radius:6px;"
               "white-space:pre-wrap;word-break:break-word;font-size:13px;line-height:1.5;",
        "pre code": f"font-family:{mono};font-size:13px;",
        "code": f"font-family:{mono};font-size:0.9em;background:#f1f2f4;padding:1px 4px;border-radius:4px;",
        "img": "max-width:100%;height:auto;border:0;display:block;margin:0 auto 16px;",
        "ul": "margin:0 0 16px;padding-left:24px;",
        "ol": "margin:0 0 16px;padding-left:24px;",
        "li": "margin:0 0 6px;font-size:16px;line-height:1.6;",
        "table": "border-collapse:collapse;width:100%;margin:0 0 16px;font-size:14px;",
        "th": "border:1px solid #d6dae1;padding:6px 8px;text-align:left;background:#f4f5f7;",
        "td": "border:1px solid #d6dae1;padding:6px 8px;",
        "hr": "border:0;border-top:1px solid #e3e6eb;margin:24px 0;",
        "summary": "margin:0 0 8px;font-size:16px;line-height:1.65;font-weight:700;",
        "callout note": "display:block;margin:0 0 16px;padding:12px 16px;background:#f2f5fb;border-left:4px solid #5b7bd5;",
        "callout tip": "display:block;margin:0 0 16px;padding:12px 16px;background:#eff8f2;border-left:4px solid #2f9e5c;",
        "callout warning": "display:block;margin:0 0 16px;padding:12px 16px;background:#fdf6ec;border-left:4px solid #d48a1c;",
        "callout title": "margin:0 0 6px;font-weight:700;font-size:14px;",
    }
    from flask import has_app_context

    if has_app_context():
        from copydesk.appearance import design, email_design

        d = design()
        if d["enabled"]:
            e = email_design(d)
            styles["p"] = e["p"]
            styles["li"] = e["p"].replace("0 0 16px", "0 0 6px")
            for tag, size in (("h1", 28), ("h2", 23), ("h3", 20), ("h4", 18)):
                styles[tag] = f"margin:24px 0 12px;font-family:{e['heading_font']};font-size:{size}px;line-height:1.3;color:{e['text']};"
            styles["blockquote"] = f"margin:0 0 16px;padding:2px 0 2px 16px;border-left:3px solid {e['border']};color:{e['muted']};"
            styles["a"] = f"color:{e['link']};text-decoration:underline;"
    return styles


_email_token_styles: dict[str, str] | None = None


def _token_styles() -> dict[str, str]:
    global _email_token_styles
    if _email_token_styles is None:
        formatter = HtmlFormatter(style="default")
        _email_token_styles = {
            cls: value[0].strip().rstrip(";") + ";" for cls, value in formatter.class2style.items() if value[0]
        }
    return _email_token_styles


def email_html(html: str | Markup, accent: str, origin: str) -> Markup:
    """Inline styles and absolute URLs so sanitized HTML survives email clients."""
    styler = _EmailStyler(email_styles(accent), _token_styles(), origin)
    styler.feed(str(html))
    styler.close()
    return Markup("".join(styler.out))


# --------------------------------------------------------------------------- diffs

_WORD_RE = re.compile(r"\s+|\w+|[^\w\s]")


def _word_diff(old: str, new: str) -> tuple[str, str]:
    a, b = _WORD_RE.findall(old), _WORD_RE.findall(new)
    left: list[str] = []
    right: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        old_part, new_part = escape("".join(a[i1:i2])), escape("".join(b[j1:j2]))
        if tag == "equal":
            left.append(old_part)
            right.append(new_part)
        else:
            if old_part:
                left.append(f"<del>{old_part}</del>")
            if new_part:
                right.append(f"<ins>{new_part}</ins>")
    return "".join(left), "".join(right)


def diff(old: str, new: str, context: int = 2) -> list[dict[str, Any]]:
    """A readable line-by-line diff, with changed words highlighted inside each line.

    Returns rows of ``{"kind": "same" | "add" | "del" | "skip", "html": ..., "count": ...}``.
    """
    a, b = (old or "").splitlines(), (new or "").splitlines()
    rows: list[dict[str, Any]] = []
    opcodes = difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes()
    for index, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            lines = a[i1:i2]
            head = lines[:context] if index > 0 else []
            tail = lines[-context:] if index < len(opcodes) - 1 else []
            if len(lines) <= len(head) + len(tail) + 1:
                rows.extend({"kind": "same", "html": escape(line)} for line in lines)
                continue
            rows.extend({"kind": "same", "html": escape(line)} for line in head)
            rows.append({"kind": "skip", "count": len(lines) - len(head) - len(tail)})
            rows.extend({"kind": "same", "html": escape(line)} for line in tail)
        elif tag == "replace":
            old_lines, new_lines = a[i1:i2], b[j1:j2]
            pairs = min(len(old_lines), len(new_lines))
            dels, adds = [], []
            for k in range(pairs):
                left, right = _word_diff(old_lines[k], new_lines[k])
                dels.append({"kind": "del", "html": left})
                adds.append({"kind": "add", "html": right})
            dels.extend({"kind": "del", "html": escape(line)} for line in old_lines[pairs:])
            adds.extend({"kind": "add", "html": escape(line)} for line in new_lines[pairs:])
            rows.extend(dels + adds)
        elif tag == "delete":
            rows.extend({"kind": "del", "html": escape(line)} for line in a[i1:i2])
        elif tag == "insert":
            rows.extend({"kind": "add", "html": escape(line)} for line in b[j1:j2])
    for row in rows:
        if "html" in row:
            row["html"] = Markup(row["html"] or "&nbsp;")
    return rows
