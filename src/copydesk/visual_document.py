"""Reading Markdown for the visual editor.

The parser that renders a piece also decides what the visual editor shows, so the
two can't disagree and extension syntax is recognized for what it is. Each block
keeps its original text: the editor writes that text back unless the writer changes
the block, so opening a piece and saving it changes nothing. Anything the visual
editor can't represent stays as an editable block of Markdown source.
"""

from __future__ import annotations

import re
from typing import Any

from copydesk.text import CALLOUTS, markdown_tokens

_ALIGN_RE = re.compile(r"text-align:(left|right|center)")
_CONTAINER_END_RE = re.compile(r" {0,3}:{3,}[ \t]*")
_FOOTNOTE_DEF_RE = re.compile(r" {0,3}\[\^([^\]\s]+)\]:")
# A definition nested in a quote, list or box leaves no trace in the parsed tokens.
_NESTED_DEFINITION_RE = re.compile(r"^[ \t>*+\-\d.)]*\[[^\]]+\]:[ \t]*\S", re.M)
_MARKS = {"strong_open": "strong", "em_open": "em", "s_open": "strike"}
_CONTAINERS = {f"container_{name}_open": name for name in CALLOUTS}
_CLOSES = {"strong_close": "strong", "em_close": "em", "s_close": "strike", "link_close": "link"}


class _Unsupported(Exception):
    """This block uses something the visual editor can't show faithfully."""


def _closing(tokens: list[Any], index: int) -> int:
    depth = 0
    for position in range(index, len(tokens)):
        depth += tokens[position].nesting
        if depth == 0:
            return position
    raise _Unsupported


def _alt_text(children: list[Any]) -> str:
    parts = []
    for token in children or []:
        if token.type == "image":
            parts.append(_alt_text(token.children))
        elif token.type in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif token.nesting == 0:
            parts.append(token.content)
    return "".join(parts)


