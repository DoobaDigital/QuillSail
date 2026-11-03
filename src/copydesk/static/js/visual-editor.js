/*
 * The visual editor's document: its schema, its commands, and how it becomes Markdown.
 *
 * Markdown stays the saved format. The server reads a piece into blocks, each with its
 * original text (see visual_document.py). A block the writer doesn't touch goes back
 * exactly as it was written, so opening and saving a piece changes nothing. Only edited
 * blocks are written out afresh. Anything else the editor can't show stays as a block of
 * editable Markdown source.
 *
 * editor.js owns the page: modes, the toolbar, dialogs and uploads. Everything here except
 * mount() works without a browser, so tests/js can run it under Node.
 */
(function (root) {
  "use strict";

  var kit = root.QuillSailEditorKit;
  if (!kit) return;

  var Schema = kit.model.Schema;
  var Fragment = kit.model.Fragment;
  var Slice = kit.model.Slice;
  var EditorState = kit.state.EditorState;
  var Plugin = kit.state.Plugin;
  var PluginKey = kit.state.PluginKey;
  var NodeSelection = kit.state.NodeSelection;
  var TextSelection = kit.state.TextSelection;
  var cmd = kit.commands;
  var lists = kit.schemaList;
  var rules = kit.inputrules;
  var tables = kit.tables;

  // ---------------------------------------------------------------- schema

  function safeUrl(value, isImage) {
    var clean = String(value || "").replace(/[\u0000-\u0020\u007f-\u009f]/g, "");
    var scheme = /^([a-z][a-z0-9+.-]*):/i.exec(clean);
    if (!scheme) return clean !== "" || !isImage;
    return isImage ? /^https?$/i.test(scheme[1]) : /^(https?|mailto)$/i.test(scheme[1]);
  }

  function cellAlign(dom) {
    var match = /\balign-(left|right|center)\b/.exec(dom.getAttribute("class") || "");
    if (match) return match[1];
    var style = dom.style && dom.style.textAlign;
    return style === "left" || style === "right" || style === "center" ? style : null;
  }

  var INLINE_ONLY = "(text | image | footnote_ref)*";

  var tableSpec = tables.tableNodes({
    tableGroup: "block",
    cellContent: INLINE_ONLY,
    cellAttributes: {
      align: {
        default: null,
        getFromDOM: cellAlign,
        setDOMAttr: function (value, attrs) {
          if (value) attrs.class = "align-" + value;
        },
      },
    },
  });
  // Markdown tables can't merge cells, so pasted spans are ignored and the gaps get filled in.
  tableSpec.table_cell.parseDOM = [{ tag: "td", getAttrs: function (dom) { return { align: cellAlign(dom) }; } }];
  tableSpec.table_header.parseDOM = [{ tag: "th", getAttrs: function (dom) { return { align: cellAlign(dom) }; } }];

  function headingRule(level) {
    return { tag: "h" + level, attrs: { level: level } };
  }

  var CALLOUT_KINDS = ["note", "tip", "warning"];

  function calloutLabel(node) {
    return node.attrs.title || node.attrs.kind.charAt(0).toUpperCase() + node.attrs.kind.slice(1);
  }

  var schema = new Schema({
    nodes: {
      doc: { content: "(block | footnote_definition | raw_block)+" },
      paragraph: {
        group: "block",
        content: "inline*",
        parseDOM: [{ tag: "p.callout-title", ignore: true, priority: 60 }, { tag: "p" }],
        toDOM: function () { return ["p", 0]; },
      },
      heading: {
        group: "block",
        content: INLINE_ONLY,
        attrs: { level: { default: 2 } },
        defining: true,
        parseDOM: [1, 2, 3, 4, 5, 6].map(headingRule),
        toDOM: function (node) { return ["h" + node.attrs.level, 0]; },
      },
      blockquote: {
        group: "block",
        content: "block+",
        defining: true,
        parseDOM: [{ tag: "blockquote" }],
        toDOM: function () { return ["blockquote", 0]; },
      },
      bullet_list: {
        group: "block",
        content: "list_item+",
        attrs: { tight: { default: true }, bullet: { default: "-" } },
        parseDOM: [{ tag: "ul" }],
        toDOM: function () { return ["ul", 0]; },
      },
      ordered_list: {
        group: "block",
        content: "list_item+",
        attrs: { order: { default: 1 }, tight: { default: true }, delimiter: { default: "." } },
        parseDOM: [{
          tag: "ol",
          getAttrs: function (dom) {
            var start = parseInt(dom.getAttribute("start"), 10);
            return { order: isNaN(start) ? 1 : start };
          },
        }],
        toDOM: function (node) {
          return node.attrs.order === 1 ? ["ol", 0] : ["ol", { start: node.attrs.order }, 0];
        },
      },
      list_item: {
        content: "block+",
        attrs: { checked: { default: null } },
        defining: true,
        parseDOM: [{
          tag: "li",
          getAttrs: function (dom) {
            var marked = dom.getAttribute("data-checked");
            if (marked !== null) return { checked: marked === "true" };
            var box = dom.querySelector(":scope > input[type=checkbox], :scope > p > input[type=checkbox]");
            return { checked: box ? box.hasAttribute("checked") : null };
          },
        }],
        toDOM: function (node) {
          if (node.attrs.checked === null) return ["li", 0];
          return ["li", { class: "task-list-item", "data-checked": String(node.attrs.checked) }, 0];
        },
      },
      code_block: {
        group: "block",
        content: "text*",
        marks: "",
        code: true,
        defining: true,
        attrs: { language: { default: "" } },
        parseDOM: [{
          tag: "pre",
          preserveWhitespace: "full",
          getAttrs: function (dom) {
            var code = dom.querySelector("code");
            var match = /\blanguage-([\w+#.-]+)/.exec((code && code.getAttribute("class")) || "");
            return { language: dom.getAttribute("data-language") || (match ? match[1] : "") };
          },
        }],
        toDOM: function (node) {
          return ["pre", node.attrs.language ? { "data-language": node.attrs.language } : {}, ["code", 0]];
        },
      },
      horizontal_rule: {
        group: "block",
        parseDOM: [{ tag: "hr" }],
        toDOM: function () { return ["hr"]; },
      },
      callout: {
        group: "block",
        content: "block+",
        defining: true,
        attrs: { kind: { default: "tip" }, title: { default: "" } },
        parseDOM: [{
          tag: "aside.callout",
          getAttrs: function (dom) {
            var match = /\bcallout-(note|tip|warning)\b/.exec(dom.getAttribute("class") || "");
            var kind = match ? match[1] : "note";
            var heading = dom.querySelector(":scope > .callout-title");
            var title = heading ? heading.textContent.trim() : "";
            return { kind: kind, title: title.toLowerCase() === kind ? "" : title };
          },
        }],
        toDOM: function (node) {
          return ["aside", { class: "callout callout-" + node.attrs.kind },
            ["p", { class: "callout-title", contenteditable: "false" }, calloutLabel(node)],
            ["div", { class: "callout-body" }, 0]];
        },
      },
      table: tableSpec.table,
      table_row: tableSpec.table_row,
      table_cell: tableSpec.table_cell,
      table_header: tableSpec.table_header,
      footnote_definition: {
        content: "block+",
        attrs: { label: { default: "1" } },
        defining: true,
        isolating: true,
        parseDOM: [{
          tag: "div.visual-footnote",
          contentElement: ".visual-footnote-body",
          getAttrs: function (dom) { return { label: dom.getAttribute("data-label") || "1" }; },
        }],
        toDOM: function (node) {
          return ["div", { class: "visual-footnote", "data-label": node.attrs.label },
            ["span", { class: "visual-footnote-label", contenteditable: "false" }, "Footnote " + node.attrs.label],
            ["div", { class: "visual-footnote-body" }, 0]];
        },
      },
      raw_block: {
        content: "text*",
        marks: "",
        code: true,
        defining: true,
        isolating: true,
        parseDOM: [{ tag: "div.visual-raw", contentElement: "code", preserveWhitespace: "full" }],
        toDOM: function () {
          return ["div", { class: "visual-raw" },
            ["p", { class: "visual-raw-label", contenteditable: "false" }, "Markdown source: kept exactly as typed"],
            ["pre", ["code", 0]]];
        },
      },
      text: { group: "inline" },
      image: {
        inline: true,
        group: "inline",
        draggable: true,
        attrs: { src: {}, alt: { default: "" }, title: { default: null } },
        parseDOM: [{
          tag: "img[src]",
          getAttrs: function (dom) {
            var src = dom.getAttribute("src");
            // A relative address in pasted HTML would point somewhere else on this site.
            if (!safeUrl(src, true) || !/^(https?:\/\/|(\/[^/?#]+)*\/uploads\/)/i.test(src)) return false;
            return { src: src, alt: dom.getAttribute("alt") || "", title: dom.getAttribute("title") };
          },
        }],
        toDOM: function (node) {
          return ["img", { src: node.attrs.src, alt: node.attrs.alt, title: node.attrs.title }];
        },
      },
      hard_break: {
        inline: true,
        group: "inline",
        selectable: false,
        parseDOM: [{ tag: "br" }],
        toDOM: function () { return ["br"]; },
      },
      footnote_ref: {
        inline: true,
        group: "inline",
        atom: true,
        attrs: { label: { default: "1" } },
        parseDOM: [{
          tag: "sup.footnote-ref",
          getAttrs: function (dom) {
            var label = dom.getAttribute("data-label");
            if (label) return { label: label };
            var match = /\d+/.exec(dom.textContent);
            return match ? { label: match[0] } : false;
          },
        }],
        toDOM: function (node) {
          return ["sup", { class: "footnote-ref", "data-label": node.attrs.label }, "[" + node.attrs.label + "]"];
        },
      },
    },
    // Marks nest in this order when they're written out, so a link wraps its bold text.
    marks: {
      link: {
        attrs: { href: {}, title: { default: null } },
        inclusive: false,
        parseDOM: [{
          tag: "a[href]",
          getAttrs: function (dom) {
            var href = dom.getAttribute("href");
            if (!safeUrl(href)) return false;
            return { href: href, title: dom.getAttribute("title") };
          },
        }],
        toDOM: function (mark) {
          return ["a", { href: mark.attrs.href, title: mark.attrs.title, rel: "noopener noreferrer nofollow" }, 0];
        },
      },
      strong: {
        parseDOM: [
          { tag: "strong" },
          // Google Docs wraps whole documents in <b style="font-weight:normal">.
          { tag: "b", getAttrs: function (dom) { return dom.style.fontWeight !== "normal" && null; } },
          { style: "font-weight=400", clearMark: function (mark) { return mark.type.name === "strong"; } },
          { style: "font-weight", getAttrs: function (value) { return /^(bold(er)?|[5-9]\d{2,})$/.test(value) && null; } },
        ],
        toDOM: function () { return ["strong", 0]; },
      },
      em: {
        parseDOM: [
          { tag: "i" },
          { tag: "em" },
          { style: "font-style=italic" },
          { style: "font-style=normal", clearMark: function (mark) { return mark.type.name === "em"; } },
        ],
        toDOM: function () { return ["em", 0]; },
      },
      strike: {
        parseDOM: [
          { tag: "s" },
          { tag: "del" },
          { tag: "strike" },
          { style: "text-decoration=line-through" },
          { style: "text-decoration-line=line-through" },
        ],
        toDOM: function () { return ["s", 0]; },
      },
      code: {
        code: true,
        parseDOM: [{ tag: "code" }],
        toDOM: function () { return ["code", 0]; },
      },
    },
  });

  var nodes = schema.nodes;
  var marks = schema.marks;

  // ---------------------------------------------------------------- writing Markdown

  var WORD = /[\p{L}\p{N}]/u;

  // Keep these rules in step with _escape in body_formats.py.
  function escapeText(text, inLink) {
    var out = text
      .replace(inLink ? /[\\`*[\]]/g : /[\\`*[]/g, "\\$&")
      .replace(/<(?=[A-Za-z/!?])/g, "\\<")
      .replace(/~(?=~|$)|^~/g, "\\~")
      .replace(/&(?=#?\w+;)/g, "\\&");
    return out.replace(/_/g, function (match, offset, whole) {
      var before = whole.charAt(offset - 1);
      var after = whole.charAt(offset + 1);
      return WORD.test(before) && WORD.test(after) ? "_" : "\\_";
    });
  }

  var LINE_START = /^(#{1,6}(?=\s|$)|>|[-+](?=\s|$)|=+\s*$|-+\s*$|:::|\|)/;
  var LINE_START_NUMBER = /^(\d{1,9})([.)])(?=\s|$)/;

  // Keep these rules in step with _escape_line_start in body_formats.py.
  function escapeLineStart(text) {
    if (LINE_START.test(text)) return "\\" + text;
    return text.replace(LINE_START_NUMBER, "$1\\$2");
  }

  function linkTarget(value) {
    if (/[\s()<>]/.test(value)) {
      return "<" + value.replace(/</g, "%3C").replace(/>/g, "%3E").replace(/\n/g, "") + ">";
    }
    return value;
  }

  function linkTitle(value) {
    return value ? ' "' + value.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"' : "";
  }

  function codeSpan(text) {
    var longest = 0;
    (text.match(/`+/g) || []).forEach(function (run) {
      longest = Math.max(longest, run.length);
    });
    var fence = new Array(longest + 2).join("`");
    var pad = /^`|`$/.test(text) || (/^ .* $/.test(text) && text.trim() !== "") ? " " : "";
    return fence + pad + text + pad + fence;
  }

  function imageMarkdown(node) {
    var alt = (node.attrs.alt || "").replace(/\\/g, "\\\\").replace(/\[/g, "\\[").replace(/]/g, "\\]");
    return "![" + alt + "](" + linkTarget(node.attrs.src) + linkTitle(node.attrs.title) + ")";
  }

  function opener(mark, out) {
    if (mark.type === marks.link) return "[";
    if (mark.type === marks.strike) return "~~";
    // Two runs of asterisks side by side would read as one, so switch to underscores.
    var star = out.charAt(out.length - 1) === "*";
    if (mark.type === marks.strong) return star ? "__" : "**";
    return star ? "_" : "*";
  }

  function closer(entry) {
    if (entry.mark.type === marks.link) {
      return "](" + linkTarget(entry.mark.attrs.href) + linkTitle(entry.mark.attrs.title) + ")";
    }
    return entry.delimiter;
  }

  // How many following siblings keep this mark, so the longest-running mark opens first.
  function markRun(parent, index, mark) {
    var run = 0;
    for (var i = index + 1; i < parent.childCount; i++) {
      if (!mark.isInSet(parent.child(i).marks)) break;
      run++;
    }
    return run;
  }

  function inlineMarkdown(parent) {
    var out = "";
    var open = [];
    var pending = "";

    function close(keep) {
      while (open.length > keep) {
        var entry = open.pop();
        var label = out.slice(entry.at + 1);
        var href = entry.mark.attrs && entry.mark.attrs.href;
        // A link whose text is its own address reads best as the address alone.
        if (entry.mark.type === marks.link && label === href && !entry.mark.attrs.title &&
            /^(https?|mailto):[^\s<>]*$/i.test(href)) {
          out = out.slice(0, entry.at) + "<" + href + ">";
        } else {
          out += closer(entry);
        }
      }
    }

    for (var index = 0; index < parent.childCount; index++) {
      var child = parent.child(index);
      var isCode = child.isText && !!marks.code.isInSet(child.marks);
      var wanted = child.marks.filter(function (mark) { return mark.type !== marks.code; });

      var keep = 0;
      while (keep < open.length && open[keep].mark.isInSet(wanted)) keep++;
      close(keep);
      out += pending;
      pending = "";

      var text = child.isText ? child.text.replace(/\n/g, " ") : "";
      var core = text;
      var lead = "";
      var tail = "";
      if (child.isText && !isCode) {
        lead = /^\s*/.exec(text)[0];
        core = text.slice(lead.length);
        tail = /\s*$/.exec(core)[0];
        core = core.slice(0, core.length - tail.length);
      }
      // Spaces at the start of a line would change what the line means, so they don't survive.
      out += out !== "" && out.charAt(out.length - 1) !== "\n" ? lead : lead.replace(/^[ \t]+/, "");
      if (child.isText && !isCode && !core) {
        pending = tail;
        continue;
      }

      var opening = wanted
        .filter(function (mark) {
          return !open.some(function (entry) { return entry.mark.eq(mark); });
        })
        .map(function (mark, order) { return { mark: mark, run: markRun(parent, index, mark), order: order }; })
        .sort(function (a, b) { return b.run - a.run || a.order - b.order; });
      opening.forEach(function (item) {
        var delimiter = opener(item.mark, out);
        open.push({ mark: item.mark, delimiter: delimiter, at: out.length });
        out += delimiter;
      });

      if (isCode) {
        out += codeSpan(text);
      } else if (child.isText) {
        var escaped = escapeText(core, wanted.some(function (mark) { return mark.type === marks.link; }));
        var lineEmpty = out === "" || out.charAt(out.length - 1) === "\n";
        out += lineEmpty ? escapeLineStart(escaped) : escaped;
        pending = tail;
      } else if (child.type === nodes.hard_break) {
        // A break at the very end of a block means nothing in Markdown.
        if (index < parent.childCount - 1) out += "\\\n";
      } else if (child.type === nodes.image) {
        out += imageMarkdown(child);
      } else if (child.type === nodes.footnote_ref) {
        out += "[^" + child.attrs.label + "]";
      }
    }
    close(0);
    return out.replace(/[ \t]+$/, "");
  }

  function indent(text, prefix, first) {
    return text
      .split("\n")
      .map(function (line, index) {
        var lead = index === 0 && first !== undefined ? first : prefix;
        if (line) return lead + line;
        return index === 0 ? lead.replace(/\s+$/, "") : "";
      })
      .join("\n");
  }

  function fenced(node) {
    var code = node.textContent;
    var info = node.attrs.language || "";
    var longest = 2;
    (code.match(/^ {0,3}(`{3,}|~{3,})/gm) || []).forEach(function (run) {
      longest = Math.max(longest, run.trim().length);
    });
    var mark = info.indexOf("`") === -1 ? "`" : "~";
    var fence = new Array(longest + 2).join(mark);
    return fence + info + "\n" + code + "\n" + fence;
  }

  function calloutDepth(node) {
    var depth = 0;
    node.descendants(function (child) {
      if (child.type === nodes.callout) depth = Math.max(depth, calloutDepth(child) + 1);
      return child.type !== nodes.callout;
    });
    return depth;
  }

  function tableMarkdown(node) {
    var rows = [];
    node.forEach(function (row) {
      var cells = [];
      row.forEach(function (cell) {
        cells.push(inlineMarkdown(cell).replace(/\|/g, "\\|"));
      });
      rows.push(cells);
    });
    var width = rows.length ? rows[0].length : 1;
    var aligns = [];
    if (node.childCount) {
      node.child(0).forEach(function (cell) { aligns.push(cell.attrs.align); });
    }
    var rule = { left: ":---", right: "---:", center: ":---:" };
    var lines = rows.map(function (cells) {
      var padded = cells.slice(0, width);
      while (padded.length < width) padded.push("");
      return "| " + padded.join(" | ") + " |";
    });
    var divider = [];
    for (var i = 0; i < width; i++) divider.push(rule[aligns[i]] || "---");
    lines.splice(1, 0, "| " + divider.join(" | ") + " |");
    return lines.join("\n");
  }

  // Two lists in a row with the same marker would read as one list.
  function listMarker(node, previous) {
    if (node.type === nodes.bullet_list) {
      var bullet = node.attrs.bullet || "-";
      if (previous && previous.type === nodes.bullet_list && previous.marker === bullet) {
        bullet = bullet === "-" ? "*" : "-";
      }
      return bullet;
    }
    var delimiter = node.attrs.delimiter || ".";
    if (previous && previous.type === nodes.ordered_list && previous.marker === delimiter) {
      delimiter = delimiter === "." ? ")" : ".";
    }
    return delimiter;
  }

  function isList(node) {
    return node.type === nodes.bullet_list || node.type === nodes.ordered_list;
  }

  function listItemMarkdown(item, tight) {
    var parts = [];
    var previous = null;
    item.forEach(function (child) {
      var written = blockMarkdown(child, previous);
      previous = { type: child.type, marker: written.marker };
      if (written.text || parts.length || child.type !== nodes.paragraph) {
        // Only a list starting at 1 can follow a line directly. Anything else needs a blank line.
        parts.push({ text: written.text, list: isList(child) && (child.type === nodes.bullet_list || child.attrs.order === 1) });
      }
    });
    var body = "";
    parts.forEach(function (part, index) {
      if (index) body += tight && part.list ? "\n" : "\n\n";
      body += part.text;
    });
    if (item.attrs.checked !== null && item.firstChild && item.firstChild.type === nodes.paragraph && body) {
      body = (item.attrs.checked ? "[x] " : "[ ] ") + body;
    }
    return body;
  }

  function listMarkdown(node, marker) {
    var tight = node.attrs.tight !== false;
    var written = [];
    node.forEach(function (item, _offset, index) {
      var lead = node.type === nodes.bullet_list
        ? marker + " "
        : (node.attrs.order === undefined ? 1 : node.attrs.order) + index + marker + " ";
      var body = listItemMarkdown(item, tight);
      written.push(body ? indent(body, new Array(lead.length + 1).join(" "), lead) : lead.replace(/\s+$/, ""));
    });
    return written.join(tight ? "\n" : "\n\n");
  }

  function blocksMarkdown(parent) {
    var parts = [];
    var previous = null;
    parent.forEach(function (child) {
      var written = blockMarkdown(child, previous);
      previous = { type: child.type, marker: written.marker };
      if (written.text) parts.push(written.text);
    });
    return parts.join("\n\n");
  }

  function blockMarkdown(node, previous) {
    var type = node.type;
    if (type === nodes.bullet_list || type === nodes.ordered_list) {
      var marker = listMarker(node, previous);
      return { text: listMarkdown(node, marker), marker: marker };
    }
    return { text: plainBlockMarkdown(node) };
  }

  function plainBlockMarkdown(node) {
    var type = node.type;
    if (type === nodes.paragraph) return inlineMarkdown(node);
    if (type === nodes.heading) {
      var text = inlineMarkdown(node).replace(/(^|[^\\#])(#+)$/, "$1\\$2");
      return text ? new Array(node.attrs.level + 1).join("#") + " " + text : "";
    }
    if (type === nodes.blockquote) {
      return blocksMarkdown(node)
        .split("\n")
        .map(function (line) { return line ? "> " + line : ">"; })
        .join("\n");
    }
    if (type === nodes.code_block) return fenced(node);
    if (type === nodes.horizontal_rule) return "---";
    if (type === nodes.table) return tableMarkdown(node);
    if (type === nodes.raw_block) return node.textContent;
    if (type === nodes.callout) {
      var colons = new Array(calloutDepth(node) + 4).join(":");
      var title = (node.attrs.title || "").replace(/\s+/g, " ").trim();
      return colons + " " + node.attrs.kind + (title ? " " + title : "") + "\n" + blocksMarkdown(node) + "\n" + colons;
    }
    if (type === nodes.footnote_definition) {
      return indent(blocksMarkdown(node), "    ", "[^" + node.attrs.label + "]: ");
    }
    return node.textContent;
  }

  function canonical(node, previous) {
    return blockMarkdown(node, previous).text;
  }

  // ---------------------------------------------------------------- reading the server's blocks

  function rawNode(source) {
    return nodes.raw_block.create(null, source ? schema.text(source) : null);
  }

  /* Build a document from POST /write/visual. ``origin`` remembers each block's original text. */
  function documentFrom(data) {
    var origin = { nodes: new WeakMap(), blocks: [], trailing: data.trailing || "", pristine: null };
    var children = (data.blocks || []).map(function (block, index) {
      var node;
      try {
        node = schema.nodeFromJSON(block.node);
        node.check();
      } catch (e) {
        node = rawNode(block.source);
      }
      var entry = { source: block.source, gap: block.gap || "", index: index, node: node, used: false };
      origin.nodes.set(node, entry);
      origin.blocks.push(entry);
      return node;
    });
    if (!children.length) children = [nodes.paragraph.create()];
    return { doc: nodes.doc.create(null, children), origin: origin };
  }

  // An edit that was undone gives back an equal block as a new object. Finding its original
  // text keeps the writer's formatting, so undoing really does put everything back.
  function pristineFor(origin, text) {
    if (!origin.pristine) {
      origin.pristine = Object.create(null);
      origin.blocks.forEach(function (entry) {
        var key = canonical(entry.node);
        if (!origin.pristine[key]) origin.pristine[key] = entry;
      });
    }
    return origin.pristine[text];
  }

  /* The document as Markdown. Blocks nobody changed come back byte for byte. */
  function toMarkdown(doc, origin) {
    var out = "";
    var previousEntry = null;
    var previous = null;
    doc.forEach(function (node) {
      var entry = origin ? origin.nodes.get(node) : null;
      var written = entry
        ? { text: entry.source, marker: isList(node) ? node.attrs.bullet || node.attrs.delimiter : undefined }
        : blockMarkdown(node, previous);
      previous = { type: node.type, marker: written.marker };
      if (!entry && origin && written.text) entry = pristineFor(origin, written.text);
      var text = entry ? entry.source : written.text;
      if (!text) return;
      var gap = "\n\n";
      if (!out && !entry) gap = "";
      else if (entry && (previousEntry ? previousEntry.index + 1 === entry.index : entry.index === 0 && !out)) gap = entry.gap;
      else if (!out) gap = "";
      out += gap + text;
      previousEntry = entry;
    });
    return out + (origin ? origin.trailing : "");
  }

  // ---------------------------------------------------------------- commands

  function ancestor(state, types) {
    var $from = state.selection.$from;
    for (var depth = $from.depth; depth > 0; depth--) {
      if (types.indexOf($from.node(depth).type) !== -1) {
        return { node: $from.node(depth), pos: $from.before(depth), depth: depth };
      }
    }
    return null;
  }

  function toggleBlock(type, attrs) {
    return function (state, dispatch, view) {
      var parent = state.selection.$from.parent;
      var active = parent.type === type && (!attrs || parent.attrs.level === attrs.level);
      if (active) return cmd.setBlockType(nodes.paragraph)(state, dispatch, view);
      return cmd.setBlockType(type, attrs)(state, dispatch, view);
    };
  }

  function toggleWrap(type, attrs) {
    return function (state, dispatch, view) {
      if (ancestor(state, [type])) return cmd.lift(state, dispatch, view);
      return cmd.wrapIn(type, attrs)(state, dispatch, view);
    };
  }

  function toggleList(type) {
    return function (state, dispatch, view) {
      var list = ancestor(state, [nodes.bullet_list, nodes.ordered_list]);
      if (!list) return lists.wrapInList(type)(state, dispatch, view);
      if (list.node.type === type) return lists.liftListItem(nodes.list_item)(state, dispatch, view);
      if (dispatch) dispatch(state.tr.setNodeMarkup(list.pos, type, { tight: list.node.attrs.tight }));
      return true;
    };
  }

  function setTaskState(tr, from, to, value) {
    tr.doc.nodesBetween(from, to, function (node, pos) {
      if (node.type === nodes.list_item) {
        tr.setNodeMarkup(tr.mapping.map(pos), null, { checked: value });
      }
    });
    return tr;
  }

  function toggleTask(state, dispatch, view) {
    var item = ancestor(state, [nodes.list_item]);
    var selection = state.selection;
    if (item) {
      if (dispatch) {
        var next = item.node.attrs.checked === null ? false : null;
        dispatch(setTaskState(state.tr, selection.from, Math.max(selection.to, selection.from + 1), next));
      }
      return true;
    }
    var wrapped = null;
    if (!lists.wrapInList(nodes.bullet_list)(state, function (tr) { wrapped = tr; }, view)) return false;
    if (dispatch) {
      var from = wrapped.mapping.map(selection.from, -1);
      var to = wrapped.mapping.map(selection.to, 1);
      var tasks = wrapped;
      wrapped.doc.nodesBetween(from, to, function (node, pos) {
        if (node.type === nodes.list_item) tasks.setNodeMarkup(pos, null, { checked: false });
      });
      dispatch(tasks);
    }
    return true;
  }

  function toggleChecked(state, dispatch) {
    var item = ancestor(state, [nodes.list_item]);
    if (!item || item.node.attrs.checked === null) return false;
    if (dispatch) dispatch(state.tr.setNodeMarkup(item.pos, null, { checked: !item.node.attrs.checked }));
    return true;
  }

  // A new line in a task list is another unticked task.
  function splitItem(state, dispatch, view) {
    var item = ancestor(state, [nodes.list_item]);
    var attrs = item && item.node.attrs.checked !== null ? { checked: false } : null;
    return lists.splitListItem(nodes.list_item, attrs)(state, dispatch, view);
  }

  function insertRule(state, dispatch) {
    if (dispatch) dispatch(state.tr.replaceSelectionWith(nodes.horizontal_rule.create()).scrollIntoView());
    return true;
  }

  function insertTable(state, dispatch) {
    var header = [];
    var body = [];
    for (var column = 0; column < 2; column++) {
      header.push(nodes.table_header.create());
      body.push(nodes.table_cell.create());
    }
    var table = nodes.table.create(null, [nodes.table_row.create(null, header), nodes.table_row.create(null, body)]);
    if (dispatch) {
      var tr = state.tr.replaceSelectionWith(table);
      var found = null;
      tr.doc.descendants(function (node, pos) {
        if (found === null && node === table) found = pos;
        return found === null;
      });
      if (found !== null) tr.setSelection(TextSelection.near(tr.doc.resolve(found + 3)));
      dispatch(tr.scrollIntoView());
    }
    return true;
  }

  function usedFootnotes(doc) {
    var used = Object.create(null);
    doc.descendants(function (node) {
      if (node.type === nodes.footnote_ref || node.type === nodes.footnote_definition) used[node.attrs.label] = true;
      if (node.type === nodes.raw_block) {
        (node.textContent.match(/\[\^[^\]\s]+\]/g) || []).forEach(function (match) {
          used[match.slice(2, -1)] = true;
        });
      }
    });
    return used;
  }

  function insertFootnote(text) {
    return function (state, dispatch) {
      if (dispatch) {
        var used = usedFootnotes(state.doc);
        var number = 1;
        while (used[String(number)]) number++;
        var label = String(number);
        var tr = state.tr.replaceSelectionWith(nodes.footnote_ref.create({ label: label }), true);
        var paragraph = nodes.paragraph.create(null, text ? schema.text(text) : null);
        tr.insert(tr.doc.content.size, nodes.footnote_definition.create({ label: label }, paragraph));
        dispatch(tr.scrollIntoView());
      }
      return true;
    };
  }

  function insertImage(attrs, pos) {
    return function (state, dispatch) {
      if (!safeUrl(attrs.src, true)) return false;
      if (dispatch) {
        var image = nodes.image.create(attrs);
        var tr = pos === undefined ? state.tr.replaceSelectionWith(image) : state.tr.insert(pos, image);
        dispatch(tr.scrollIntoView());
      }
      return true;
    };
  }

  function selectedImage(state) {
    var selection = state.selection;
    return selection instanceof NodeSelection && selection.node.type === nodes.image ? selection.node : null;
  }

  function setImageAlt(alt) {
    return function (state, dispatch) {
      var image = selectedImage(state);
      if (!image) return false;
      if (dispatch) {
        dispatch(state.tr.setNodeMarkup(state.selection.from, null, Object.assign({}, image.attrs, { alt: alt })));
      }
      return true;
    };
  }

  // The whole link around the cursor, so editing it never leaves part of it behind.
  function linkRange(state) {
    var $from = state.selection.$from;
    var parent = $from.parent;
    if (!parent.inlineContent) return null;
    var position = $from.parentOffset;
    var ranges = [];
    parent.forEach(function (child, offset) {
      ranges.push({ node: child, from: offset, to: offset + child.nodeSize });
    });
    var hit = ranges.find(function (range) {
      return range.from <= position && position <= range.to && marks.link.isInSet(range.node.marks);
    });
    if (!hit) return null;
    var mark = marks.link.isInSet(hit.node.marks);
    var first = ranges.indexOf(hit);
    var last = first;
    while (first > 0 && mark.isInSet(ranges[first - 1].node.marks)) first--;
    while (last < ranges.length - 1 && mark.isInSet(ranges[last + 1].node.marks)) last++;
    var start = $from.start();
    return { from: start + ranges[first].from, to: start + ranges[last].to, mark: mark };
  }

  function setLink(attrs, text) {
    return function (state, dispatch) {
      if (!safeUrl(attrs.href)) return false;
      if (dispatch) {
        var tr = state.tr;
        var range = linkRange(state);
        var from = range ? range.from : state.selection.from;
        var to = range ? range.to : state.selection.to;
        var mark = marks.link.create({ href: attrs.href, title: attrs.title || null });
        if (text !== undefined && text !== state.doc.textBetween(from, to, " ", " ")) {
          tr.replaceWith(from, to, schema.text(text || attrs.href, [mark]));
          to = from + (text || attrs.href).length;
        } else if (from === to) {
          tr.insert(from, schema.text(attrs.href, [mark]));
          to = from + attrs.href.length;
        } else {
          tr.removeMark(from, to, marks.link).addMark(from, to, mark);
        }
        tr.setSelection(TextSelection.create(tr.doc, to)).removeStoredMark(marks.link);
        dispatch(tr.scrollIntoView());
      }
      return true;
    };
  }

  function removeLink(state, dispatch) {
    var range = linkRange(state);
    if (!range) return false;
    if (dispatch) dispatch(state.tr.removeMark(range.from, range.to, marks.link));
    return true;
  }

  function setCodeLanguage(language) {
    return function (state, dispatch) {
      var code = ancestor(state, [nodes.code_block]);
      if (!code) return false;
      if (dispatch) dispatch(state.tr.setNodeMarkup(code.pos, null, { language: language.replace(/\s+/g, " ").trim() }));
      return true;
    };
  }

  function setCallout(changes) {
    return function (state, dispatch) {
      var box = ancestor(state, [nodes.callout]);
      if (!box) return false;
      if (dispatch) dispatch(state.tr.setNodeMarkup(box.pos, null, Object.assign({}, box.node.attrs, changes)));
      return true;
    };
  }

  function isMarkActive(state, type) {
    var selection = state.selection;
    if (selection.empty) return !!type.isInSet(state.storedMarks || selection.$from.marks());
    return state.doc.rangeHasMark(selection.from, selection.to, type);
  }

  var commands = {
    bold: function () { return cmd.toggleMark(marks.strong); },
    italic: function () { return cmd.toggleMark(marks.em); },
    strike: function () { return cmd.toggleMark(marks.strike); },
    code: function () { return cmd.toggleMark(marks.code); },
    paragraph: function () { return cmd.setBlockType(nodes.paragraph); },
    heading: function (level) { return toggleBlock(nodes.heading, { level: level || 2 }); },
    codeblock: function () { return toggleBlock(nodes.code_block); },
    quote: function () { return toggleWrap(nodes.blockquote); },
    callout: function () { return toggleWrap(nodes.callout, { kind: "tip", title: "" }); },
    ul: function () { return toggleList(nodes.bullet_list); },
    ol: function () { return toggleList(nodes.ordered_list); },
    task: function () { return toggleTask; },
    check: function () { return toggleChecked; },
    hr: function () { return insertRule; },
    table: function () { return insertTable; },
    footnote: insertFootnote,
    image: insertImage,
    imageAlt: setImageAlt,
    link: setLink,
    unlink: function () { return removeLink; },
    language: setCodeLanguage,
    calloutSet: setCallout,
    undo: function () { return kit.undo; },
    redo: function () { return kit.redo; },
    addRowBefore: function () { return tables.addRowBefore; },
    addRowAfter: function () { return tables.addRowAfter; },
    addColumnBefore: function () { return tables.addColumnBefore; },
    addColumnAfter: function () { return tables.addColumnAfter; },
    deleteRow: function () { return tables.deleteRow; },
    deleteColumn: function () { return tables.deleteColumn; },
    deleteTable: function () { return tables.deleteTable; },
  };

  /* What the toolbar should show for the current selection. */
  function describe(state) {
    var parent = state.selection.$from.parent;
    var list = ancestor(state, [nodes.bullet_list, nodes.ordered_list]);
    var item = ancestor(state, [nodes.list_item]);
    var box = ancestor(state, [nodes.callout]);
    var code = parent.type === nodes.code_block ? parent : null;
    var image = selectedImage(state);
    var link = linkRange(state);
    return {
      bold: isMarkActive(state, marks.strong),
      italic: isMarkActive(state, marks.em),
      strike: isMarkActive(state, marks.strike),
      code: isMarkActive(state, marks.code),
      link: !!link || isMarkActive(state, marks.link),
      linkHref: link ? link.mark.attrs.href : "",
      linkTitle: link ? link.mark.attrs.title || "" : "",
      linkText: link ? state.doc.textBetween(link.from, link.to, " ", " ") : state.doc.textBetween(state.selection.from, state.selection.to, " ", " "),
      quote: !!ancestor(state, [nodes.blockquote]),
      ul: !!list && list.node.type === nodes.bullet_list && !(item && item.node.attrs.checked !== null),
      ol: !!list && list.node.type === nodes.ordered_list,
      task: !!item && item.node.attrs.checked !== null,
      checked: !!item && item.node.attrs.checked === true,
      callout: !!box,
      calloutKind: box ? box.node.attrs.kind : "",
      calloutTitle: box ? box.node.attrs.title : "",
      codeblock: !!code,
      language: code ? code.attrs.language : "",
      table: tables.isInTable(state),
      raw: parent.type === nodes.raw_block,
      image: image ? { alt: image.attrs.alt, src: image.attrs.src } : null,
      heading: parent.type === nodes.heading ? parent.attrs.level : 0,
    };
  }

  // ---------------------------------------------------------------- typing shortcuts

  function markRule(pattern, type) {
    return new rules.InputRule(pattern, function (state, match, start, end) {
      var content = match[2];
      var from = start + match[1].length;
      var tr = state.tr.replaceWith(from, end, schema.text(content, [type.create()].concat(state.selection.$from.marks())));
      return tr.removeStoredMark(type);
    });
  }

  function typingRules() {
    return rules.inputRules({
      rules: [
        rules.textblockTypeInputRule(/^(#{1,6})\s$/, nodes.heading, function (match) {
          return { level: match[1].length };
        }),
        rules.textblockTypeInputRule(/^```([\w+#.-]*)\s$/, nodes.code_block, function (match) {
          return { language: match[1] };
        }),
        rules.wrappingInputRule(/^\s*>\s$/, nodes.blockquote),
        rules.wrappingInputRule(/^\s*([-+*])\s$/, nodes.bullet_list),
        rules.wrappingInputRule(/^(\d+)[.)]\s$/, nodes.ordered_list, function (match) {
          return { order: Number(match[1]) };
        }, function (match, node) {
          return node.childCount + node.attrs.order === Number(match[1]);
        }),
        new rules.InputRule(/^\[( |x)\]\s$/, function (state, match, start, end) {
          var item = ancestor(state, [nodes.list_item]);
          if (!item || item.node.childCount !== 1) return null;
          return state.tr.delete(start, end).setNodeMarkup(item.pos, null, { checked: match[1] === "x" });
        }),
        new rules.InputRule(/^---\s$/, function (state, _match, start, end) {
          var $start = state.doc.resolve(start);
          if ($start.parent.type !== nodes.paragraph) return null;
          return state.tr.replaceRangeWith($start.before(), $start.after(), nodes.horizontal_rule.create());
        }),
        markRule(/(^|[^*\\])\*\*([^*\s](?:[^*]*[^*\s])?)\*\*$/, marks.strong),
        markRule(/(^|[^*\\])\*([^*\s](?:[^*]*[^*\s])?)\*$/, marks.em),
        markRule(/(^|[^\w\\])_([^_\s](?:[^_]*[^_\s])?)_$/, marks.em),
        markRule(/(^|[^~\\])~~([^~\s](?:[^~]*[^~\s])?)~~$/, marks.strike),
        markRule(/(^|[^`\\])`([^`]+)`$/, marks.code),
      ],
    });
  }

  // ---------------------------------------------------------------- key bindings

  var chain = cmd.chainCommands;

  function nextCell(direction) {
    return function (state, dispatch, view) {
      if (!tables.isInTable(state)) return false;
      if (tables.goToNextCell(direction)(state, dispatch, view)) return true;
      if (direction < 0) return false;
      // Tab in the last cell adds a row, as in a spreadsheet. Escape always leaves the editor.
      if (dispatch) {
        var added = null;
        tables.addRowAfter(state, function (tr) { added = tr; });
        if (added) {
          var next = state.apply(added);
          dispatch(added);
          if (view) tables.goToNextCell(1)(view.state, view.dispatch);
          else tables.goToNextCell(1)(next, function () {});
        }
      }
      return true;
    };
  }

  // A hard line break, where one is allowed. Table cells and headings can't hold one in Markdown.
  function hardBreak(state, dispatch) {
    if (!state.selection.$from.parent.type.contentMatch.matchType(nodes.hard_break)) return false;
    if (dispatch) dispatch(state.tr.replaceSelectionWith(nodes.hard_break.create()).scrollIntoView());
    return true;
  }

  function bindings() {
    var keys = {
      "Mod-z": kit.undo,
      "Shift-Mod-z": kit.redo,
      "Mod-y": kit.redo,
      "Mod-b": commands.bold(),
      "Mod-i": commands.italic(),
      "Mod-Shift-x": commands.strike(),
      "Mod-e": commands.code(),
      "Mod-Alt-0": commands.paragraph(),
      "Mod-Alt-c": commands.codeblock(),
      "Mod-Shift-b": commands.quote(),
      "Mod-Shift-7": commands.ol(),
      "Mod-Shift-8": commands.ul(),
      "Mod-Shift-9": toggleTask,
      Tab: chain(nextCell(1), lists.sinkListItem(nodes.list_item)),
      "Shift-Tab": chain(nextCell(-1), lists.liftListItem(nodes.list_item)),
      Enter: chain(function (state, dispatch, view) {
        return tables.isInTable(state) ? nextCell(1)(state, dispatch, view) : false;
      }, splitItem),
      "Mod-Enter": chain(cmd.exitCode, hardBreak),
      "Shift-Enter": chain(cmd.exitCode, hardBreak),
      Backspace: rules.undoInputRule,
    };
    [1, 2, 3, 4, 5, 6].forEach(function (level) {
      keys["Mod-Alt-" + level] = commands.heading(level);
    });
    return keys;
  }

  // ---------------------------------------------------------------- plugins

  // Nothing can be typed after these with the cursor alone, so keep a line below them.
  var NEEDS_A_LINE_AFTER = [nodes.table, nodes.code_block, nodes.raw_block, nodes.horizontal_rule];

  var trailingParagraph = new Plugin({
    key: new PluginKey("trailingParagraph"),
    appendTransaction: function (_transactions, _old, state) {
      var last = state.doc.lastChild;
      if (!last || NEEDS_A_LINE_AFTER.indexOf(last.type) === -1) return null;
      return state.tr.insert(state.doc.content.size, nodes.paragraph.create()).setMeta("addToHistory", false);
    },
  });

  var uploadKey = new PluginKey("uploads");

  function createState(data, options) {
    var read = documentFrom(data);
    var state = EditorState.create({
      doc: read.doc,
      plugins: pluginsFor(options || {}),
    });
    return { state: state, origin: read.origin };
  }

  function pluginsFor(options) {
    var list = [
      kit.history(),
      typingRules(),
      kit.keymap(bindings()),
      kit.keymap(cmd.baseKeymap),
      tables.tableEditing({ allowTableNodeSelection: false }),
      trailingParagraph,
    ];
    if (options.extraPlugins) list = options.extraPlugins.concat(list);
    return list;
  }

  // ---------------------------------------------------------------- the view (browser only)

  function TaskItemView(node, view, getPos) {
    this.node = node;
    this.dom = document.createElement("li");
    if (node.attrs.checked === null) {
      this.contentDOM = this.dom;
      return;
    }
    this.dom.className = "task-list-item";
    var box = document.createElement("input");
    box.type = "checkbox";
    box.className = "task-list-item-checkbox";
    box.checked = node.attrs.checked;
    box.contentEditable = "false";
    box.tabIndex = -1;
    box.setAttribute("aria-label", "Done");
    box.addEventListener("mousedown", function (event) {
      event.preventDefault();
      var pos = getPos();
      if (typeof pos === "number") {
        var current = view.state.doc.nodeAt(pos);
        view.dispatch(view.state.tr.setNodeMarkup(pos, null, { checked: !current.attrs.checked }));
      }
    });
    this.box = box;
    this.contentDOM = document.createElement("div");
    this.contentDOM.className = "task-list-body";
    this.dom.appendChild(box);
    this.dom.appendChild(this.contentDOM);
  }

  TaskItemView.prototype.update = function (node) {
    if (node.type !== this.node.type || (node.attrs.checked === null) !== (this.node.attrs.checked === null)) return false;
    this.node = node;
    if (this.box) this.box.checked = node.attrs.checked;
    return true;
  };

  TaskItemView.prototype.stopEvent = function (event) {
    return event.target === this.box;
  };

  TaskItemView.prototype.ignoreMutation = function (mutation) {
    return !!this.box && (mutation.target === this.box || (mutation.type === "attributes" && mutation.target === this.dom));
  };

  var LOOKS_LIKE_MARKDOWN = /^(#{1,6} |[-*+] |\d+[.)] |> |```|~~~|:::|\|.*\|\s*$)|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^)\n]+\)/m;
  var LOOKS_LIKE_URL = /^(https?:\/\/|mailto:)\S+$/i;

  /*
   * Show the editor. ``options``: place, label, describedBy, placeholder, onChange(markdown),
   * onSelection(description), onImages(files, pos), onMarkdownPaste(text), onNotice(message),
   * onLinkKey(), onEscape().
   */
  function mount(data, options) {
    var uploads = new Plugin({
      key: uploadKey,
      state: {
        init: function () { return kit.view.DecorationSet.empty; },
        apply: function (tr, set) {
          var next = set.map(tr.mapping, tr.doc);
          var action = tr.getMeta(uploadKey);
          if (action && action.add) {
            var widget = document.createElement("span");
            widget.className = "visual-uploading";
            widget.textContent = "Uploading " + action.add.name + "…";
            next = next.add(tr.doc, [kit.view.Decoration.widget(action.add.pos, widget, { id: action.add.id })]);
          } else if (action && action.remove) {
            next = next.remove(next.find(null, null, function (spec) { return spec.id === action.remove; }));
          }
          return next;
        },
      },
      props: {
        decorations: function (state) { return this.getState(state); },
      },
    });

    var placeholder = new Plugin({
      key: new PluginKey("placeholder"),
      props: {
        decorations: function (state) {
          var doc = state.doc;
          if (doc.childCount !== 1 || doc.firstChild.type !== nodes.paragraph || doc.firstChild.content.size) return null;
          return kit.view.DecorationSet.create(doc, [
            kit.view.Decoration.node(0, doc.firstChild.nodeSize, {
              class: "is-empty",
              "data-placeholder": options.placeholder || "",
            }),
          ]);
        },
      },
    });

    var created = createState(data, {
      extraPlugins: [
        uploads,
        placeholder,
        kit.keymap({
          "Mod-k": function () {
            if (options.onLinkKey) options.onLinkKey();
            return true;
          },
          Escape: function () {
            if (options.onEscape) options.onEscape();
            return !!options.onEscape;
          },
          "Alt-F10": function () {
            if (options.onEscape) options.onEscape();
            return !!options.onEscape;
          },
        }),
        kit.dropCursor({ class: "visual-drop-cursor" }),
        kit.gapCursor(),
      ],
    });

    var origin = created.origin;
    var attributes = {
      class: "prose visual-content",
      role: "textbox",
      "aria-multiline": "true",
      "aria-label": options.label || "Your piece",
      spellcheck: "true",
    };
    if (options.describedBy) attributes["aria-describedby"] = options.describedBy;

    var view = new kit.view.EditorView(options.place, {
      state: created.state,
      attributes: attributes,
      nodeViews: {
        list_item: function (node, editorView, getPos) {
          return new TaskItemView(node, editorView, getPos);
        },
      },
      dispatchTransaction: function (tr) {
        var state = view.state.apply(tr);
        view.updateState(state);
        if (tr.docChanged && options.onChange) options.onChange();
        if (options.onSelection) options.onSelection(describe(view.state));
      },
      handlePaste: function (editorView, event) {
        var clipboard = event.clipboardData;
        if (!clipboard) return false;
        var files = Array.prototype.filter.call(clipboard.files || [], function (file) {
          return /^image\//.test(file.type);
        });
        var html = clipboard.getData("text/html");
        var text = clipboard.getData("text/plain");
        if (files.length && !html) {
          event.preventDefault();
          if (options.onImages) options.onImages(files, editorView.state.selection.from);
          return true;
        }
        var parent = editorView.state.selection.$from.parent;
        if (parent.type.spec.code) return false;
        if (html && /<img\b[^>]*\bsrc\s*=\s*["']?data:/i.test(html) && options.onNotice) {
          options.onNotice("Images embedded in what you pasted were left out. Upload them with the image button.");
        }
        if (!html && text) {
          var selection = editorView.state.selection;
          if (!selection.empty && LOOKS_LIKE_URL.test(text.trim())) {
            setLink({ href: text.trim() })(editorView.state, editorView.dispatch);
            return true;
          }
          if (LOOKS_LIKE_MARKDOWN.test(text) && options.onMarkdownPaste) {
            options.onMarkdownPaste(text);
            return true;
          }
        }
        return false;
      },
      handleDrop: function (editorView, event, _slice, moved) {
        var files = event.dataTransfer && event.dataTransfer.files;
        if (moved || !files || !files.length) return false;
        var images = Array.prototype.filter.call(files, function (file) {
          return /^image\//.test(file.type);
        });
        if (!images.length) return false;
        event.preventDefault();
        var spot = editorView.posAtCoords({ left: event.clientX, top: event.clientY });
        if (options.onImages) options.onImages(images, spot ? spot.pos : editorView.state.selection.from);
        return true;
      },
    });

    var uploadCount = 0;

    return {
      view: view,
      markdown: function () { return toMarkdown(view.state.doc, origin); },
      run: function (command) {
        view.focus();
        return command(view.state, view.dispatch, view);
      },
      describe: function () { return describe(view.state); },
      focus: function () { view.focus(); },
      destroy: function () { view.destroy(); },
      /* Hold a place for an image while it uploads, and return how to fill it in. */
      startUpload: function (name, pos) {
        var id = "upload-" + ++uploadCount;
        var place = pos === undefined ? view.state.selection.from : pos;
        view.dispatch(view.state.tr.setMeta(uploadKey, { add: { id: id, pos: place, name: name } }).setMeta("addToHistory", false));
        return {
          finish: function (attrs) {
            var found = uploadKey.getState(view.state).find(null, null, function (spec) { return spec.id === id; });
            var at = found.length ? found[0].from : view.state.selection.from;
            var tr = view.state.tr.setMeta(uploadKey, { remove: id });
            if (attrs) tr.insert(at, nodes.image.create(attrs));
            view.dispatch(tr);
          },
        };
      },
      /* Insert Markdown the server has read. A single paragraph joins the current line. */
      insertBlocks: function (blocks) {
        var read = documentFrom({ blocks: blocks });
        var fragment = read.doc.content;
        var single = fragment.childCount === 1 && fragment.firstChild.type === nodes.paragraph;
        var slice = new Slice(Fragment.from(fragment), single ? 1 : 0, single ? 1 : 0);
        view.dispatch(view.state.tr.replaceSelection(slice).scrollIntoView());
      },
    };
  }

  root.QuillSailVisual = {
    CALLOUT_KINDS: CALLOUT_KINDS,
    commands: commands,
    createState: createState,
    describe: describe,
    documentFrom: documentFrom,
    mount: mount,
    safeUrl: safeUrl,
    schema: schema,
    toMarkdown: toMarkdown,
  };
})(typeof window !== "undefined" ? window : globalThis);
