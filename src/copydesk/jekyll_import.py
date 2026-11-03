"""Bringing an existing Jekyll blog into QuillSail.

The importer reads a Jekyll site's source folder. It never runs Jekyll, Liquid or any
plugin: every conversion here is pattern matching on text, so a site can't execute
anything by being imported. Reading a site (``plan_import``) writes nothing, which is
what makes a dry run trustworthy. ``run_import`` then creates each post in its own
transaction, so a failed import can simply run again: an address already recorded in
``article_redirects`` means that post has been imported.

Published posts already reached their readers, so importing them fires no hooks and sends
no email (see ``workflow.import_article``).
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
import shutil
import stat
import zipfile
import zlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from flask import url_for
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import FileStorage

from copydesk import jobs, uploads, workflow
from copydesk.db import db
from copydesk.helpers import state
from copydesk.models import ArticleRedirect, Section, User
from copydesk.text import AUTHORED_TAGS, embed_url, markdown_tokens
from copydesk.utils import random_token, slugify, utcnow

log = logging.getLogger(__name__)

MARKDOWN_EXTENSIONS = {"markdown", "mdown", "mdwn", "md", "mkd", "mkdn", "mkdown"}
HTML_EXTENSIONS = {"htm", "html"}
IMAGE_EXTENSIONS = {"gif", "jpeg", "jpg", "png", "svg", "webp"}
SKIPPED_FOLDERS = {".git", ".github", "_site", ".jekyll-cache", ".sass-cache", "node_modules", "vendor", "__MACOSX"}
MAX_POST_CHARACTERS = 200_000
MAX_TAGS = 12
MAX_EXCERPT = 400
MAX_ZIP_FILES = 20_000
# A zip may unpack to this many times its upload limit.
MAX_ZIP_EXPANSION = 5
KEEP_IMPORTS_FOR_SECONDS = 7 * 24 * 3600

PERMALINK_STYLES = {
    "date": "/:categories/:year/:month/:day/:title:output_ext",
    "pretty": "/:categories/:year/:month/:day/:title/",
    "ordinal": "/:categories/:year/:y_day/:title:output_ext",
    "weekdate": "/:categories/:year/W:week/:short_day/:title:output_ext",
    "none": "/:categories/:title:output_ext",
}
PROMPT_CALLOUTS = {"tip": "tip", "info": "note", "warning": "warning", "danger": "warning"}

_POST_NAME_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})-(.+)\.([A-Za-z0-9]+)")
_DRAFT_NAME_RE = re.compile(r"(.+)\.([A-Za-z0-9]+)")
_DATE_RE = re.compile(
    r"(\d{4})-(\d{1,2})-(\d{1,2})"
    r"(?:[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?"
    r"\s*(Z|UTC|[+-]\d{1,2}(?::?\d{2})?)?"
)
_FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
_HIGHLIGHT_RE = re.compile(r"\s*\{%-?\s*highlight\s+([\w+#.-]+)[^%]*-?%\}(.*?)\{%-?\s*endhighlight\s*-?%\}", re.S)
_HIGHLIGHT_OPEN_RE = re.compile(r"\s*\{%-?\s*highlight\b")
_HIGHLIGHT_CLOSE_RE = re.compile(r"\{%-?\s*endhighlight\s*-?%\}")
_RAW_MARKER_RE = re.compile(r"\{%-?\s*(raw|endraw)\s*-?%\}")
_COMMENT_RE = re.compile(r"\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}", re.S)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->\n?", re.S)
_POST_URL_RE = re.compile(r"\{%-?\s*post_url\s+([^\s%]+)\s*-?%\}")
_LINK_TAG_RE = re.compile(r"\{%-?\s*link\s+([^\s%]+)\s*-?%\}")
_INCLUDE_RE = re.compile(r"\{%-?\s*include(?:_relative)?\s+([^\s%]+)[^%]*-?%\}")
_LIQUID_TAG_RE = re.compile(r"\{%-?\s*(\w+)[^%]*-?%\}")
_SITE_URL_RE = re.compile(r"\{\{-?\s*site\.(?:baseurl|url)\s*-?\}\}")
_URL_FILTER_RE = re.compile(
    r"""\{\{-?\s*(?:(['"])(.*?)\1|page\.(\w+))\s*\|\s*(?:relative_url|absolute_url|prepend:\s*site\.(?:baseurl|url))\s*-?\}\}"""
)
_LIQUID_OUTPUT_RE = re.compile(r"\{\{-?\s*([^}]*?)\s*-?\}\}")
_TOC_RE = re.compile(r"^(?:[*\-+]|1\.)[ \t]+.*\n\{:[ \t]*\.?toc[^}\n]*\}[ \t]*(?:\n|$)", re.M)
_KRAMDOWN_BLOCK_RE = re.compile(r"\{::comment\}.*?\{:/(?:comment)?\}|\{::options[^}\n]*/\}", re.S)
_KRAMDOWN_MARKER_RE = re.compile(r"\{::nomarkdown\}|\{:/(?:nomarkdown)?\}")
_PROMPT_RE = re.compile(r"((?:^>.*(?:\n|$))+)^\{:[ \t]*\.prompt-(\w+)[ \t]*\}[ \t]*(?:\n|$)", re.M)
_IAL_LINE_RE = re.compile(r"^[ \t]*\{:[^}\n]*\}[ \t]*(?:\n|$)", re.M)
_IAL_INLINE_RE = re.compile(r"\{:[^}\n]*\}")
# A code span can't cross a blank line, so a stray backtick can't swallow the next paragraph.
_INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)((?:(?!\n[ \t]*\n).)+?)(?<!`)\1(?!`)", re.S)
_MD_IMAGE_RE = re.compile(r"""(!\[[^\]\n]*\]\()\s*<?([^\s)<>]+)>?((?:\s+["'(][^)\n]*)?\))""")
_HTML_IMAGE_RE = re.compile(r"""(<img\b[^>]*?\bsrc\s*=\s*["'])([^"']+)(["'])""", re.I)
_REF_IMAGE_RE = re.compile(r"""^( {0,3}\[[^\]\n]+\]:[ \t]*)<?(\S+\.(?:gif|jpe?g|png|svg|webp))>?""", re.I | re.M)
_MATH_RE = re.compile(r"\$\$|\\\[.*?\\\]|\\\(.*?\\\)", re.S)


class ImportError_(Exception):
    """The site or archive can't be imported. The message says why, in plain words."""


@dataclass
class PlannedPost:
    source: str
    title: str
    slug: str
    body: str
    body_format: str
    status: str
    published_at: datetime | None
    updated_at: datetime | None
    excerpt: str = ""
    section: str = ""
    tags: list[str] = field(default_factory=list)
    cover: str = ""
    cover_alt: str = ""
    featured: bool = False
    authors: list[str] = field(default_factory=list)
    old_paths: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    images: dict[str, str] = field(default_factory=dict)
    already_imported: bool = False

    @property
    def new_path(self) -> str:
        return f"/articles/{self.slug}/"


@dataclass
class ImportPlan:
    root: Path
    site_title: str = ""
    posts: list[PlannedPost] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    new_sections: list[str] = field(default_factory=list)
    unmatched_authors: list[str] = field(default_factory=list)

    @property
    def to_import(self) -> list[PlannedPost]:
        return [post for post in self.posts if not post.already_imported]

    @property
    def needing_review(self) -> list[PlannedPost]:
        return [post for post in self.posts if post.notes and not post.already_imported]

    def counts(self) -> dict[str, int]:
        posts = self.to_import
        return {
            "posts": len(self.posts),
            "new": len(posts),
            "published": sum(post.status == "published" for post in posts),
            "drafts": sum(post.status == "draft" for post in posts),
            "already_imported": sum(post.already_imported for post in self.posts),
            "needs_review": len(self.needing_review),
            "images": len({path for post in posts for path in post.images.values()}),
            "skipped": len(self.skipped),
        }


# --------------------------------------------------------------------------- reading files


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ImportError_(f"{path.name} couldn't be read: {exc}") from None
    return data if isinstance(data, dict) else {}


def _split_front_matter(text: str) -> tuple[dict[str, Any], str] | None:
    """Jekyll only treats a file as a post if it starts with a YAML block."""
    match = re.match(r"---[ \t]*\n(.*?)(?:\n)?^(?:---|\.\.\.)[ \t]*(?:\n|\Z)", text, re.S | re.M)
    if not match:
        return None
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise yaml.YAMLError("the front matter isn't a set of named values")
    return data, text[match.end() :]


def find_site_root(folder: Path) -> Path:
    """A site's source, which may sit inside one folder, as GitHub's zip downloads do."""
    candidates = [folder, *sorted(p for p in folder.iterdir() if p.is_dir() and p.name not in SKIPPED_FOLDERS)]
    for candidate in candidates:
        if (candidate / "_config.yml").is_file() or (candidate / "_config.yaml").is_file() or (candidate / "_posts").is_dir():
            return candidate
    raise ImportError_(
        "This doesn't look like a Jekyll site. Use the site's source folder, which has _config.yml and _posts, "
        "not the built _site folder."
    )


def _timezone(config: dict[str, Any]) -> ZoneInfo | None:
    name = config.get("timezone")
    if not name:
        return None
    try:
        return ZoneInfo(str(name))
    except Exception:  # noqa: BLE001 - an unknown or unavailable zone just means UTC
        return None


def _as_utc(value: Any, zone: ZoneInfo | None) -> datetime | None:
    """A front matter date as aware UTC. PyYAML can't read every form Jekyll accepts."""
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime(value.year, value.month, value.day)
    else:
        match = _DATE_RE.fullmatch(str(value or "").strip())
        if not match:
            return None
        year, month, day, hour, minute, second, offset = match.groups()
        try:
            moment = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0))
        except ValueError:
            return None
        if offset:
            moment = datetime.fromisoformat(moment.isoformat() + _offset(offset))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone or UTC)
    return moment.astimezone(UTC)


