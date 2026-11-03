"""The visual editor: reading Markdown for it, and getting Markdown back from it.

The Python tests use the same parser that renders articles. The Node script runs the
editor's real schema and writer, so a piece that survives here survives in a browser.
"""

import json
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from copydesk import body_formats, text
from copydesk.models import Article, User
from copydesk.visual_document import markdown_to_document
from test_body_formats import EVERY_FEATURE, make_article

ROOT = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="Node runs the editor's own code")

# Every feature the toolbar offers, written the way the editor writes it.
SUPPORTED = {
    "headings": "# One\n\n## Two\n\n###### Six",
    "marks": "Some **bold**, *italic*, ~~struck~~ and `code` in **bold *and italic*** text.",
    "links": '[Plain](https://example.com) and [titled](https://example.com/a "A title") and <https://auto.example>.',
    "bold link": "[**Bold link**](https://example.com) and more.",
    "bullets": "- one\n- two\n  - nested\n  - nested two\n- three",
    "loose list": "- one\n\n- two\n\n  second paragraph",
    "ordered": "1. one\n2. two\n\n   more of two\n3. three",
    "start": "4. four\n5. five",
    "zero": "0. zero\n1. one",
    "tasks": "- [ ] open\n- [x] done\n- plain",
    "quote": "> A quotation\n>\n> with two paragraphs\n>\n> > and a nested one",
    "fence": "```python\nprint('hello')\n\n# blank line above\n```",
    "plain fence": "```\nplain\n```",
    "fence holding fences": "````\n```python\ninner\n```\n````",
    "info": "```python title=x\ncode\n```",
    "image": '![Alt text](/uploads/a.png "Caption")',
    "image link": "[![Alt](/uploads/a.png)](https://example.com)",
    "table": "| A | B | C |\n| :--- | ---: | :---: |\n| 1 | `x\\|y` | **z** |\n|  | ![I](/i.png) | [l](/l) |",
    "one column": "| A |\n| --- |\n| 1 |",
    "footnotes": "Text[^1] and more[^note].\n\n[^1]: First note.\n\n[^note]: Second note.\n\n    With a second paragraph.",
    "callouts": "::: note\nA note.\n:::\n\n::: tip A title\nA tip.\n\n- with a list\n:::\n\n::: warning\nCareful.\n:::",
    "nested callouts": ":::: note Outer\nText\n\n::: tip Inner\nDeep\n:::\n::::",
    "rule": "Above\n\n---\n\nBelow",
    "break": "Line one\\\nline two",
    "escapes": r"Not \*bold\*, not \_italic\_, \`code\`, \[link](x), \<tag>, \&amp; and \# hash.",
    "line starts": "\\# not a heading\n\n\\- not a list\n\n1\\. not a list\n\n\\> not a quote\n\n\\::: not a box",
    "intraword": "snake_case_name and 2 * 3 * 4",
    "unicode": "مرحبا 🌊 café 日本語",
    "together": EVERY_FEATURE,
}

# Written differently from how the editor would, or not representable at all. All must be kept.
UNUSUAL = {
    "setext": "Heading\n=======\n\nSub\n---",
    "star bullets": "* one\n* two\n\n+ other\n+ list",
    "paren list": "1) one\n2) two",
    "soft breaks": "One line\nand another\nand a third.",
    "trailing hashes": "## Heading ##",
    "underscores": "__bold__ and _italic_",
    "tilde fence": "~~~python\ncode\n~~~",
    "indented": "    indented code",
    "hard break spaces": "Line one  \nline two",
    "spaces between": "One\n\n\n\nTwo\n\n\nThree\n",
    "reference link": "[text][r]\n\n[r]: https://example.com 'T'",
    "inline footnote": "Text ^[inline note] here.",
    "unused footnote": "No reference.\n\n[^x]: Never used.",
    "html text": "<div>shown as text</div>\n\nand <b>this</b>.",
    "entities": "&copy; &amp; &#35; here",
    "lazy": "> quoted\nlazy line",
    "extension syntax": "@[youtube](abc) {{ thing }} %% note %%",
    "nested reference": "> [r]: https://example.com\n> quoted\n\n[text][r]",
    "nested footnote": "::: tip\nText[^1]\n\n[^1]: Inside a box.\n:::",
    "leading blank lines": "\n\n# Heading",
    "crlf free tabs": "-\titem\n\n\tcode?",
    "empty": "",
    "only spaces": "   \n  \n",
}


