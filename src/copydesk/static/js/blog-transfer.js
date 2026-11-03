/* A public article handoff is form data, never sign-in authority or HTML. */
(() => {
  "use strict";
  const receiver = document.querySelector("[data-blog-transfer]");
  if (!receiver) return;
  const status = receiver.querySelector("[data-transfer-status]");
  const source = new URLSearchParams(location.search).get("source");
  const key = "quillsail-blog-transfer";
  const maxAge = 30 * 60 * 1000;
  let transfer;
  try {
    if (location.hash.startsWith("#quillsail=")) {
      const encoded = location.hash.slice(11);
      // Bound decoding before allocating memory, including multibyte Markdown.
      if (encoded.length > 1100000) throw new Error("too large");
      const binary = atob(encoded.replace(/-/g, "+").replace(/_/g, "/"));
      transfer = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(
        Uint8Array.from(binary, char => char.charCodeAt(0))
      ));
      if (transfer.version !== 1 || transfer.source !== source ||
          typeof transfer.body !== "string" || Array.from(transfer.body).length > 200000) {
        throw new Error("invalid transfer");
      }
      transfer.savedAt = Date.now();
      transfer.path = location.pathname;
      // Keep just one bounded transfer, scoped to this tab and destination.
      try { sessionStorage.setItem(key, JSON.stringify(transfer)); } catch (_) {
        if (receiver.dataset.transferFill !== "true") throw new Error("storage unavailable");
      }
    } else if (receiver.dataset.transferFill === "true") {
      transfer = JSON.parse(sessionStorage.getItem(key) || "null");
    }
    if (transfer && (transfer.path !== location.pathname || transfer.source !== source ||
        Date.now() - transfer.savedAt > maxAge || transfer.savedAt > Date.now())) {
      transfer = null;
      sessionStorage.removeItem(key);
    }
    if (transfer && receiver.dataset.transferFill === "true") {
      if (transfer.body_format === "html" || transfer.body_format === "markdown_html") {
        receiver.querySelector('[name="body_format"]').value = transfer.body_format;
      }
      receiver.querySelector('[name="body"]').value = transfer.body;
      status.textContent = "The full article was transferred. Review it and add a newsletter blurb before submitting.";
      try { sessionStorage.removeItem(key); } catch (_) {}
    } else if (transfer) {
      status.textContent = "Your article is ready. Sign in to review it and write a newsletter blurb. Keep this tab open.";
    }
  } catch (_) {
    status.textContent = "The article could not be transferred. You can paste it into the submission form instead.";
    try { sessionStorage.removeItem(key); } catch (_) {}
  } finally {
    // Do not leave the article in the address bar or browser history.
    if (location.hash.startsWith("#quillsail=")) {
      history.replaceState(null, "", location.pathname + location.search);
    }
  }
})();
