/*
 * The writing editor. A piece is written in one of three ways: Visual, Markdown or HTML.
 * The textarea always holds the text that gets saved, so the page works without JavaScript
 * and every other feature here (preview, word count, local backup) reads from one place.
 * Visual mode keeps the textarea up to date as Markdown (see visual-editor.js).
 *
 * Markup expected: see templates/write/edit.html.
 */
(function () {
  "use strict";

  var editor = document.querySelector("[data-editor]");
  if (!editor) return;

  var textarea = editor.querySelector("[data-editor-input]");
  var preview = editor.querySelector("[data-editor-preview]");
  var wordCount = editor.querySelector("[data-word-count]");
  var visualHost = editor.querySelector("[data-visual-editor]");
  var context = editor.querySelector("[data-visual-context]");
  var toolbar = editor.querySelector("[data-editor-toolbar]");
  var noticeBox = editor.querySelector("[data-editor-notice]");
  var modeLabel = editor.querySelector("[data-mode-label]");
  var styleSelect = editor.querySelector("[data-visual-style]");
  var form = textarea.form;
  var formatField = form.querySelector('[name="body_format"]');
  var maxWords = parseInt(editor.getAttribute("data-max-words") || "0", 10);
  var backupKey = editor.getAttribute("data-backup-key");
  var titleInput = form.querySelector('[name="title"]');
  var subtitleInput = form.querySelector('[name="subtitle"]');
  var dirty = false;

  var Visual = window.QuillSailVisual;
  var canUseVisual = !!Visual && typeof HTMLDialogElement === "function" && !!window.Copydesk;
  var PREFERENCE_KEY = "cd-editor-mode";
  var MODE_LABELS = {
    visual: "Visual · Saved as Markdown · Ctrl+S saves",
    markdown: "Markdown · Ctrl+S saves",
    html: "HTML · Scripts and styles are removed · Ctrl+S saves",
    markdown_html: "Markdown with HTML · Scripts and styles are removed · Ctrl+S saves",
  };

  var mode = "markdown";
  var previewing = false;
  var busy = false;
  var visual = null; // the mounted visual editor, while there is one
  var visualText = null; // the text the mounted editor last matched
  var syncTimer = null;
  var conversion = null; // what the last conversion replaced, so switching back is exact

  function format() {
    return formatField.value;
  }

  function showNotice(message) {
    noticeBox.textContent = message || "";
    noticeBox.hidden = !message;
  }

  // ------------------------------------------------------------ dialogs

  function open(dialog) {
    return new Promise(function (resolve) {
      dialog.returnValue = "";
      dialog.addEventListener("close", function done() {
        dialog.removeEventListener("close", done);
        resolve(dialog.returnValue);
      });
      dialog.showModal();
    });
  }

  var linkDialog = document.querySelector("[data-link-dialog]");
  var linkUrl = linkDialog.querySelector("[data-link-url]");
  var linkText = linkDialog.querySelector("[data-link-text]");
  var linkError = linkDialog.querySelector("[data-link-error]");
  var linkRemove = linkDialog.querySelector("[data-link-remove]");

  linkDialog.querySelector("form").addEventListener("submit", function (event) {
    var button = event.submitter;
    if (!button || button.value !== "ok") return;
    var url = linkUrl.value.trim();
    var safe = url && (!Visual || Visual.safeUrl(url));
    linkError.hidden = !!safe;
    linkError.textContent = safe ? "" : "Enter a web address that starts with https:// or mailto:, or a path on this site.";
    if (!safe) {
      event.preventDefault();
      linkUrl.focus();
    }
  });

  /* Resolves with {url, text}, {remove: true}, or null if the writer cancelled. */
  function askLink(current) {
    linkUrl.value = current.url || "https://";
    linkText.value = current.text || "";
    linkError.hidden = true;
    linkRemove.hidden = !current.url;
    return open(linkDialog).then(function (result) {
      if (result === "remove") return { remove: true };
      if (result !== "ok") return null;
      return { url: linkUrl.value.trim(), text: linkText.value };
    });
  }

  var imageDialog = document.querySelector("[data-image-dialog]");
  var imageAlt = imageDialog.querySelector("[data-image-alt]");

  function askImageAlt(current) {
    imageAlt.value = current || "";
    return open(imageDialog).then(function () {
      return imageAlt.value.trim();
    });
  }

  var footnoteDialog = document.querySelector("[data-footnote-dialog]");
  var footnoteText = footnoteDialog.querySelector("[data-footnote-text]");

  function askFootnote() {
    footnoteText.value = "";
    return open(footnoteDialog).then(function (result) {
      return result === "ok" ? footnoteText.value.trim() : null;
    });
  }

  var convertDialog = document.querySelector("[data-convert-dialog]");
  var convertWarnings = convertDialog.querySelector("[data-convert-warnings]");

  function confirmConversion(warnings) {
    convertWarnings.textContent = "";
    warnings.forEach(function (warning) {
      var item = document.createElement("li");
      item.textContent = warning;
      convertWarnings.appendChild(item);
    });
    convertWarnings.hidden = !warnings.length;
    return open(convertDialog).then(function (result) {
      return result === "ok";
    });
  }

  // ------------------------------------------------------------ typing formatting by hand

  function selection() {
    return { start: textarea.selectionStart, end: textarea.selectionEnd, text: textarea.value };
  }

  function replaceRange(start, end, insert, selectStart, selectEnd) {
    textarea.focus();
    textarea.setRangeText(insert, start, end, "end");
    if (selectStart !== undefined) {
      textarea.setSelectionRange(start + selectStart, start + (selectEnd !== undefined ? selectEnd : selectStart));
    }
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function wrap(before, after, placeholder) {
    var s = selection();
    var chosen = s.text.slice(s.start, s.end) || placeholder;
    replaceRange(s.start, s.end, before + chosen + after, before.length, before.length + chosen.length);
  }

  function selectedLines() {
    var s = selection();
    var lineStart = s.text.lastIndexOf("\n", s.start - 1) + 1;
    var lineEnd = s.text.indexOf("\n", s.end);
    if (lineEnd === -1) lineEnd = s.text.length;
    return { start: lineStart, end: lineEnd, lines: s.text.slice(lineStart, lineEnd).split("\n") };
  }

  function prefixLines(prefix, numbered) {
    var range = selectedLines();
    var already = range.lines.every(function (line) {
      return numbered ? /^\d+\.\s/.test(line) : line.indexOf(prefix) === 0;
    });
    var result = range.lines
      .map(function (line, i) {
        if (already) return numbered ? line.replace(/^\d+\.\s/, "") : line.slice(prefix.length);
        return (numbered ? i + 1 + ". " : prefix) + line;
      })
      .join("\n");
    replaceRange(range.start, range.end, result, 0, result.length);
  }

  function wrapLinesHtml(open, close, itemOpen, itemClose) {
    var range = selectedLines();
    var items = range.lines.map(function (line) {
      return itemOpen + line + itemClose;
    });
    var result = open + (open ? "\n" : "") + items.join("\n") + (close ? "\n" : "") + close;
    replaceRange(range.start, range.end, result, 0, result.length);
  }

  function insertBlock(block, selectFrom, selectLength) {
    var s = selection();
    var before = s.start > 0 && s.text.charAt(s.start - 1) !== "\n" ? "\n\n" : "";
    replaceRange(s.start, s.end, before + block + "\n", before.length + selectFrom, before.length + selectFrom + selectLength);
  }

  function sourceLink() {
    var s = selection();
    var chosen = s.text.slice(s.start, s.end);
    askLink({ text: chosen }).then(function (answer) {
      if (!answer || !answer.url) return;
      var label = answer.text || "link text";
      var isHtml = format() === "html";
      var lead = isHtml ? '<a href="' + answer.url.replace(/"/g, "&quot;") + '">' : "[";
      var tail = isHtml ? "</a>" : "](" + answer.url + ")";
      replaceRange(s.start, s.end, lead + label + tail, lead.length, lead.length + label.length);
    });
  }

  function sourceFootnote() {
    var start = textarea.selectionStart;
    var end = textarea.selectionEnd;
    askFootnote().then(function (note) {
      if (note === null) return;
      var used = textarea.value.match(/\[\^(\d+)\]/g) || [];
      var number = 1;
      while (used.indexOf("[^" + number + "]") !== -1) number++;
      var marker = "[^" + number + "]";
      replaceRange(start, end, marker);
      var at = textarea.value.length;
      var gap = /\n\n$/.test(textarea.value) ? "" : /\n$/.test(textarea.value) ? "\n" : "\n\n";
      textarea.setRangeText(gap + marker + ": " + note + "\n", at, at, "preserve");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  function markdownTools() {
    return {
      bold: function () { wrap("**", "**", "bold text"); },
      italic: function () { wrap("_", "_", "italic text"); },
      strike: function () { wrap("~~", "~~", "struck text"); },
      heading: function () { prefixLines("## "); },
      link: sourceLink,
      quote: function () { prefixLines("> "); },
      code: function () {
        var s = selection();
        var chosen = s.text.slice(s.start, s.end);
        if (chosen.indexOf("\n") !== -1) insertBlock("```\n" + chosen + "\n```", 4, chosen.length);
        else wrap("`", "`", "code");
      },
      codeblock: function () {
        var s = selection();
        var chosen = s.text.slice(s.start, s.end) || "code";
        insertBlock("```\n" + chosen + "\n```", 4, chosen.length);
      },
      ul: function () { prefixLines("- "); },
      ol: function () { prefixLines("", true); },
      task: function () { prefixLines("- [ ] "); },
      table: function () { insertBlock("| Column | Column |\n| --- | --- |\n| Cell | Cell |", 2, 6); },
      callout: function () {
        var s = selection();
        var chosen = s.text.slice(s.start, s.end) || "Something worth calling out.";
        insertBlock("::: tip\n" + chosen + "\n:::", 8, chosen.length);
      },
      footnote: sourceFootnote,
      hr: function () { insertBlock("---", 3, 0); },
      image: function () { fileInput.click(); },
    };
  }

  function htmlTools() {
    return {
      bold: function () { wrap("<strong>", "</strong>", "bold text"); },
      italic: function () { wrap("<em>", "</em>", "italic text"); },
      strike: function () { wrap("<s>", "</s>", "struck text"); },
      heading: function () { wrap("<h2>", "</h2>", "Heading"); },
      link: sourceLink,
      quote: function () { wrap("<blockquote>", "</blockquote>", "A quotation"); },
      code: function () { wrap("<code>", "</code>", "code"); },
      codeblock: function () { wrap("<pre><code>", "</code></pre>", "code"); },
      ul: function () { wrapLinesHtml("<ul>", "</ul>", "  <li>", "</li>"); },
      ol: function () { wrapLinesHtml("<ol>", "</ol>", "  <li>", "</li>"); },
      task: function () { wrapLinesHtml("<ul>", "</ul>", '  <li><input type="checkbox"> ', "</li>"); },
      table: function () {
        insertBlock("<table>\n  <tr><th>Column</th><th>Column</th></tr>\n  <tr><td>Cell</td><td>Cell</td></tr>\n</table>", 19, 6);
      },
      callout: function () {
        wrap('<aside class="callout callout-tip">', "</aside>", "Something worth calling out.");
      },
      hr: function () { insertBlock("<hr>", 4, 0); },
      image: function () { fileInput.click(); },
    };
  }

  // ------------------------------------------------------------ visual tools

  function visualLink() {
    var state = visual.describe();
    askLink({ url: state.linkHref, text: state.linkText }).then(function (answer) {
      if (!answer) return visual.focus();
      if (answer.remove) return visual.run(Visual.commands.unlink());
      visual.run(Visual.commands.link({ href: answer.url, title: state.linkTitle || null }, answer.text));
    });
  }

  function visualAlt() {
    var state = visual.describe();
    if (!state.image) return;
    askImageAlt(state.image.alt).then(function (alt) {
      visual.run(Visual.commands.imageAlt(alt));
    });
  }

  function visualFootnote() {
    askFootnote().then(function (note) {
      if (note === null) return visual.focus();
      visual.run(Visual.commands.footnote(note));
    });
  }

  function visualTools() {
    var tools = {};
    ["bold", "italic", "strike", "code", "codeblock", "quote", "callout", "ul", "ol", "task", "check", "hr", "table",
      "undo", "redo", "addRowBefore", "addRowAfter", "addColumnBefore", "addColumnAfter", "deleteRow", "deleteColumn",
      "deleteTable"].forEach(function (name) {
      tools[name] = function () { visual.run(Visual.commands[name]()); };
    });
    tools.link = visualLink;
    tools.footnote = visualFootnote;
    tools.image = function () { fileInput.click(); };
    tools.imageAlt = visualAlt;
    return tools;
  }

  function currentTools() {
    if (mode === "visual") return visualTools();
    return format() === "html" ? htmlTools() : markdownTools();
  }

  editor.querySelectorAll("[data-md]").forEach(function (button) {
    button.addEventListener("click", function () {
      var tool = currentTools()[button.getAttribute("data-md")];
      if (tool) tool();
    });
  });

  styleSelect.addEventListener("change", function () {
    if (!visual) return;
    var value = styleSelect.value;
    visual.run(value === "paragraph" ? Visual.commands.paragraph() : Visual.commands.heading(Number(value)));
  });

  var languageInput = editor.querySelector("[data-code-language]");
  var calloutKind = editor.querySelector("[data-callout-kind]");
  var calloutTitle = editor.querySelector("[data-callout-title]");

  function applyWithoutFocus(command) {
    if (visual) command(visual.view.state, visual.view.dispatch);
  }

  languageInput.addEventListener("input", function () {
    applyWithoutFocus(Visual.commands.language(languageInput.value));
  });
  calloutKind.addEventListener("change", function () {
    applyWithoutFocus(Visual.commands.calloutSet({ kind: calloutKind.value }));
  });
  calloutTitle.addEventListener("input", function () {
    applyWithoutFocus(Visual.commands.calloutSet({ title: calloutTitle.value }));
  });
  // Enter in these fields returns to the writing, and must never submit the piece.
  [languageInput, calloutTitle].forEach(function (input) {
    input.addEventListener("keydown", function (event) {
      if (event.key === "Enter") {
        event.preventDefault();
        if (visual) visual.focus();
      }
    });
  });

  function setPressed(name, value) {
    var button = toolbar.querySelector('[data-md="' + name + '"]');
    if (button) button.setAttribute("aria-pressed", String(!!value));
  }

  function updateVisualTools(state) {
    ["bold", "italic", "strike", "code", "link", "ul", "ol", "task", "quote", "codeblock", "callout"].forEach(function (name) {
      setPressed(name, state[name]);
    });
    if (document.activeElement !== styleSelect) {
      styleSelect.value = state.heading ? String(state.heading) : "paragraph";
    }
    var groups = {
      table: state.table,
      code: state.codeblock,
      callout: state.callout,
      task: state.task,
      image: !!state.image,
      raw: state.raw,
    };
    var any = false;
    Object.keys(groups).forEach(function (name) {
      var group = context.querySelector('[data-context="' + name + '"]');
      group.hidden = !groups[name];
      any = any || !!groups[name];
    });
    context.hidden = !any;
    if (state.codeblock && document.activeElement !== languageInput) languageInput.value = state.language;
    if (state.callout) {
      if (document.activeElement !== calloutKind) calloutKind.value = state.calloutKind;
      if (document.activeElement !== calloutTitle) calloutTitle.value = state.calloutTitle;
    }
    if (state.task) context.querySelector("[data-check-label]").textContent = state.checked ? "Mark as not done" : "Mark as done";
  }

  function clearPressed() {
    toolbar.querySelectorAll("[data-md]").forEach(function (button) {
      button.removeAttribute("aria-pressed");
    });
  }

  // ------------------------------------------------------------ toolbar keyboard

  // Arrow keys move along the toolbar, so one Tab reaches it and the next leaves it.
  function toolbarButtons() {
    return Array.prototype.filter.call(toolbar.querySelectorAll("button"), function (button) {
      return !button.hidden && !button.disabled;
    });
  }

  function focusTool(button) {
    toolbarButtons().forEach(function (item) {
      item.tabIndex = item === button ? 0 : -1;
    });
    if (button) button.focus();
  }

  toolbar.addEventListener("keydown", function (event) {
    if (event.target.tagName !== "BUTTON") {
      if (event.key === "Escape" && visual && mode === "visual") visual.focus();
      return;
    }
    var buttons = toolbarButtons();
    var index = buttons.indexOf(event.target);
    var next = null;
    if (event.key === "ArrowRight") next = buttons[(index + 1) % buttons.length];
    else if (event.key === "ArrowLeft") next = buttons[(index - 1 + buttons.length) % buttons.length];
    else if (event.key === "Home") next = buttons[0];
    else if (event.key === "End") next = buttons[buttons.length - 1];
    else if (event.key === "Escape") {
      event.preventDefault();
      if (mode === "visual" && visual) visual.focus();
      else textarea.focus();
      return;
    }
    if (next) {
      event.preventDefault();
      focusTool(next);
    }
  });

  function resetToolbarFocus() {
    var buttons = toolbarButtons();
    buttons.forEach(function (item, index) {
      item.tabIndex = index === 0 ? 0 : -1;
    });
  }

  // ------------------------------------------------------------ source shortcuts

  textarea.addEventListener("keydown", function (event) {
    var mod = event.metaKey || event.ctrlKey;
    if (!mod) return;
    var key = event.key.toLowerCase();
    var tools = currentTools();
    if (key === "b") {
      event.preventDefault();
      tools.bold();
    } else if (key === "i") {
      event.preventDefault();
      tools.italic();
    } else if (key === "k") {
      event.preventDefault();
      tools.link();
    }
  });

  document.addEventListener("keydown", function (event) {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      var save = form.querySelector('button[value="save"]');
      if (save) save.click();
    }
  });

  // ------------------------------------------------------------ word count

  function countWords(text) {
    var matches = text.match(/[\w'’-]+/g);
    return matches ? matches.length : 0;
  }

  function readableText() {
    return format() === "markdown" ? textarea.value : textarea.value.replace(/<[^>]*>/g, " ");
  }

  function updateCount() {
    if (!wordCount) return;
    var words = countWords(readableText());
    var minutes = Math.max(1, Math.ceil(words / 230));
    var text = words.toLocaleString() + (words === 1 ? " word" : " words") + " · " + minutes + " min read";
    if (maxWords && words > maxWords) {
      text += " · " + (words - maxWords).toLocaleString() + " over the " + maxWords.toLocaleString() + "-word limit";
      wordCount.classList.add("over");
    } else {
      wordCount.classList.remove("over");
    }
    wordCount.textContent = text;
  }

  // ------------------------------------------------------------ keeping the textarea current

  function syncFromVisual() {
    clearTimeout(syncTimer);
    syncTimer = null;
    if (!visual || mode !== "visual") return;
    var text = visual.markdown();
    visualText = text;
    if (text !== textarea.value) {
      textarea.value = text;
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  function scheduleSync() {
    clearTimeout(syncTimer);
    syncTimer = setTimeout(syncFromVisual, 120);
  }

  // ------------------------------------------------------------ opening the visual editor

  function destroyVisual() {
    if (visual) visual.destroy();
    visual = null;
    visualText = null;
  }

  function mountVisual(data) {
    destroyVisual();
    visual = Visual.mount(data, {
      place: visualHost,
      label: "Your piece",
      describedBy: textarea.getAttribute("aria-describedby"),
      placeholder: textarea.getAttribute("placeholder"),
      onChange: scheduleSync,
      onSelection: updateVisualTools,
      onImages: uploadToVisual,
      onMarkdownPaste: pasteMarkdown,
      onNotice: showNotice,
      onLinkKey: visualLink,
      onEscape: function () {
        var buttons = toolbarButtons();
        focusTool(buttons[0]);
      },
    });
    visualText = textarea.value;
  }

  function pasteMarkdown(text) {
    window.Copydesk.post(editor.getAttribute("data-visual-url"), { body: text })
      .then(function (data) {
        if (visual) visual.insertBlocks(data.blocks);
      })
      .catch(function () {
        if (visual) visual.view.dispatch(visual.view.state.tr.insertText(text));
      });
  }

  function openVisual() {
    if (visual && visualText === textarea.value) return Promise.resolve();
    var sent = textarea.value;
    return window.Copydesk.post(editor.getAttribute("data-visual-url"), { body: sent }).then(function (data) {
      if (textarea.value !== sent) return openVisual();
      mountVisual(data);
      if (data.unsupported) {
        showNotice(
          data.unsupported === 1
            ? "One part of this piece uses Markdown the visual editor can't show. It's kept as text, exactly as you wrote it."
            : data.unsupported + " parts of this piece use Markdown the visual editor can't show. They're kept as text, exactly as you wrote them."
        );
      }
    });
  }

  // ------------------------------------------------------------ switching modes

  function formatOf(target) {
    return target === "visual" ? "markdown" : target;
  }

  function setFormat(value) {
    if (!formatField.querySelector('option[value="' + value + '"]')) {
      var option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      formatField.appendChild(option);
    }
    formatField.value = value;
  }

  /* Rewrite the text for another format, asking first when that could lose formatting. */
  function convertTo(target) {
    var source = format();
    if (source === target) return Promise.resolve(true);
    if (conversion && conversion.to === source && conversion.from === target && conversion.result === textarea.value) {
      textarea.value = conversion.original;
      setFormat(target);
      conversion = null;
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      return Promise.resolve(true);
    }
    var original = textarea.value;
    return window.Copydesk.post(editor.getAttribute("data-convert-url"), { body: original, source: source, target: target })
      .then(function (answer) {
        var mayLose = target === "markdown" && (source === "html" || answer.body !== original);
        return (mayLose ? confirmConversion(answer.warnings || []) : Promise.resolve(true)).then(function (confirmed) {
          if (!confirmed) return false;
          conversion = { from: source, to: target, original: original, result: answer.body };
          textarea.value = answer.body;
          setFormat(target);
          textarea.dispatchEvent(new Event("input", { bubbles: true }));
          return true;
        });
      });
  }

  function showMode(target) {
    mode = target;
    editor.querySelectorAll("[data-editor-mode]").forEach(function (button) {
      var name = button.getAttribute("data-editor-mode");
      button.setAttribute("aria-pressed", String(name === target));
      if (name === "markdown_html") button.hidden = format() !== "markdown_html";
    });
    var inVisual = target === "visual";
    textarea.hidden = inVisual || previewing;
    visualHost.hidden = !inVisual || previewing;
    preview.hidden = !previewing;
    toolbar.querySelectorAll("[data-only]").forEach(function (item) {
      item.hidden = item.getAttribute("data-only") !== (inVisual ? "visual" : "source");
    });
    toolbar.querySelectorAll("[data-hide-for]").forEach(function (item) {
      item.hidden = item.getAttribute("data-hide-for") === format() && !inVisual;
    });
    if (!inVisual) {
      clearPressed();
      context.hidden = true;
    } else if (visual) {
      updateVisualTools(visual.describe());
    }
    modeLabel.textContent = MODE_LABELS[target];
    resetToolbarFocus();
    updateCount();
  }

  function rememberMode(target) {
    if (target !== "visual" && target !== "markdown") return;
    try {
      localStorage.setItem(PREFERENCE_KEY, target);
    } catch (e) {
      /* blocked storage only means the choice isn't remembered */
    }
  }

  function preferredMode() {
    try {
      return localStorage.getItem(PREFERENCE_KEY);
    } catch (e) {
      return null;
    }
  }

  function setPreview(value) {
    previewing = value;
    var button = editor.querySelector('[data-editor-tab="preview"]');
    button.setAttribute("aria-pressed", String(value));
    editor.querySelectorAll("[data-md], [data-visual-style]").forEach(function (control) {
      control.disabled = value;
    });
    showMode(mode);
    if (value) renderPreview();
  }

  function switchTo(target, options) {
    var settings = options || {};
    if (busy) return Promise.resolve();
    syncFromVisual();
    if (target === mode && !previewing && (target !== "visual" || visual)) return Promise.resolve();
    busy = true;
    showNotice("");
    if (previewing) setPreview(false);
    return convertTo(formatOf(target))
      .then(function (converted) {
        if (!converted) return false;
        return (target === "visual" ? openVisual() : Promise.resolve()).then(function () {
          showMode(target);
          if (!settings.quiet) {
            rememberMode(target);
            if (target === "visual") visual.focus();
            else textarea.focus();
          }
          return true;
        });
      })
      .catch(function (error) {
        showNotice(error.message + " You can keep writing here.");
        showMode(format() === "markdown" ? "markdown" : format());
      })
      .then(function (result) {
        busy = false;
        return result;
      });
  }

  editor.querySelectorAll("[data-editor-mode]").forEach(function (button) {
    button.addEventListener("click", function () {
      switchTo(button.getAttribute("data-editor-mode"));
    });
  });

  var previewButton = editor.querySelector('[data-editor-tab="preview"]');
  previewButton.addEventListener("click", function () {
    syncFromVisual();
    setPreview(!previewing);
  });

  // ------------------------------------------------------------ preview

  function renderPreview() {
    preview.innerHTML = '<p class="muted">Loading preview…</p>';
    window.Copydesk.post(editor.getAttribute("data-preview-url"), { body: textarea.value, body_format: format() })
      .then(function (data) {
        preview.innerHTML = '<div class="prose">' + (data.html || '<p class="muted">Nothing to preview yet.</p>') + "</div>";
      })
      .catch(function (error) {
        preview.innerHTML = '<p class="error-text">' + escapeHtml(error.message) + "</p>";
      });
  }

  function escapeHtml(text) {
    var div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // ------------------------------------------------------------ image upload

  var fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = "image/jpeg,image/png,image/gif,image/webp";
  fileInput.hidden = true;
  editor.appendChild(fileInput);

  fileInput.addEventListener("change", function () {
    if (fileInput.files.length) {
      if (mode === "visual") uploadToVisual([fileInput.files[0]]);
      else upload(fileInput.files[0]);
    }
    fileInput.value = "";
  });

  function sendImage(file) {
    var body = new FormData();
    body.append("image", file);
    return window.Copydesk.post(editor.getAttribute("data-upload-url"), body);
  }

  function uploadToVisual(files, pos) {
    files.forEach(function (file) {
      var pending = visual.startUpload(file.name, pos);
      sendImage(file)
        .then(function (data) {
          return askImageAlt("").then(function (alt) {
            pending.finish({ src: data.url, alt: alt });
          });
        })
        .catch(function (error) {
          pending.finish(null);
          showNotice(error.message);
        });
    });
  }

  function upload(file) {
    var s = selection();
    var placeholder = "![Uploading " + file.name.replace(/[[\]]/g, "") + "…]()";
    replaceRange(s.start, s.end, placeholder);
    sendImage(file)
      .then(function (data) {
        return askImageAlt("").then(function (alt) {
          var clean = alt.replace(/[[\]]/g, "");
          var isHtml = format() === "html";
          var image = isHtml
            ? '<img src="' + data.url + '" alt="' + clean.replace(/"/g, "&quot;") + '">'
            : "![" + clean + "](" + data.url + ")";
          swapPlaceholder(placeholder, image);
        });
      })
      .catch(function (error) {
        swapPlaceholder(placeholder, "");
        showNotice(error.message);
      });
  }

  function swapPlaceholder(placeholder, replacement) {
    var index = textarea.value.indexOf(placeholder);
    if (index === -1) return;
    replaceRange(index, index + placeholder.length, replacement);
  }

  textarea.addEventListener("paste", function (event) {
    var items = event.clipboardData && event.clipboardData.files;
    if (items && items.length && /^image\//.test(items[0].type)) {
      event.preventDefault();
      upload(items[0]);
    }
  });

  textarea.addEventListener("dragover", function (event) {
    if (event.dataTransfer && Array.prototype.indexOf.call(event.dataTransfer.types, "Files") !== -1) {
      event.preventDefault();
      editor.classList.add("drop-hint");
    }
  });

  textarea.addEventListener("dragleave", function () {
    editor.classList.remove("drop-hint");
  });

  textarea.addEventListener("drop", function (event) {
    editor.classList.remove("drop-hint");
    var files = event.dataTransfer && event.dataTransfer.files;
    if (files && files.length && /^image\//.test(files[0].type)) {
      event.preventDefault();
      upload(files[0]);
    }
  });

  // ------------------------------------------------------------ local backup

  function snapshot() {
    return {
      title: titleInput ? titleInput.value : "",
      subtitle: subtitleInput ? subtitleInput.value : "",
      body: textarea.value,
      body_format: format(),
      savedAt: new Date().toISOString(),
    };
  }

  function readBackup() {
    try {
      return JSON.parse(localStorage.getItem(backupKey) || "null");
    } catch (e) {
      return null;
    }
  }

  function writeBackup() {
    try {
      localStorage.setItem(backupKey, JSON.stringify(snapshot()));
    } catch (e) {
      /* storage full or blocked; nothing else to do */
    }
  }

  function clearBackup() {
    try {
      localStorage.removeItem(backupKey);
    } catch (e) {
      /* ignore */
    }
  }

  function restoreBackup(backup) {
    if (titleInput) titleInput.value = backup.title;
    if (subtitleInput) subtitleInput.value = backup.subtitle;
    textarea.value = backup.body;
    setFormat(backup.body_format || format());
    conversion = null;
    dirty = true;
    destroyVisual();
    return openInitialMode().then(updateCount);
  }

  // A backup from before formats existed is Markdown, like everything else from then.
  function backupDiffers(backup, current) {
    return (
      backup.body !== current.body ||
      backup.title !== current.title ||
      backup.subtitle !== current.subtitle ||
      (backup.body_format || "markdown") !== current.body_format
    );
  }

  function setUpBackup() {
    if (!backupKey) return;
    var backup = readBackup();
    var notice = document.querySelector("[data-restore-notice]");
    if (backup && backupDiffers(backup, snapshot()) && notice) {
      notice.hidden = false;
      var when = notice.querySelector("[data-restore-time]");
      if (when) when.textContent = new Date(backup.savedAt).toLocaleString();
      notice.querySelector("[data-restore]").addEventListener("click", function () {
        notice.hidden = true;
        restoreBackup(backup);
      });
      notice.querySelector("[data-discard]").addEventListener("click", function () {
        clearBackup();
        notice.hidden = true;
      });
    } else if (backup) {
      clearBackup();
    }
  }

  var backupTimer = null;
  form.addEventListener("input", function (event) {
    // These controls change the visual document, which reports back through the textarea.
    if (event.target.closest && event.target.closest("[data-visual-context], [data-editor-toolbar]")) return;
    dirty = true;
    updateCount();
    if (backupKey) {
      clearTimeout(backupTimer);
      backupTimer = setTimeout(writeBackup, 800);
    }
    if (mode !== "visual" && conversion && conversion.result !== textarea.value) conversion = null;
  });

  form.addEventListener("submit", function () {
    syncFromVisual();
    dirty = false;
    clearTimeout(backupTimer);
    if (backupKey) writeBackup();
  });

  window.addEventListener("beforeunload", function (event) {
    syncFromVisual();
    if (dirty) {
      event.preventDefault();
      event.returnValue = "";
    }
  });

  // ------------------------------------------------------------ starting up

  function openInitialMode() {
    if (format() !== "markdown") return switchTo(format(), { quiet: true });
    if (canUseVisual && preferredMode() !== "markdown") return switchTo("visual", { quiet: true });
    showMode("markdown");
    return Promise.resolve();
  }

  // Scripts are running, so buttons replace the plain format list.
  editor.querySelector("[data-editor-format]").hidden = true;
  editor.querySelector("[data-editor-modes]").hidden = false;
  if (canUseVisual) editor.querySelector('[data-editor-mode="visual"]').hidden = false;
  showMode(format() === "markdown" ? "markdown" : format());
  setUpBackup();
  openInitialMode();
})();