def run_node(**payload):
    done = subprocess.run(
        ["node", "tests/js/visual-roundtrip.cjs"], input=json.dumps(payload), cwd=ROOT,
        capture_output=True, text=True, check=True,
    )
    return json.loads(done.stdout)


def rendered(markdown):
    """What a reader gets. Line breaks and spaces between tags don't change that."""
    html = str(text.render_markdown(markdown))
    return re.sub(r">\s+<", "><", re.sub(r"\s+", " ", html)).strip()


# ---------------------------------------------------------------------- reading on the server


@pytest.mark.parametrize("source", [*SUPPORTED.values(), *UNUSUAL.values()],
                         ids=[*SUPPORTED.keys(), *UNUSUAL.keys()])
def test_blocks_rebuild_the_text_exactly(app, source):
    with app.app_context():
        document = markdown_to_document(source)
    rebuilt = "".join(block["gap"] + block["source"] for block in document["blocks"]) + document["trailing"]
    assert rebuilt == source


@pytest.mark.parametrize("name", list(SUPPORTED))
def test_supported_features_become_visual_blocks(app, name):
    with app.app_context():
        document = markdown_to_document(SUPPORTED[name])
    assert document["unsupported"] == 0, document


@pytest.mark.parametrize("name", ["inline footnote", "extension syntax" , "reference link", "nested reference", "nested footnote", "unused footnote"])
def test_what_cannot_be_shown_stays_as_source(app, name):
    with app.app_context():
        document = markdown_to_document(UNUSUAL[name])
    if name == "extension syntax":
        # Core Markdown sees plain text here. A real plugin is covered below.
        assert document["unsupported"] == 0
        return
    kinds = [block["node"]["type"] for block in document["blocks"]]
    assert "raw_block" in kinds, kinds
    raw = next(b for b in document["blocks"] if b["node"]["type"] == "raw_block")
    assert raw["node"]["content"][0]["text"] == raw["source"]


def test_extension_syntax_is_recognized_and_kept_as_source(app):
    from markdown_it.rules_inline import StateInline

    def plugin(md):
        def rule(state: StateInline, silent: bool) -> bool:
            if not state.src.startswith("%%", state.pos):
                return False
            if not silent:
                token = state.push("spoiler", "span", 0)
                token.content = "x"
            state.pos += 2
            return True

        md.inline.ruler.before("emphasis", "spoiler", rule)

    with app.app_context():
        state = app.extensions["copydesk"]
        state.hooks.markdown_setups.append(plugin)
        document = markdown_to_document("Plain paragraph.\n\nWith %% a spoiler.")
    kinds = [block["node"]["type"] for block in document["blocks"]]
    assert kinds == ["paragraph", "raw_block"] and document["unsupported"] == 1


def test_typographer_does_not_change_the_text_the_editor_shows(app):
    with app.app_context():
        document = markdown_to_document('"Quotes" -- (c) ...')
    assert document["blocks"][0]["node"]["content"][0]["text"] == '"Quotes" -- (c) ...'


def test_endpoint_reads_markdown(app, editor_client):
    response = editor_client.post("/write/visual", json={"body": "# Hi"}, headers={"X-CSRF-Token": "test-csrf"})
    assert response.status_code == 200 and response.get_json()["blocks"][0]["node"]["type"] == "heading"


@pytest.mark.parametrize("path", ["/write/visual", "/write/convert"])
def test_endpoints_need_a_token_and_a_verified_account(app, client, path):
    assert client.post(path, json={"body": "x"}).status_code == 400
    with client.session_transaction() as session:
        session["_csrf"] = "token"
    assert client.post(path, json={"body": "x"}, headers={"X-CSRF-Token": "token"}).status_code in (302, 401, 403)


def test_a_piece_over_the_limit_is_refused_and_never_cut_short(editor_client):
    headers = {"X-CSRF-Token": "test-csrf", "X-Requested-With": "fetch"}
    response = editor_client.post("/write/visual", json={"body": "x" * 200_001}, headers=headers)
    assert response.status_code == 413 and "too long" in response.get_json()["message"]
    response = editor_client.post("/write/convert", json={"body": "x" * 200_001, "source": "markdown", "target": "html"}, headers=headers)
    assert response.status_code == 413