def _inline(children: list[Any], *, in_cell: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    marks: list[dict[str, Any]] = []

    def add_text(text: str, extra: list[dict[str, Any]] | None = None) -> None:
        if text:
            node: dict[str, Any] = {"type": "text", "text": text}
            applied = marks + (extra or [])
            if applied:
                node["marks"] = list(applied)
            out.append(node)

    def with_marks(node: dict[str, Any]) -> dict[str, Any]:
        if marks:
            node["marks"] = list(marks)
        return node

    for token in children:
        kind = token.type
        if kind == "text":
            add_text(token.content)
        elif kind == "softbreak":
            add_text(" ")
        elif kind == "hardbreak":
            if in_cell:
                raise _Unsupported
            out.append(with_marks({"type": "hard_break"}))
        elif kind == "code_inline":
            add_text(token.content, [{"type": "code"}])
        elif kind in _MARKS:
            marks.append({"type": _MARKS[kind]})
        elif kind == "link_open":
            marks.append({"type": "link", "attrs": {
                "href": token.attrGet("href") or "", "title": token.attrGet("title"),
            }})
        elif kind in _CLOSES:
            name = _CLOSES[kind]
            for position in range(len(marks) - 1, -1, -1):
                if marks[position]["type"] == name:
                    del marks[position]
                    break
        elif kind == "image":
            out.append(with_marks({"type": "image", "attrs": {
                "src": token.attrGet("src") or "",
                "alt": _alt_text(token.children),
                "title": token.attrGet("title"),
            }}))
        elif kind == "footnote_ref" and token.meta.get("label"):
            out.append(with_marks({"type": "footnote_ref", "attrs": {"label": str(token.meta["label"])}}))
        else:
            raise _Unsupported
    return out


def _textblock(node_type: str, inline_token: Any, attrs: dict[str, Any] | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": node_type}
    if attrs:
        node["attrs"] = attrs
    content = _inline(inline_token.children or [])
    if content:
        node["content"] = content
    return node


def _task_state(inline_token: Any) -> bool | None:
    """Read and remove a task list's checkbox from the start of an item."""
    children = inline_token.children or []
    if not children or children[0].type != "html_inline" or "task-list-item-checkbox" not in children[0].content:
        return None
    checked = 'checked="checked"' in children[0].content
    inline_token.children = children[1:]
    if inline_token.children and inline_token.children[0].type == "text":
        inline_token.children[0].content = inline_token.children[0].content.removeprefix(" ")
    return checked


def _list_item(tokens: list[Any], start: int, end: int) -> dict[str, Any]:
    checked = None
    if tokens[start].attrGet("class") == "task-list-item" and tokens[start + 1].type == "paragraph_open":
        checked = _task_state(tokens[start + 2])
    content = _blocks(tokens, start + 1, end)
    item: dict[str, Any] = {"type": "list_item", "content": content or [{"type": "paragraph"}]}
    if checked is not None:
        item["attrs"] = {"checked": checked}
    return item


def _list(tokens: list[Any], start: int, end: int) -> dict[str, Any]:
    opening = tokens[start]
    items = []
    tight = True
    position = start + 1
    while position < end:
        if tokens[position].type != "list_item_open":
            raise _Unsupported
        close = _closing(tokens, position)
        depth = tokens[position].level + 1
        for token in tokens[position + 1 : close]:
            if token.type == "paragraph_open" and token.level == depth and not token.hidden:
                tight = False
        items.append(_list_item(tokens, position, close))
        position = close + 1
    if opening.type == "bullet_list_open":
        attrs: dict[str, Any] = {"tight": tight, "bullet": opening.markup or "-"}
        return {"type": "bullet_list", "attrs": attrs, "content": items}
    start_number = opening.attrGet("start")
    attrs = {
        "tight": tight,
        "order": 1 if start_number is None else int(start_number),
        "delimiter": opening.markup or ".",
    }
    return {"type": "ordered_list", "attrs": attrs, "content": items}


def _table(tokens: list[Any], start: int, end: int) -> dict[str, Any]:
    rows = []
    position = start + 1
    while position < end:
        token = tokens[position]
        if token.type == "tr_open":
            close = _closing(tokens, position)
            cells = []
            cell = position + 1
            while cell < close:
                opening = tokens[cell]
                if opening.type not in ("th_open", "td_open"):
                    raise _Unsupported
                align = _ALIGN_RE.search(opening.attrGet("style") or "")
                node: dict[str, Any] = {
                    "type": "table_header" if opening.type == "th_open" else "table_cell",
                    "attrs": {"align": align.group(1) if align else None},
                }
                content = _inline(tokens[cell + 1].children or [], in_cell=True)
                if content:
                    node["content"] = content
                cells.append(node)
                cell = _closing(tokens, cell) + 1
            rows.append({"type": "table_row", "content": cells})
            position = close + 1
        else:
            position += 1
    return {"type": "table", "content": rows}


def _block(tokens: list[Any], start: int, end: int) -> dict[str, Any]:
    token = tokens[start]
    kind = token.type
    if kind == "paragraph_open":
        return _textblock("paragraph", tokens[start + 1])
    if kind == "heading_open":
        return _textblock("heading", tokens[start + 1], {"level": int(token.tag[1])})
    if kind == "blockquote_open":
        return {"type": "blockquote", "content": _blocks(tokens, start + 1, end) or [{"type": "paragraph"}]}
    if kind in ("bullet_list_open", "ordered_list_open"):
        return _list(tokens, start, end)
    if kind in ("fence", "code_block"):
        node: dict[str, Any] = {"type": "code_block", "attrs": {"language": token.info.strip() if kind == "fence" else ""}}
        code = token.content.removesuffix("\n")
        if code:
            node["content"] = [{"type": "text", "text": code}]
        return node
    if kind == "hr":
        return {"type": "horizontal_rule"}
    if kind == "table_open":
        return _table(tokens, start, end)
    if kind in _CONTAINERS:
        name = _CONTAINERS[kind]
        title = token.info.strip()[len(name) :].strip()
        return {
            "type": "callout",
            "attrs": {"kind": name, "title": title},
            "content": _blocks(tokens, start + 1, end) or [{"type": "paragraph"}],
        }
    raise _Unsupported


def _blocks(tokens: list[Any], start: int, end: int) -> list[dict[str, Any]]:
    out = []
    position = start
    while position < end:
        token = tokens[position]
        if token.type == "footnote_anchor":
            position += 1
            continue
        close = _closing(tokens, position) if token.nesting == 1 else position
        out.append(_block(tokens, position, close))
        position = close + 1
    return out


def _footnote_groups(tokens: list[Any]) -> dict[str, dict[str, Any]]:
    """The tokens for each footnote definition, which the parser moves to the very end."""
    groups: dict[str, dict[str, Any]] = {}
    position = 0
    while position < len(tokens):
        if tokens[position].type == "footnote_open":
            close = _closing(tokens, position)
            label = tokens[position].meta.get("label")
            lines = [t.map[1] for t in tokens[position:close] if t.map]
            first = [t.map[0] for t in tokens[position:close] if t.map]
            if label is not None:
                groups[str(label)] = {
                    "start": position + 1, "end": close,
                    "first": min(first, default=-1), "last": max(lines, default=-1),
                }
            position = close
        position += 1
    return groups


def _gap_chunks(lines: list[str], start: int, end: int, groups: dict[str, dict[str, Any]]) -> list[tuple[int, int, str | None]]:
    """Split lines no top-level block claimed into footnote definitions and other source."""
    chunks: list[tuple[int, int, str | None]] = []
    line = start
    while line < end:
        if not lines[line].strip():
            line += 1
            continue
        match = _FOOTNOTE_DEF_RE.match(lines[line])
        if match:
            label = match.group(1)
            group = groups.get(label)
            stop = line + 1
            if group and group["last"] > stop:
                stop = min(group["last"], end)
            else:
                while stop < end and lines[stop].strip() and not _FOOTNOTE_DEF_RE.match(lines[stop]):
                    stop += 1
            chunks.append((line, stop, label if group else None))
            line = stop
            continue
        stop = line + 1
        while stop < end and lines[stop].strip() and not _FOOTNOTE_DEF_RE.match(lines[stop]):
            stop += 1
        chunks.append((line, stop, None))
        line = stop
    return chunks


def _raw(source: str) -> dict[str, Any]:
    return {"type": "raw_block", "content": [{"type": "text", "text": source}]} if source else {"type": "raw_block"}


def _whole_document_as_source(source: str) -> dict[str, Any]:
    stripped = source.strip()
    if not stripped:
        return {"blocks": [], "lead": source, "trailing": "", "unsupported": 0}
    lead = source[: len(source) - len(source.lstrip())]
    return {
        "blocks": [{"node": _raw(stripped), "source": stripped, "gap": lead}],
        "trailing": source[len(lead) + len(stripped) :],
        "unsupported": 1,
    }


def markdown_to_document(source: str) -> dict[str, Any]:
    """Blocks for the visual editor: each has a document node and its original text.

    Joining every block's ``gap`` and ``source``, then ``trailing``, gives back the
    Markdown exactly.
    """
    source = (source or "").replace("\r\n", "\n")
    tokens, _env = markdown_tokens(source)
    lines = source.split("\n")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)

    groups = _footnote_groups(tokens)
    claimed: list[tuple[int, int, int, int]] = []
    position = 0
    while position < len(tokens):
        token = tokens[position]
        if token.type == "footnote_block_open":
            break
        close = _closing(tokens, position) if token.nesting == 1 else position
        if token.map:
            last = token.map[1]
            # A box's line range stops short of its closing fence.
            if token.type in _CONTAINERS and last < len(lines) and _CONTAINER_END_RE.fullmatch(lines[last]):
                last += 1
            claimed.append((token.map[0], last, position, close))
        position = close + 1

    parts: list[dict[str, Any]] = []
    line = 0
    for first, last, opening, close in [*claimed, (len(lines), len(lines), -1, -1)]:
        if first < line:
            return _whole_document_as_source(source)
        for start, stop, label in _gap_chunks(lines, line, first, groups):
            parts.append({"start": start, "stop": stop, "label": label})
        if opening >= 0:
            parts.append({"start": first, "stop": last, "tokens": (opening, close)})
        line = max(line, last)

    blocks: list[dict[str, Any]] = []
    unsupported = 0
    cursor = 0
    used: set[str] = set()
    for part in parts:
        begin = offsets[part["start"]]
        text = source[begin : offsets[part["stop"]]].rstrip()
        if not text:
            continue
        node = None
        try:
            if "tokens" in part:
                opening, close = part["tokens"]
                if (
                    tokens[opening].type != "paragraph_open"
                    and tokens[opening].type != "heading_open"
                    and tokens[opening].type not in ("fence", "code_block", "table_open", "hr")
                    and (
                        _NESTED_DEFINITION_RE.search(text)
                        or any(part["start"] <= g["first"] < part["stop"] for g in groups.values())
                    )
                ):
                    raise _Unsupported
                node = _block(tokens, opening, close)
            elif part.get("label") and part["label"] not in used:
                group = groups[part["label"]]
                used.add(part["label"])
                node = {
                    "type": "footnote_definition",
                    "attrs": {"label": part["label"]},
                    "content": _blocks(tokens, group["start"], group["end"]) or [{"type": "paragraph"}],
                }
        except _Unsupported:
            node = None
        if node is None:
            node = _raw(text)
            unsupported += 1
        blocks.append({"node": node, "source": text, "gap": source[cursor:begin]})
        cursor = begin + len(text)

    document = {"blocks": blocks, "trailing": source[cursor:], "unsupported": unsupported}
    rebuilt = "".join(block["gap"] + block["source"] for block in blocks) + document["trailing"]
    return document if rebuilt == source else _whole_document_as_source(source)