def _offset(text: str) -> str:
    if text in ("Z", "UTC"):
        return "+00:00"
    sign, digits = text[0], text[1:].replace(":", "")
    digits = digits.zfill(2) if len(digits) <= 2 else digits.zfill(4)
    return f"{sign}{digits[:2]}:{digits[2:] or '00'}"


def _text_list(value: Any) -> list[str]:
    """Jekyll accepts a YAML list or a space-separated string for tags and categories."""
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]


def _defaults_for(config: dict[str, Any], relative: str, kind: str) -> dict[str, Any]:
    """Front matter defaults from _config.yml that apply to this file."""
    merged: dict[str, Any] = {}
    for rule in config.get("defaults") or []:
        if not isinstance(rule, dict):
            continue
        scope = rule.get("scope") or {}
        scope_type = scope.get("type")
        scope_path = str(scope.get("path") or "")
        if scope_type and scope_type != kind and not (kind == "drafts" and scope_type == "posts"):
            continue
        if scope_path and not (relative.startswith(scope_path.rstrip("/") + "/") or fnmatch.fnmatch(relative, scope_path)):
            continue
        values = rule.get("values")
        if isinstance(values, dict):
            merged.update(values)
    return merged


# --------------------------------------------------------------------------- old addresses


def _permalink_template(config: dict[str, Any], front: dict[str, Any]) -> str:
    collections = config.get("collections")
    posts = collections.get("posts") if isinstance(collections, dict) else None
    collection_link = posts.get("permalink") if isinstance(posts, dict) else None
    template = str(front.get("permalink") or collection_link or config.get("permalink") or "date")
    return PERMALINK_STYLES.get(template, template)