# ---------------------------------------------------------------- writing it back in the editor


@needs_node
def test_nothing_changes_when_nothing_is_edited(app):
    sources = [*SUPPORTED.values(), *UNUSUAL.values()]
    with app.app_context():
        documents = [markdown_to_document(source) for source in sources]
    results = run_node(documents=documents)["documents"]
    for source, result in zip(sources, results, strict=True):
        assert result["kept"] == source


@needs_node
@pytest.mark.parametrize("name", list(SUPPORTED))
def test_rewriting_a_block_keeps_how_it_renders(app, name):
    source = SUPPORTED[name]
    with app.app_context():
        result = run_node(documents=[markdown_to_document(source)])["documents"][0]
        assert rendered(result["rewritten"]) == rendered(source), result["rewritten"]


@needs_node
@pytest.mark.parametrize("name", list(SUPPORTED))
def test_the_editors_own_output_is_stable(app, name):
    with app.app_context():
        once = run_node(documents=[markdown_to_document(SUPPORTED[name])])["documents"][0]["rewritten"]
        twice = run_node(documents=[markdown_to_document(once)])["documents"][0]
    assert twice["rewritten"] == once and twice["kept"] == once


FRAGMENTS = [
    "word", "a", "b", " ", "  ", "*", "**", "_", "__", "`", "``", "~", "~~", "[", "]", "(", ")", "<", ">", "<b>",
    "</b>", "&amp;", "&", "\\", "#", "# ", "- ", "+ ", "1. ", "2) ", "> ", "|", "!", "![", "::: ", ":::", "---",
    "===", "^", "[^1]", "[a](b)", '"', "'", "...", "--", "(c)", "$", "{", "}", "é", "日本", "_a_", "*a*", "`a`",
    "foo_bar", "1.", "\\*",
]
MARKS = [
    [], [], [], [{"type": "strong"}], [{"type": "em"}], [{"type": "strike"}], [{"type": "code"}],
    [{"type": "link", "attrs": {"href": "https://e.x/p", "title": None}}], [{"type": "strong"}, {"type": "em"}],
    [{"type": "link", "attrs": {"href": "https://e.x/q_r", "title": 'T"t'}}, {"type": "strong"}],
    [{"type": "em"}, {"type": "strike"}],
]


def fuzz_inline(rng):
    # CommonMark can't open emphasis on punctuation straight after a letter, so marked runs
    # sit between spaces or start and end with letters. See test_known_limit_below.
    out = []
    for _ in range(rng.randint(1, 4)):
        content = "".join(rng.choice(FRAGMENTS) for _ in range(rng.randint(1, 4)))
        node = {"type": "text", "text": content}
        marks = rng.choice(MARKS)
        if not marks:
            out.append(node)
            continue
        node["marks"] = marks
        if rng.random() < 0.5:
            node["text"] = f"x{content}y"
        elif not any(mark["type"] == "code" for mark in marks):
            node["text"] = content.strip() or "x"
        if out:
            out.append({"type": "text", "text": " "})
        out += [node, {"type": "text", "text": " "}]
    return out


