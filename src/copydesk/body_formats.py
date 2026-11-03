"""Converting an article between its writing formats.

Markdown to HTML is safe: it's what the site renders anyway. HTML to Markdown can
lose formatting Markdown can't express, so the conversion reports exactly what
changes, and the editor shows that before anything happens to the writer's text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from copydesk.text import markdown_tokens, media_link, render_source, sanitize_authored

_VOID = {"br", "hr", "img", "input", "source", "track", "wbr"}
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_MEDIA = {"audio": "Listen", "iframe": "Watch the video", "video": "Watch the video"}
_BLOCKS = {
    "aside", "audio", "blockquote", "caption", "dd", "details", "div", "dl", "dt", "figcaption",
    "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "iframe", "ol", "p", "pre", "section",
    "summary", "table", "ul", "video",
}
# Wrappers with no look of their own, so removing them changes nothing a reader sees.
_PLAIN_WRAPPERS = {"div", "section", "span", "wbr"}
_LINE_START_RE = re.compile(r"(#{1,6}(?=\s|$)|>|[-+](?=\s|$)|=+\s*$|-+\s*$|:::|\|)")
_LINE_START_NUMBER_RE = re.compile(r"(\d{1,9})([.)])(?=\s|$)")
_ENTITY_RE = re.compile(r"&(?=#?\w+;)")
_UNDERSCORE_RE = re.compile(r"(?<![^\W_])_|_(?![^\W_])")
_FOOTNOTE_ID_RE = re.compile(r"fn(\d+)")
_NUMBERED_NOT_ONE_RE = re.compile(r"(?!1[.)])\d+[.)] ")


@dataclass
class Conversion:
    body: str
    warnings: list[str] = field(default_factory=list)


class _Node:
    def __init__(self, tag: str, attrs: dict[str, str | None] | None = None) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[Any] = []

    @property
    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)


class _TreeBuilder(HTMLParser):
    """Sanitized HTML is well formed, so a simple stack is enough."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if tag not in _VOID and any(node.tag == tag for node in self.stack[1:]):
            while self.stack.pop().tag != tag:
                pass

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _escape(text: str, in_link: bool = False) -> str:
    """Backslash-escape what Markdown would read as formatting, and nothing else."""
    text = re.sub(r"([\\`*\[\]])" if in_link else r"([\\`*\[])", r"\\\1", text)
    text = re.sub(r"<(?=[A-Za-z/!?])", r"\\<", text)
    text = re.sub(r"~(?=~|$)|^~", r"\\~", text)
    text = _ENTITY_RE.sub(r"\\&", text)
    return _UNDERSCORE_RE.sub(r"\\_", text)


def _escape_line_start(text: str) -> str:
    if _LINE_START_RE.match(text):
        return f"\\{text}"
    return _LINE_START_NUMBER_RE.sub(r"\1\\\2", text, count=1)


def _url(value: str) -> str:
    if re.search(r"[\s()<>]", value):
        return "<" + value.replace("<", "%3C").replace(">", "%3E").replace("\n", "") + ">"
    return value