def _expand_permalink(template: str, name: str, slug: str, categories: list[str], moment: datetime, zone: ZoneInfo | None) -> str:
    local = moment.astimezone(zone or moment.tzinfo or UTC)
    values = {
        "year": f"{local:%Y}", "short_year": f"{local:%y}", "month": f"{local:%m}", "i_month": str(local.month),
        "short_month": f"{local:%b}", "long_month": f"{local:%B}", "day": f"{local:%d}", "i_day": str(local.day),
        "y_day": f"{local:%j}", "w_year": f"{local:%G}", "week": f"{local:%V}", "w_day": str(local.isoweekday()),
        "short_day": f"{local:%a}", "long_day": f"{local:%A}", "hour": f"{local:%H}", "minute": f"{local:%M}",
        "second": f"{local:%S}", "title": slug, "slug": slugify(slug, 200, slug), "name": name, "basename": name,
        "categories": "/".join(dict.fromkeys(item.lower() for item in categories)),
        "slugified_categories": "/".join(dict.fromkeys(slugify(item, 80, item) for item in categories)),
        "collection": "posts", "output_ext": ".html",
    }
    path = re.sub(r":(\w+)", lambda match: values.get(match.group(1), match.group(0)), template)
    return re.sub(r"/{2,}", "/", "/" + path)


def _old_paths(
    config: dict[str, Any], front: dict[str, Any], name: str, slug: str, categories: list[str],
    moment: datetime, zone: ZoneInfo | None, url_prefix: str, notes: list[str],
) -> list[str]:
    base = str(config.get("baseurl") or "").rstrip("/")
    if base and not base.startswith("/"):
        base = "/" + base
    if base == url_prefix.rstrip("/"):
        base = ""  # This site already answers under the same path, so requests arrive without it.
    template = _permalink_template(config, front)
    paths = [base + _expand_permalink(template, name, slug, categories, moment, zone)]
    for extra in _text_list(front.get("redirect_from")):
        paths.append(base + "/" + extra.lstrip("/"))
    keys: list[str] = []
    for path in paths:
        key = workflow.redirect_key(path)
        if len(key) > 512:
            notes.append("One old address is too long to redirect.")
        elif key and key not in keys:
            keys.append(key)
    return keys


# --------------------------------------------------------------------------- converting text


def _split_code(text: str) -> list[tuple[bool, str]]:
    """Cut text into (is_code, chunk) so conversions never touch fenced or indented code."""
    chunks: list[tuple[bool, str]] = []
    buffer: list[str] = []
    fence: str | None = None
    code = False

    def flush(next_code: bool) -> None:
        nonlocal buffer, code
        if buffer:
            chunks.append((code, "".join(buffer)))
        buffer = []
        code = next_code

    previous_blank = True
    in_indented = False
    in_highlight = False
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\n")
        if in_highlight:
            buffer.append(line)
            if _HIGHLIGHT_CLOSE_RE.search(bare):
                in_highlight = False
                previous_blank = False
                flush(False)
            continue
        if fence:
            buffer.append(line)
            match = _FENCE_RE.fullmatch(bare)
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence) and not match.group(2).strip():
                fence = None
                previous_blank = False
                flush(False)
            continue
        if _HIGHLIGHT_OPEN_RE.match(bare):
            flush(True)
            in_indented = False
            buffer.append(line)
            if _HIGHLIGHT_CLOSE_RE.search(bare):
                previous_blank = False
                flush(False)
            else:
                in_highlight = True
            continue
        match = _FENCE_RE.fullmatch(bare)
        if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            flush(True)
            in_indented = False
            fence = match.group(1)
            buffer.append(line)
            continue
        indented = bare.startswith(("    ", "\t")) and bare.strip() != ""
        if indented and (previous_blank or in_indented):
            if not in_indented:
                flush(True)
            in_indented = True
        elif in_indented and bare.strip():
            in_indented = False
            flush(False)
        buffer.append(line)
        previous_blank = not bare.strip()
    flush(False)
    return chunks


def _outside_inline_code(text: str, convert) -> str:
    """Apply ``convert`` to everything except `inline code`."""
    out: list[str] = []
    position = 0
    for match in _INLINE_CODE_RE.finditer(text):
        out.append(convert(text[position : match.start()]))
        out.append(match.group(0))
        position = match.end()
    out.append(convert(text[position:]))
    return "".join(out)


class _Context:
    """What converting one post needs to know, and where it records what it finds."""

    def __init__(self, title: str, site_title: str, paths: dict[str, str], prefix: str) -> None:
        self.title = title
        self.site_title = site_title
        self.paths = paths
        self.prefix = prefix
        self.notes: dict[str, None] = {}

    def note(self, message: str) -> None:
        self.notes.setdefault(message)