def fuzz_block(rng, depth=0):
    kind = rng.choice(["p", "p", "p", "h", "q", "ul", "ol", "task", "code", "hr", "box", "table"]) if depth < 3 else "p"
    if kind == "p":
        return {"type": "paragraph", "content": fuzz_inline(rng)}
    if kind == "h":
        return {"type": "heading", "attrs": {"level": rng.randint(1, 6)}, "content": fuzz_inline(rng)}
    if kind == "q":
        return {"type": "blockquote", "content": [fuzz_block(rng, depth + 1) for _ in range(rng.randint(1, 2))]}
    if kind in ("ul", "ol", "task"):
        items = []
        for _ in range(rng.randint(1, 3)):
            item = {"type": "list_item", "content": [{"type": "paragraph", "content": fuzz_inline(rng)}]}
            if rng.random() < 0.3:
                item["content"].append(fuzz_block(rng, depth + 1))
            if kind == "task":
                item["attrs"] = {"checked": rng.random() < 0.5}
            items.append(item)
        tight = rng.random() < 0.5
        if kind == "ol":
            return {"type": "ordered_list", "attrs": {"order": rng.choice([1, 1, 3, 0]), "tight": tight, "delimiter": "."}, "content": items}
        return {"type": "bullet_list", "attrs": {"tight": tight, "bullet": "-"}, "content": items}
    if kind == "code":
        code = rng.choice(["x = 1", "```\ninner\n```", "  indented\n\nblank", "~~~\nz", "a `b`"])
        return {"type": "code_block", "attrs": {"language": rng.choice(["", "python", "js"])}, "content": [{"type": "text", "text": code}]}
    if kind == "hr":
        return {"type": "horizontal_rule"}
    if kind == "box":
        return {"type": "callout", "attrs": {"kind": rng.choice(["note", "tip", "warning"]), "title": rng.choice(["", "A title"])},
                "content": [fuzz_block(rng, depth + 1) for _ in range(rng.randint(1, 2))]}
    columns = rng.randint(1, 3)
    aligns = [rng.choice([None, "left", "right", "center"]) for _ in range(columns)]
    rows = []
    for row in range(rng.randint(1, 3)):
        cells = [{"type": "table_header" if row == 0 else "table_cell", "attrs": {"align": align}, "content": fuzz_inline(rng)} for align in aligns]
        rows.append({"type": "table_row", "content": cells})
    return {"type": "table", "content": rows}


def flat_text(content):
    chars = []
    for node in content or []:
        # Plain addresses get linked when rendered, which is fine, so only compare real links.
        marks = tuple(sorted(
            (mark["type"], json.dumps(mark.get("attrs"), sort_keys=True) if mark["type"] == "link" else "")
            for mark in node.get("marks", []) if mark["type"] != "link" or "e.x/" in mark["attrs"]["href"]
        ))
        if node["type"] == "text":
            chars.extend((char, marks) for char in node["text"])
        else:
            chars.append((node["type"] + json.dumps(node.get("attrs"), sort_keys=True), marks))
    out = []
    for char, marks in chars:
        if char in " \t\n":
            if not out or out[-1][0] != " ":
                out.append((" ", ()))
        else:
            out.append((char, marks))
    while out and out[0][0] == " ":
        out.pop(0)
    while out and out[-1][0] == " ":
        out.pop()
    return out


def meaning(node):
    """What a block means to a reader, ignoring how its text happened to be split up."""
    kind = node["type"]
    attrs = node.get("attrs") or {}
    if kind in ("paragraph", "heading", "table_cell", "table_header"):
        extra = attrs.get("level") if kind == "heading" else attrs.get("align")
        return (kind, extra, flat_text(node.get("content")))
    if kind == "code_block":
        return (kind, attrs["language"], "".join(child["text"] for child in node.get("content", [])))
    children = [meaning(child) for child in node.get("content", [])]
    children = [child for child in children if not (child[0] == "paragraph" and not child[2])]
    if kind == "callout":
        return (kind, attrs["kind"], attrs["title"], children)
    if kind == "ordered_list":
        return (kind, attrs.get("order"), children)
    if kind == "list_item":
        return (kind, attrs.get("checked"), children)
    return (kind, children)


@needs_node
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_any_document_survives_being_written_and_read_again(app, seed):
    rng = random.Random(seed)
    documents = [
        {"type": "doc", "content": [fuzz_block(rng) for _ in range(rng.randint(1, 3))]}
        for _ in range(150)
    ]
    written = run_node(nodes=documents)["nodes"]
    with app.app_context():
        for document, markdown in zip(documents, written, strict=True):
            back = [meaning(block["node"]) for block in markdown_to_document(markdown)["blocks"]]
            wanted = [meaning(node) for node in document["content"]]
            wanted = [block for block in wanted if not (block[0] == "paragraph" and not block[2])]
            assert back == wanted, markdown


@needs_node
def test_known_limit_emphasis_cannot_open_on_punctuation_after_a_letter(app):
    """CommonMark can't express this, so the asterisks show. No text is ever lost."""
    document = {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "word"}, {"type": "text", "text": '"quoted"', "marks": [{"type": "em"}]},
    ]}]}
    markdown = run_node(nodes=[document])["nodes"][0]
    with app.app_context():
        assert "word" in rendered(markdown) and "quoted" in rendered(markdown)