def _title(value: str | None) -> str:
    if not value:
        return ""
    return ' "' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _code_span(text: str) -> str:
    runs = re.findall(r"`+", text)
    fence = "`" * (max((len(run) for run in runs), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") or (text[:1] == text[-1:] == " " and text.strip()) else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _fence(code: str, info: str = "") -> str:
    code = code[:-1] if code.endswith("\n") else code
    runs = re.findall(r"^ {0,3}(`{3,})", code, re.M)
    fence = "`" * max([3] + [len(run) + 1 for run in runs])
    return f"{fence}{info}\n{code}\n{fence}"


def _indent(text: str, prefix: str, first: str | None = None) -> str:
    lines = text.split("\n")
    out = []
    for index, line in enumerate(lines):
        lead = first if index == 0 and first is not None else prefix
        out.append(lead + line if line else lead.rstrip() if index == 0 else "")
    return "\n".join(out)


class _MarkdownWriter:
    def __init__(self) -> None:
        self.warnings: dict[str, None] = {}
        self.link_depth = 0

    def warn(self, message: str) -> None:
        self.warnings.setdefault(message)

    def lost(self, tag: str) -> None:
        self.warn(f"<{tag}> isn't available in Markdown. Its text stays, without that formatting.")

    # ---------------------------------------------------------------- inline

    def inline(self, children: list[Any]) -> str:
        return "".join(self._inline_one(child) for child in children)

    def _wrap(self, node: _Node, delimiter: str) -> str:
        content = self.inline(node.children)
        stripped = content.strip()
        if not stripped:
            return content
        lead = content[: len(content) - len(content.lstrip())]
        tail = content[len(content.rstrip()) :]
        return f"{lead}{delimiter}{stripped}{delimiter}{tail}"

    def _inline_one(self, node: Any) -> str:
        if isinstance(node, str):
            return _escape(re.sub(r"\s+", " ", node), self.link_depth > 0)
        tag = node.tag
        if tag in ("strong", "b"):
            return self._wrap(node, "**")
        if tag in ("em", "i"):
            return self._wrap(node, "*")
        if tag in ("del", "s"):
            return self._wrap(node, "~~")
        if tag == "code":
            return _code_span(node.text())
        if tag == "br":
            return "\\\n"
        if tag == "a":
            if "footnote-backref" in node.classes:
                return ""
            href = node.attrs.get("href")
            self.link_depth += 1
            label = self.inline(node.children)
            self.link_depth -= 1
            if not href:
                return label
            return f"[{label}]({_url(href)}{_title(node.attrs.get('title'))})"
        if tag == "img":
            return self._image(node)
        if tag == "sup" and "footnote-ref" in node.classes:
            anchor = next((c for c in node.children if isinstance(c, _Node) and c.tag == "a"), None)
            match = anchor and _FOOTNOTE_ID_RE.fullmatch((anchor.attrs.get("href") or "").lstrip("#"))
            if match:
                return f"[^{match.group(1)}]"
        if tag in _MEDIA:
            return self._media(node)
        if tag == "input":
            return ""
        if tag not in _PLAIN_WRAPPERS:
            self.lost(tag)
        return self.inline(node.children)

    def _image(self, node: _Node) -> str:
        if node.attrs.get("width") or node.attrs.get("height"):
            self.warn("Image sizes can't be set in Markdown, so images use their natural size.")
        alt = (node.attrs.get("alt") or "").replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
        return f"![{alt}]({_url(node.attrs.get('src') or '')}{_title(node.attrs.get('title'))})"

    def _media(self, node: _Node) -> str:
        source = node.attrs.get("src")
        if not source:
            child = next((c for c in node.children if isinstance(c, _Node) and c.tag == "source"), None)
            source = child.attrs.get("src") if child else None
        if not source:
            return ""
        self.warn("Markdown can't embed video or audio, so each one becomes a link.")
        return f"[{_MEDIA[node.tag]}]({_url(media_link(source))})"

    # ---------------------------------------------------------------- blocks

    def blocks(self, children: list[Any]) -> list[str]:
        out: list[str] = []
        run: list[Any] = []

        def flush() -> None:
            text = re.sub(r" *\\\n\s*", "\\\n", self.inline(run).strip())
            if text:
                out.append(_escape_line_start(text))
            run.clear()

        for child in children:
            if isinstance(child, _Node) and child.tag in _BLOCKS:
                flush()
                out.extend(self._block(child))
            else:
                run.append(child)
        flush()
        return out

    def _block(self, node: _Node) -> list[str]:
        tag = node.tag
        if tag in _HEADINGS:
            text = self.inline(node.children).replace("\\\n", " ").strip()
            text = re.sub(r"(^|[^\\#])(#+)$", r"\1\\\2", text)
            return [f"{'#' * _HEADINGS[tag]} {text}"] if text else []
        if tag == "hr":
            return [] if "footnotes-sep" in node.classes else ["---"]
        if tag == "p":
            return self.blocks(node.children)
        if tag == "blockquote":
            lines = "\n\n".join(self.blocks(node.children)).split("\n")
            return ["\n".join(f"> {line}" if line else ">" for line in lines)]
        if tag in ("ul", "ol"):
            return [self._list(node)]
        if tag == "pre":
            return [self._pre(node)]
        if tag == "table":
            return [self._table(node)]
        if tag == "aside" and "callout" in node.classes:
            return [self._callout(node)]
        if tag == "section" and "footnotes" in node.classes:
            return self._footnotes(node)
        if tag in _MEDIA:
            link = self._media(node)
            return [link] if link else []
        if tag == "details":
            self.warn("Collapsible sections (<details>) become ordinary, open text.")
            return self.blocks(node.children)
        if tag == "summary":
            text = self.inline(node.children).strip()
            return [f"**{text}**"] if text else []
        if tag not in _PLAIN_WRAPPERS:
            self.lost(tag)
        return self.blocks(node.children)

    def _pre(self, node: _Node) -> str:
        code = next((c for c in node.children if isinstance(c, _Node) and c.tag == "code"), None)
        language = next(
            (c.removeprefix("language-") for c in (code.classes if code else []) if c.startswith("language-")), ""
        )
        return _fence(node.text(), language)

    def _list(self, node: _Node) -> str:
        items = [c for c in node.children if isinstance(c, _Node) and c.tag == "li"]
        tight = not any(
            isinstance(c, _Node) and c.tag == "p" for item in items for c in item.children
        )
        start = int(node.attrs.get("start") or 1) if (node.attrs.get("start") or "1").isdecimal() else 1
        rendered = []
        for index, item in enumerate(items):
            marker = f"{start + index}. " if node.tag == "ol" else "- "
            children, task = self._task(item)
            parts = self.blocks(children)
            body = ""
            for position, part in enumerate(parts):
                # Only a list starting at 1 can follow a line directly.
                follows = tight and not _NUMBERED_NOT_ONE_RE.match(part)
                body += ("\n" if follows else "\n\n") * bool(position) + part
            if task and parts:
                body = f"{task} {body}"
            rendered.append(_indent(body, " " * len(marker), marker) if body else marker.rstrip())
        return ("\n" if tight else "\n\n").join(rendered)

    def _task(self, item: _Node) -> tuple[list[Any], str]:
        """Pull a task list's checkbox off the front of an item."""
        container = item
        first = next((c for c in item.children if not (isinstance(c, str) and not c.strip())), None)
        if isinstance(first, _Node) and first.tag == "p":
            container = first
            first = next((c for c in first.children if not (isinstance(c, str) and not c.strip())), None)
        if not (isinstance(first, _Node) and first.tag == "input"):
            return item.children, ""
        container.children.remove(first)
        return item.children, "[x]" if "checked" in first.attrs else "[ ]"

    def _table(self, node: _Node) -> str:
        rows: list[_Node] = []

        def collect(parent: _Node) -> None:
            for child in parent.children:
                if isinstance(child, _Node):
                    if child.tag == "tr":
                        rows.append(child)
                    elif child.tag in ("thead", "tbody", "tfoot"):
                        collect(child)
                    elif child.tag == "caption":
                        self.warn("Markdown tables can't have captions, so the caption is removed.")

        collect(node)
        if not rows:
            return ""
        table = []
        aligns: list[str] = []
        for row in rows:
            cells = [c for c in row.children if isinstance(c, _Node) and c.tag in ("td", "th")]
            texts = []
            for cell in cells:
                if cell.attrs.get("colspan") or cell.attrs.get("rowspan"):
                    self.warn("Markdown tables can't merge cells, so merged cells are split.")
                text = re.sub(r"\s*\n\s*", " ", self.inline(cell.children).replace("\\\n", " ")).strip()
                texts.append(text.replace("|", "\\|"))
            if not table:
                aligns = [next((k for k in ("left", "right", "center") if f"align-{k}" in c.classes), "") for c in cells]
            table.append(texts)
        width = max(1, len(table[0]))
        marks = {"left": ":---", "right": "---:", "center": ":---:", "": "---"}
        lines = ["| " + " | ".join((row + [""] * width)[:width]) + " |" for row in table]
        lines.insert(1, "| " + " | ".join(marks[a] for a in (aligns + [""] * width)[:width]) + " |")
        return "\n".join(lines)

    def _callout(self, node: _Node) -> str:
        kind = next((c.split("-", 1)[1] for c in node.classes if c.startswith("callout-")), "note")
        children = list(node.children)
        title = ""
        for child in children:
            if isinstance(child, _Node) and child.tag == "p" and "callout-title" in child.classes:
                title = child.text().strip()
                children.remove(child)
                break
        if title.lower() == kind:
            title = ""
        body = "\n\n".join(self.blocks(children))
        colons = ":" * (max([2] + [len(run) for run in re.findall(r"^:{3,}", body, re.M)]) + 1)
        return f"{colons} {kind}{' ' + title if title else ''}\n{body}\n{colons}"

    def _footnotes(self, node: _Node) -> list[str]:
        out = []
        for item in (c for section in node.children if isinstance(section, _Node) for c in section.children):
            if not (isinstance(item, _Node) and item.tag == "li"):
                continue
            match = _FOOTNOTE_ID_RE.fullmatch(item.attrs.get("id") or "")
            label = match.group(1) if match else str(len(out) + 1)
            body = "\n\n".join(self.blocks(item.children)).rstrip()
            out.append(_indent(body, "    ", f"[^{label}]: "))
        return out


def html_to_markdown(html: str) -> Conversion:
    """Sanitized HTML as Markdown. Text is always kept; formatting may not be."""
    builder = _TreeBuilder()
    builder.feed(str(html))
    builder.close()
    writer = _MarkdownWriter()
    body = "\n\n".join(writer.blocks(builder.root.children)).strip()
    return Conversion(body, list(writer.warnings))


def convert(body: str, source: str, target: str) -> Conversion:
    """Rewrite a body from one of ``text.BODY_FORMATS`` into another."""
    if source == target:
        return Conversion(body)
    if target == "html":
        return Conversion(str(render_source(body, source)))
    if target == "markdown" and source == "html":
        return html_to_markdown(sanitize_authored(body))
    if target == "markdown" and source == "markdown_html":
        tokens, _env = markdown_tokens(body, kind="markdown_html")
        types = {t.type for t in tokens} | {c.type for t in tokens for c in (t.children or [])}
        if not types & {"html_block", "html_inline"}:
            return Conversion(body)
        return html_to_markdown(render_source(body, source))
    return Conversion(body)