def _post_key(reference: str) -> str:
    """The name a Liquid tag uses for a post, without its folder or extension."""
    name = PurePosixPath(reference.strip("'\"")).name
    return re.sub(r"\.[A-Za-z0-9]+$", "", name)


def _liquid_output(match: re.Match, context: _Context) -> str:
    expression = re.sub(r"\s+", " ", match.group(1)).strip()
    if expression in ("site.title", "site.name"):
        return context.site_title
    if expression == "page.title":
        return context.title
    context.note(f"Remove or replace {{{{ {expression} }}}}: Liquid isn't run on import.")
    return match.group(0)


def _liquid_tag(match: re.Match, context: _Context) -> str:
    context.note(f"Replace the Liquid tag {{% {match.group(1)} %}}: it isn't run on import, so it shows as text.")
    return match.group(0)


def _convert_prose(text: str, context: _Context, protected: list[str]) -> str:
    """Rewrite Liquid and kramdown in text that isn't code. Inline code is held back first."""

    def hold_code(match: re.Match) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    text = _INLINE_CODE_RE.sub(hold_code, text)

    def resolve_post(match: re.Match) -> str:
        key = _post_key(match.group(1))
        target = context.paths.get(key)
        if target:
            return target
        context.note(f"The link to {key} couldn't be resolved, because that post isn't part of this import.")
        return match.group(0)

    def resolve_link(match: re.Match) -> str:
        reference = match.group(1).strip("'\"")
        if "_posts/" in reference or "_drafts/" in reference:
            return resolve_post(match)
        return "/" + reference.lstrip("/")

    def run(part: str) -> str:
        part = _POST_URL_RE.sub(resolve_post, part)
        part = _LINK_TAG_RE.sub(resolve_link, part)
        part = _URL_FILTER_RE.sub(lambda m: m.group(2) or "", part)
        part = _SITE_URL_RE.sub("", part)
        for match in _INCLUDE_RE.finditer(part):
            context.note(f"Replace {{% include {match.group(1)} %}}: includes aren't run on import, so it shows as text.")
        part = _LIQUID_TAG_RE.sub(lambda m: m.group(0) if m.group(1) in ("include", "include_relative") else _liquid_tag(m, context), part)
        part = _LIQUID_OUTPUT_RE.sub(lambda m: _liquid_output(m, context), part)
        return _IAL_INLINE_RE.sub("", part)

    if _MATH_RE.search(text):
        context.note("This post seems to use math. QuillSail doesn't render math, so it shows as plain text.")
    text = _COMMENT_RE.sub("", text)
    text = _HTML_COMMENT_RE.sub("", text)
    text = _KRAMDOWN_BLOCK_RE.sub("", text)
    text = _KRAMDOWN_MARKER_RE.sub("", text)
    text = _TOC_RE.sub("", text)

    def prompt(match: re.Match) -> str:
        kind = PROMPT_CALLOUTS.get(match.group(2).lower(), "note")
        lines = [re.sub(r"^> ?", "", line) for line in match.group(1).splitlines()]
        return f"::: {kind}\n" + "\n".join(lines) + "\n:::\n"

    text = _PROMPT_RE.sub(prompt, text)
    text = _IAL_LINE_RE.sub("", text)
    return run(text)


def _highlight_to_fence(match: re.Match) -> str:
    language, code = match.group(1), match.group(2).strip("\n")
    code = _RAW_MARKER_RE.sub("", code)
    runs = re.findall(r"^`{3,}", code, re.M)
    ticks = "`" * max([3] + [len(run) + 1 for run in runs])
    return f"{ticks}{language}\n{code}\n{ticks}"


def convert_body(text: str, context: _Context) -> str:
    """Turn a Jekyll post body into Markdown QuillSail renders. Code is left exactly as written."""
    protected: list[str] = []
    out: list[str] = []
    in_raw = False
    for is_code, chunk in _split_code(text.replace("\r\n", "\n")):
        if is_code:
            if _HIGHLIGHT_OPEN_RE.match(chunk):
                out.append(_HIGHLIGHT_RE.sub(_highlight_to_fence, chunk))
            else:
                # Jekyll never shows the {% raw %} markers themselves, not even inside code.
                out.append(_RAW_MARKER_RE.sub("", chunk))
            continue
        # A {% raw %} can wrap a whole code block, so its state carries across chunks.
        pieces = _RAW_MARKER_RE.split(chunk)
        for index, piece in enumerate(pieces):
            if index % 2:
                in_raw = piece == "raw"
            elif in_raw:
                protected.append(piece)
                out.append(f"\x00{len(protected) - 1}\x00")
            else:
                out.append(_convert_prose(piece, context, protected))
    result = "".join(out)
    return re.sub(r"\x00(\d+)\x00", lambda match: protected[int(match.group(1))], result)