# ------------------------------------------------------------------------- format conversions


@pytest.mark.parametrize("name", [n for n in SUPPORTED if n not in ("escapes", "info", "line starts")])
def test_markdown_to_html_and_back_renders_the_same(app, name):
    source = SUPPORTED[name]
    with app.app_context():
        as_html = body_formats.convert(source, "markdown", "html")
        assert as_html.warnings == []
        back = body_formats.convert(as_html.body, "html", "markdown")
        assert back.warnings == [], back.warnings
        assert rendered(back.body) == rendered(source), back.body


def test_markdown_to_html_renders_identically(app):
    with app.app_context():
        as_html = body_formats.convert(EVERY_FEATURE, "markdown", "html").body
        assert re.sub(r"\s+", " ", str(text.render_source(as_html, "html"))) == re.sub(r"\s+", " ", str(text.render_markdown(EVERY_FEATURE)))


@pytest.mark.parametrize(("html", "markdown", "warning"), [
    ("<p>Text <mark>marked</mark></p>", "Text marked", "<mark>"),
    ("<details><summary>More</summary><p>Inside</p></details>", "**More**\n\nInside", "Collapsible"),
    ('<video src="https://e.x/a.mp4"></video>', "[Watch the video](https://e.x/a.mp4)", "become"),
    ('<video><source src="https://e.x/b.mp4"></video>', "[Watch the video](https://e.x/b.mp4)", "become"),
    ('<audio src="https://e.x/a.mp3"></audio>', "[Listen](https://e.x/a.mp3)", "become"),
    ('<iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>', "[Watch the video](https://www.youtube.com/watch?v=dQw4w9WgXcQ)", "become"),
    ('<img src="/a.png" alt="A" width="10">', "![A](/a.png)", "sizes"),
    ('<table><tr><th colspan="2">H</th></tr></table>', "| H |\n| --- |", "merge"),
    ("<table><caption>C</caption><tr><th>H</th></tr></table>", "| H |\n| --- |", "caption"),
    ("<figure><img src='/a.png' alt='A'><figcaption>Cap</figcaption></figure>", "![A](/a.png)\n\nCap", "<figure>"),
])
def test_html_to_markdown_keeps_the_text_and_says_what_changes(app, html, markdown, warning):
    with app.app_context():
        result = body_formats.convert(html, "html", "markdown")
    assert result.body == markdown
    assert any(warning in item for item in result.warnings), result.warnings


def test_html_to_markdown_escapes_text_and_drops_what_never_rendered(app):
    with app.app_context():
        result = body_formats.convert(
            "<p>2 * 3 and [not a link] and # hash</p><script>alert(1)</script><p># heading? </p><p>1. list?</p>",
            "html", "markdown",
        )
    assert "alert" not in result.body
    assert r"2 \* 3 and \[not a link] and # hash" in result.body
    assert r"\# heading?" in result.body and r"1\. list?" in result.body
    with app.app_context():
        assert "<script" not in str(text.render_markdown(result.body))


def test_markdown_with_html_converts_only_when_it_has_html(app):
    with app.app_context():
        plain = body_formats.convert("# Just *Markdown*", "markdown_html", "markdown")
        assert plain.body == "# Just *Markdown*" and plain.warnings == []
        mixed = body_formats.convert("# Heading\n\n<mark>x</mark> *y*\n", "markdown_html", "markdown")
        assert mixed.body.startswith("## Heading") or mixed.body.startswith("# Heading")
        assert "*y*" in mixed.body and "<mark>" not in mixed.body and mixed.warnings
        as_html = body_formats.convert("<mark>x</mark> *y*\n", "markdown_html", "html")
        assert "<mark>x</mark> <em>y</em>" in as_html.body


def test_convert_endpoint(editor_client):
    headers = {"X-CSRF-Token": "test-csrf"}
    response = editor_client.post("/write/convert", json={"body": "<mark>x</mark>", "source": "html", "target": "markdown"}, headers=headers)
    assert response.get_json()["body"] == "x" and "<mark>" in response.get_json()["warnings"][0]
    response = editor_client.post("/write/convert", json={"body": "x", "source": "nope", "target": "markdown"}, headers=headers)
    assert response.status_code == 400