class _HtmlScanner(HTMLParser):
    """Which typed tags the sanitizer will remove, so the report can say so."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.removed: dict[str, None] = {}
        self.frames: dict[str, None] = {}

    def handle_starttag(self, tag, attrs):
        if tag not in AUTHORED_TAGS:
            self.removed.setdefault(tag)
        elif tag == "iframe":
            src = dict(attrs).get("src") or ""
            if not embed_url(src):
                self.frames.setdefault(src or "(no address)")


def _review_html(body: str, is_html: bool, context: _Context) -> bool:
    """Flag HTML that won't survive. True if the text has any typed HTML at all."""
    if is_html:
        pieces = [body]
    else:
        tokens, _env = markdown_tokens(body, kind="markdown_html")
        pieces = [t.content for t in tokens if t.type == "html_block"]
        for token in tokens:
            pieces.extend(c.content for c in (token.children or []) if c.type == "html_inline")
    if not pieces:
        return False
    scanner = _HtmlScanner()
    for piece in pieces:
        scanner.feed(piece)
    scanner.close()
    if scanner.removed:
        tags = ", ".join(f"<{tag}>" for tag in scanner.removed)
        context.note(f"These HTML tags are removed when the post is shown: {tags}. Check that the post still reads well.")
    for src in scanner.frames:
        context.note(f"This embed is removed, because only YouTube and Vimeo are allowed: {src}")
    return True


def _image_targets(body: str) -> list[str]:
    """Image addresses in the post, skipping anything inside code."""
    found: list[str] = []
    for is_code, chunk in _split_code(body):
        if is_code:
            continue

        def collect(part: str) -> str:
            found.extend(m.group(2) for m in _MD_IMAGE_RE.finditer(part))
            found.extend(m.group(2) for m in _HTML_IMAGE_RE.finditer(part))
            found.extend(m.group(2) for m in _REF_IMAGE_RE.finditer(part))
            return part

        _outside_inline_code(chunk, collect)
    return list(dict.fromkeys(found))


def rewrite_images(body: str, addresses: dict[str, str]) -> str:
    """Point images at their uploaded copies, again leaving code alone."""

    def swap(match: re.Match) -> str:
        new = addresses.get(match.group(2))
        return f"{match.group(1)}{new}{match.group(3)}" if new else match.group(0)

    def swap_reference(match: re.Match) -> str:
        new = addresses.get(match.group(2))
        return f"{match.group(1)}{new}" if new else match.group(0)

    def apply(part: str) -> str:
        part = _MD_IMAGE_RE.sub(swap, part)
        part = _HTML_IMAGE_RE.sub(swap, part)
        return _REF_IMAGE_RE.sub(swap_reference, part)

    out = [chunk if is_code else _outside_inline_code(chunk, apply) for is_code, chunk in _split_code(body)]
    return "".join(out)


def _find_image(root: Path, target: str, post_dir: Path, media_path: str) -> Path | None:
    """The local file an image address means. Never anything outside the site's folder."""
    clean = target.split("#")[0].split("?")[0]
    if not clean or re.match(r"[a-z][a-z0-9+.-]*:|//", clean, re.I):
        return None
    candidates = []
    if clean.startswith("/"):
        candidates.append(root / clean.lstrip("/"))
        if media_path:
            candidates.append(root / media_path.strip("/") / clean.lstrip("/"))
    else:
        if media_path:
            candidates.append(root / media_path.strip("/") / clean)
        candidates.extend([post_dir / clean, root / clean])
    resolved_root = root.resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and resolved.is_relative_to(resolved_root):
            return resolved
    return None


# --------------------------------------------------------------------------- planning


def _reserve_slug(wanted: str, taken: set[str]) -> str:
    base = slugify(wanted, 100, "untitled")
    candidate, number = base, 2
    while candidate in taken or workflow.slug_exists(candidate):
        candidate = f"{base}-{number}"
        number += 1
    taken.add(candidate)
    return candidate


def _post_files(root: Path) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if any(part in SKIPPED_FOLDERS for part in parts):
            continue
        if "_posts" in parts:
            found.append((path, "posts"))
        elif parts[0] == "_drafts":
            found.append((path, "drafts"))
    return found


def _authors_from(front: dict[str, Any], people: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for value in _text_list(front.get("authors")) or ([] if front.get("author") is None else [front["author"]]):
        if isinstance(value, dict):
            value = value.get("name") or ""
        person = people.get(str(value))
        names.append(str(person.get("name") or value) if isinstance(person, dict) else str(value))
    return [name for name in names if name]


def plan_import(root: Path, *, now: datetime | None = None) -> ImportPlan:
    """Work out exactly what an import would do. This writes nothing."""
    root = find_site_root(root)
    config = _read_yaml(root / "_config.yml") or _read_yaml(root / "_config.yaml")
    people = _read_yaml(root / "_data" / "authors.yml")
    zone = _timezone(config)
    now = now or datetime.now(UTC)
    url_prefix = state().config.url_prefix or ""
    plan = ImportPlan(root=root, site_title=str(config.get("title") or ""))
    taken: set[str] = set()

    # The first pass gives every post its address, so {% post_url %} can point anywhere.
    drafts: list[dict[str, Any]] = []
    for path, kind in _post_files(root):
        relative = path.relative_to(root).as_posix()
        extension = path.suffix.lstrip(".").lower()
        if extension not in MARKDOWN_EXTENSIONS | HTML_EXTENSIONS:
            if extension not in IMAGE_EXTENSIONS and not path.name.startswith("."):
                plan.skipped.append({"file": relative, "reason": "It isn't a Markdown or HTML post."})
            continue
        match = (_POST_NAME_RE if kind == "posts" else _DRAFT_NAME_RE).fullmatch(path.name)
        if not match:
            plan.skipped.append({"file": relative, "reason": "Its name doesn't start with a date, so Jekyll doesn't publish it."})
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            plan.skipped.append({"file": relative, "reason": "It isn't plain UTF-8 text."})
            continue
        if len(text) > MAX_POST_CHARACTERS:
            plan.skipped.append({"file": relative, "reason": "It's longer than the 200,000 characters a post can hold."})
            continue
        try:
            split = _split_front_matter(text.replace("\r\n", "\n"))
        except yaml.YAMLError as exc:
            reason = str(exc).splitlines()[0][:160]
            plan.skipped.append({"file": relative, "reason": f"Its front matter couldn't be read: {reason}"})
            continue
        if split is None:
            plan.skipped.append({"file": relative, "reason": "It has no front matter, so Jekyll doesn't treat it as a post."})
            continue
        front = {**_defaults_for(config, relative, kind), **split[0]}
        name = match.group(4) if kind == "posts" else match.group(1)
        slug_source = str(front.get("slug") or name)
        drafts.append({
            "path": path, "kind": kind, "relative": relative, "front": front, "name": name,
            "slug_source": slug_source, "body": split[1], "is_html": extension in HTML_EXTENSIONS,
            "file_date": match.groups()[:3] if kind == "posts" else None,
        })

    # Addresses first: a post already imported keeps its article, so links to it stay right.
    addresses: dict[str, str] = {}
    for item in drafts:
        notes: list[str] = []
        moment = _as_utc(item["front"].get("date"), zone)
        if item["front"].get("date") and moment is None and item["file_date"]:
            notes.append("Its date couldn't be read, so the date in the file name was used.")
        if moment is None and item["file_date"]:
            year, month, day = item["file_date"]
            try:
                moment = datetime(int(year), int(month), int(day), tzinfo=zone or UTC).astimezone(UTC)
            except ValueError:
                moment = None
        if moment is None and item["kind"] == "posts":
            plan.skipped.append({"file": item["relative"], "reason": "Its date couldn't be read."})
            item["skip"] = True
            continue
        categories = [
            part for part in PurePosixPath(item["relative"]).parts[:-1]
            if part not in ("_posts", "_drafts")
        ] + _text_list(item["front"].get("categories")) + _text_list(item["front"].get("category"))
        categories = list(dict.fromkeys(categories))
        if item["kind"] == "posts":
            keys = _old_paths(config, item["front"], item["name"], item["slug_source"], categories, moment, zone, url_prefix, notes)
        else:
            keys = [workflow.redirect_key(f"/_drafts/{item['name']}")]
        existing = db.session.scalar(select(ArticleRedirect).where(ArticleRedirect.old_path.in_(keys))) if keys else None
        if existing is not None:
            slug = existing.article.slug
        else:
            slug = _reserve_slug(item["slug_source"], taken)
        item.update(moment=moment, categories=categories, keys=keys, slug=slug, notes=notes, imported=existing is not None)
        path_for_links = f"{url_prefix.rstrip('/')}/articles/{slug}/"
        addresses[item["name"]] = path_for_links
        if item["file_date"]:
            year, month, day = item["file_date"]
            addresses[f"{year}-{month}-{day}-{item['name']}"] = path_for_links

    seen_paths: dict[str, str] = {}
    existing_sections = {
        section.slug for section in db.session.scalars(select(Section)).all()
    }
    new_sections: dict[str, None] = {}
    unmatched: dict[str, None] = {}
    for item in drafts:
        if item.get("skip"):
            continue
        front = item["front"]
        title = str(front.get("title") or item["name"].replace("-", " ").title()).strip()
        notes = item["notes"]
        if len(title) > 200:
            notes.append("Its title was shortened to 200 characters.")
            title = title[:200]
        context = _Context(title, plan.site_title, addresses, url_prefix)
        body = convert_body(item["body"], context)
        has_html = _review_html(body, item["is_html"], context)
        body_format = "html" if item["is_html"] else ("markdown_html" if has_html else "markdown")
        notes.extend(context.notes)

        moment = item["moment"]
        status = "published"
        if item["kind"] == "drafts" or front.get("published") is False:
            status = "draft"
        elif moment > now:
            status = "draft"
            notes.append("It's dated in the future, so it comes in as a draft. QuillSail doesn't schedule posts.")

        for key in item["keys"]:
            if key in seen_paths and seen_paths[key] != item["relative"]:
                notes.append(f"Another post in this site also used the address {key}, so that one keeps it.")
        keys = [key for key in item["keys"] if seen_paths.setdefault(key, item["relative"]) == item["relative"]]

        categories = item["categories"]
        section = categories[0] if categories else ""
        tags = list(dict.fromkeys(_text_list(front.get("tags")) + _text_list(front.get("tag")) + categories[1:]))
        if len(tags) > MAX_TAGS:
            notes.append(f"Only the first {MAX_TAGS} of its {len(tags)} tags were kept.")
            tags = tags[:MAX_TAGS]
        if section and slugify(section, 60, "") not in existing_sections and not item["imported"]:
            new_sections.setdefault(section)

        image = front.get("image")
        cover = str(image.get("path") or "") if isinstance(image, dict) else str(image or "")
        cover_alt = str(image.get("alt") or "") if isinstance(image, dict) else ""
        media_path = str(front.get("media_subpath") or front.get("img_path") or "")

        post_dir = item["path"].parent
        images: dict[str, str] = {}
        for target in _image_targets(body) + ([cover] if cover else []):
            found = _find_image(root, target, post_dir, media_path)
            if found is None:
                if not re.match(r"[a-z][a-z0-9+.-]*:|//", target, re.I):
                    notes.append(f"The image {target} wasn't found in the site's files.")
                continue
            if found.suffix.lower() == ".svg":
                notes.append(f"The image {target} is an SVG, which can't be uploaded. Replace it with a PNG or JPEG.")
                continue
            images[target] = str(found)
        if cover and not cover_alt and cover in images:
            notes.append("Its cover image has no description. Add one for people using screen readers.")

        authors = _authors_from(front, people)
        for name in authors:
            if _find_user(name) is None:
                unmatched.setdefault(name)

        updated = _as_utc(front.get("last_modified_at"), zone) if front.get("last_modified_at") else None
        description = str(front.get("description") or front.get("excerpt") or "").strip()
        plan.posts.append(PlannedPost(
            source=item["relative"], title=title, slug=item["slug"], body=body, body_format=body_format,
            status=status, published_at=moment.replace(tzinfo=None) if moment else None,
            updated_at=updated.replace(tzinfo=None) if updated else None, excerpt=description[:MAX_EXCERPT],
            section=section, tags=tags, cover=cover if cover in images else "", cover_alt=cover_alt[:300],
            featured=front.get("pin") is True, authors=authors, old_paths=keys,
            notes=list(dict.fromkeys(notes)), images=images, already_imported=item["imported"],
        ))
    plan.posts.sort(key=lambda post: post.published_at or datetime.max, reverse=True)
    plan.new_sections = list(new_sections)
    plan.unmatched_authors = list(unmatched)
    return plan


def _find_user(name: str) -> User | None:
    lowered = name.strip().lower()
    if not lowered:
        return None
    return db.session.scalar(
        select(User).where(
            (func.lower(User.username) == lowered) | (func.lower(User.display_name) == lowered) | (func.lower(User.email) == lowered),
            User.deleted_at.is_(None),
        ).limit(1)
    )


# --------------------------------------------------------------------------- importing


@dataclass
class ImportResult:
    imported: list[dict[str, str]] = field(default_factory=list)
    skipped: int = 0
    failed: list[dict[str, str]] = field(default_factory=list)
    images: int = 0


def _section_id(name: str) -> int | None:
    if not name:
        return None
    slug = slugify(name, 60, "")
    if not slug:
        return None
    section = db.session.scalar(select(Section).where(Section.slug == slug))
    if section is None:
        section = Section(slug=slug, name=name[:80])
        db.session.add(section)
        db.session.flush()
    return section.id


def _upload_images(post: PlannedPost, actor: User, cache: dict[str, str], added: list[str]) -> tuple[dict[str, str], str]:
    """Store each of a post's images once. Returns new addresses, and the cover's stored path."""
    addresses: dict[str, str] = {}
    cover_path = ""
    for target, file_path in post.images.items():
        stored = cache.get(file_path)
        if stored is None:
            path = Path(file_path)
            try:
                with path.open("rb") as stream:
                    prepared = uploads.prepare_image(FileStorage(stream=stream, filename=path.name))
            except (OSError, uploads.UploadError) as exc:
                post.notes.append(f"The image {target} couldn't be used: {exc}")
                continue
            stored = uploads.store_image(prepared, path.name, actor.id).path
            cache[file_path] = stored
            added.append(file_path)
        addresses[target] = url_for("public.upload", path=stored, _external=False)
        if target == post.cover:
            cover_path = stored
    return addresses, cover_path


def _import_post(post: PlannedPost, actor: User, as_drafts: bool, cache: dict[str, str], added: list[str]) -> None:
    addresses, cover_path = _upload_images(post, actor, cache, added)
    authors = [user for user in (_find_user(name) for name in post.authors) if user]
    status = "draft" if as_drafts else post.status
    article = workflow.import_article(
        actor=actor,
        authors=list(dict.fromkeys(authors)) or [actor],
        title=post.title,
        slug=post.slug,
        body=rewrite_images(post.body, addresses),
        body_format=post.body_format,
        status=status,
        # A post brought in as a draft keeps its original date for when it's published.
        published_at=post.published_at if post.status == "published" else None,
        updated_at=post.updated_at,
        excerpt=post.excerpt,
        section_id=_section_id(post.section),
        cover_image=cover_path,
        cover_alt=post.cover_alt,
        featured=post.featured,
        tags=post.tags,
        source=post.source,
    )
    for key in post.old_paths:
        db.session.add(ArticleRedirect(old_path=key, article_id=article.id))


def run_import(plan: ImportPlan, actor: User, *, as_drafts: bool = False, progress=None) -> ImportResult:
    """Create the planned posts, one transaction each. Safe to run again after a failure."""
    result = ImportResult()
    cache: dict[str, str] = {}
    actor_id = actor.id
    for post in plan.posts:
        if post.already_imported or _already_imported(post):
            result.skipped += 1
        else:
            added: list[str] = []
            try:
                _import_post(post, db.session.get(User, actor_id), as_drafts, cache, added)
                db.session.commit()
            except IntegrityError as exc:
                db.session.rollback()
                for file_path in added:
                    cache.pop(file_path, None)
                log.warning("Couldn't import %s: %s", post.source, exc)
                result.failed.append({"file": post.source, "reason": "Its address or web address is already in use."})
            except Exception as exc:  # noqa: BLE001 - one bad post must not stop the others
                db.session.rollback()
                for file_path in added:
                    cache.pop(file_path, None)
                log.exception("Couldn't import %s", post.source)
                result.failed.append({"file": post.source, "reason": str(exc)[:200]})
            else:
                result.imported.append({"title": post.title, "slug": post.slug, "status": "draft" if as_drafts else post.status})
                result.images += len(added)
        if progress:
            progress(result)
    return result


def _already_imported(post: PlannedPost) -> bool:
    if not post.old_paths:
        return False
    return db.session.scalar(select(ArticleRedirect.id).where(ArticleRedirect.old_path.in_(post.old_paths)).limit(1)) is not None


# --------------------------------------------------------------------------- zip files


def extract_zip(archive: Path | Any, destination: Path, *, max_unpacked: int) -> None:
    """Unpack a site. Anything unsafe rejects the whole file instead of being skipped."""
    try:
        bundle = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError, ValueError):
        raise ImportError_("That file isn't a zip archive. Zip the site's source folder and try again.") from None
    with bundle:
        entries = bundle.infolist()
        if len(entries) > MAX_ZIP_FILES:
            raise ImportError_(f"That zip has more than {MAX_ZIP_FILES:,} files. Remove anything the site doesn't need, such as node_modules.")
        if sum(entry.file_size for entry in entries) > max_unpacked:
            raise ImportError_(f"That zip unpacks to more than {max_unpacked // (1024 * 1024):,} MB. Remove anything the site doesn't need, then try again.")
        safe: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        for entry in entries:
            name = entry.filename
            path = PurePosixPath(name)
            if "\\" in name or "\x00" in name or path.is_absolute() or ".." in path.parts or re.match(r"[A-Za-z]:", name):
                raise ImportError_("That zip contains a file with an unsafe path, so it wasn't opened.")
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ImportError_("That zip contains a symbolic link, so it wasn't opened.")
            if entry.flag_bits & 0x1:
                raise ImportError_("That zip is password protected. Zip the folder without a password.")
            if not entry.is_dir() and not (set(path.parts) & SKIPPED_FOLDERS) and path.name != ".DS_Store":
                safe.append((entry, path))
        written = 0
        root = destination.resolve()
        for entry, path in safe:
            target = (destination / Path(*path.parts)).resolve()
            if not target.is_relative_to(root):
                raise ImportError_("That zip contains a file with an unsafe path, so it wasn't opened.")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with bundle.open(entry) as source, target.open("wb") as output:
                    while chunk := source.read(1024 * 256):
                        written += len(chunk)
                        if written > max_unpacked:
                            raise ImportError_(f"That zip unpacks to more than {max_unpacked // (1024 * 1024):,} MB.")
                        output.write(chunk)
            except (zipfile.BadZipFile, EOFError, NotImplementedError, RuntimeError, zlib.error):
                raise ImportError_("That zip is damaged, so it wasn't opened.") from None