# ------------------------------------------------------------------------------ the editor page


def test_editor_page_offers_every_mode_and_works_without_scripts(app, editor_client, admin):
    article_id = make_article(app, admin, "**text**")
    page = editor_client.get(f"/write/{article_id}/edit").data.decode()
    for piece in ('data-editor-mode="visual"', 'data-editor-mode="markdown"', 'data-editor-mode="html"',
                  'id="f-body_format"', 'name="body_format"', 'id="f-body"', 'name="action" value="preview"',
                  "editor-kit.min.js", "visual-editor.js", 'for="f-body_format"', 'data-link-dialog',
                  'for="f-link-url"', 'for="f-image-alt"', 'for="f-footnote-text"', 'for="f-code-language"',
                  'for="f-callout-kind"', 'for="f-callout-title"', 'for="f-text-style"'):
        assert piece in page
    # The modes start hidden, so nothing that needs a script shows without one.
    assert re.search(r'<div class="editor-modes"[^>]*\bhidden', page)
    assert ">Markdown with HTML</option>" not in page
    # Dialogs must not sit inside the piece's form, or Enter would submit it.
    assert page.index("data-link-dialog") > page.index("</form>")


def test_editor_scripts_follow_the_content_security_policy(app, editor_client, admin):
    article_id = make_article(app, admin, "text")
    response = editor_client.get(f"/write/{article_id}/edit")
    page = response.data.decode()
    assert " style=" not in re.sub(r"<script.*?</script>", "", page.split("<body")[1], flags=re.S)
    assert "onclick=" not in page
    for script in re.findall(r'<script src="([^"]+)"', page):
        assert script.startswith("/static/")
    static = editor_client.get(re.search(r'src="([^"]*editor-kit[^"]+)"', page).group(1))
    assert static.status_code == 200 and static.mimetype.endswith("javascript")


def test_prebuilt_editor_ships_with_its_licenses():
    vendor = ROOT / "src/copydesk/static/vendor/prosemirror"
    assert (vendor / "editor-kit.min.js").stat().st_size > 100_000
    licenses = (vendor / "LICENSES.txt").read_text(encoding="utf-8")
    readme = (vendor / "README.md").read_text(encoding="utf-8")
    for package in ("prosemirror-model", "prosemirror-view", "prosemirror-tables", "orderedmap", "w3c-keyname"):
        assert package in licenses and package in readme
    assert licenses.count("MIT License") + licenses.count("Permission is hereby granted") >= 15


# ------------------------------------------------------------------------------------ download


def test_download_gives_markdown_or_html_as_a_file(app, editor_client, admin):
    markdown_id = make_article(app, admin, "**text**", title="My piece")
    response = editor_client.get(f"/write/{markdown_id}/download")
    assert response.status_code == 200 and response.data == b"**text**"
    assert response.mimetype == "text/markdown"
    assert response.headers["Content-Disposition"] == 'attachment; filename="my-piece.md"'
    html_id = make_article(app, admin, "<script>alert(1)</script><p>x</p>", "html", title="Typed")
    response = editor_client.get(f"/write/{html_id}/download")
    assert response.headers["Content-Disposition"] == 'attachment; filename="typed.html"'
    assert response.headers["Content-Security-Policy"].startswith("sandbox")
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_download_keeps_drafts_private(app, client, admin):
    from copydesk.db import db
    from test_security_boundaries import make_user

    article_id = make_article(app, admin, "secret draft")
    assert client.get(f"/write/{article_id}/download").status_code in (302, 401)
    with app.app_context():
        other = make_user(email="other@example.edu", username="other", permissions=("submit", "review", "edit_any"))
        version = db.session.get(User, other).auth_version
    with client.session_transaction() as session:
        session["uid"], session["uv"] = other, version
    assert client.get(f"/write/{article_id}/download").status_code == 404
    with app.app_context():
        article = db.session.get(Article, article_id)
        article.status = "submitted"
        db.session.commit()
    assert client.get(f"/write/{article_id}/download").status_code == 200