# --------------------------------------------------------------------------- dashboard uploads


def imports_dir() -> Path:
    return state().config.data_dir / "imports"


def import_folder(token: str) -> Path | None:
    """The folder for one uploaded site. Tokens come from URLs, so they're checked first."""
    if not re.fullmatch(r"[\w-]{10,60}", token or "", re.A):
        return None
    folder = imports_dir() / token
    return folder if folder.is_dir() else None


def save_upload(stream: Any) -> str:
    """Unpack an uploaded zip into a new private folder and return its token."""
    token = random_token(18)
    folder = imports_dir() / token
    folder.mkdir(parents=True)
    limit = state().config.max_import_mb * 1024 * 1024 * MAX_ZIP_EXPANSION
    try:
        extract_zip(stream, folder / "source", max_unpacked=limit)
        if not (folder / "source").is_dir():
            raise ImportError_("That zip is empty.")
    except ImportError_:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return token


def read_status(folder: Path) -> dict[str, Any] | None:
    try:
        return json.loads((folder / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_status(folder: Path, **values: Any) -> None:
    current = read_status(folder) or {}
    current.update(values)
    temporary = folder / "status.json.tmp"
    temporary.write_text(json.dumps(current, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(folder / "status.json")


def remove_stale_imports() -> None:
    """Drop uploaded sites nobody confirmed, and finished reports, after a week."""
    base = imports_dir()
    if not base.is_dir():
        return
    cutoff = datetime.now(UTC).timestamp() - KEEP_IMPORTS_FOR_SECONDS
    for folder in base.iterdir():
        try:
            if folder.is_dir() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            continue


@jobs.handler("jekyll.import")
def _import_job(payload: dict[str, Any]) -> None:
    folder = import_folder(str(payload.get("token") or ""))
    actor = db.session.get(User, payload.get("actor_id"))
    if folder is None or actor is None:
        return
    source = folder / "source"
    if not source.is_dir():
        return
    write_status(folder, state="running", started_at=utcnow().isoformat(timespec="seconds"))
    try:
        plan = plan_import(source)
    except ImportError_ as exc:
        write_status(folder, state="failed", error=str(exc))
        return

    def progress(result: ImportResult) -> None:
        jobs.renew_lease()
        db.session.commit()
        write_status(folder, imported=len(result.imported), failed=len(result.failed), total=len(plan.posts))

    result = run_import(plan, actor, as_drafts=bool(payload.get("as_drafts")), progress=progress)
    from copydesk import audit

    audit.record(
        "article.imported_site", None, actor=db.session.get(User, payload.get("actor_id")),
        label=plan.site_title or "a Jekyll site",
        details={"imported": len(result.imported), "skipped": result.skipped, "failed": len(result.failed)},
    )
    db.session.commit()
    write_status(
        folder, state="done", finished_at=utcnow().isoformat(timespec="seconds"), result=asdict(result),
        posts=[{"title": post.title, "notes": post.notes} for post in plan.needing_review],
    )
    shutil.rmtree(source, ignore_errors=True)
