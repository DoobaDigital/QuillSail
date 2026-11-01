(function () {
  "use strict";
  var form = document.querySelector("[data-design-form]");
  if (!form) return;
  var frame = document.getElementById("design-preview"), preview = form.querySelector("[data-update-preview]");
  var notice = form.querySelector("[data-design-notice]"), dirty = false, timer;
  var presets = JSON.parse(document.getElementById("design-presets").textContent);
  var mobile = false, stage = form.querySelector(".design-preview-stage");
  // The publication and dashboard designers share this script; the dashboard
  // one has no homepage, email or preview-type controls.
  var kind = form.querySelector("[data-preview-kind]"), homeButton = form.querySelector("[data-preview-home]");
  function resizePreview() {
    var email = form.querySelector("[data-preview-format]").value === "email";
    var width = mobile ? 375 : (email ? Number(form.elements.namedItem("appearance.email_width").value) + 48 : 1100);
    var available = stage.clientWidth - 16;
    var scale = Math.min(1, available / width);
    frame.style.width = width + "px"; frame.style.maxWidth = "none";
    frame.style.zoom = String(scale); frame.style.height = (Math.max(550, window.innerHeight - 210) / scale) + "px";
  }
  new ResizeObserver(resizePreview).observe(stage);
  function update() { resizePreview(); if (form.checkValidity()) form.requestSubmit(preview); }
  function changed() { dirty = true; notice.textContent = "Unsaved design. Preview it, then save when you're ready."; }
  function homepagePreview() {
    if (!kind) return;
    form.querySelector("[data-preview-format]").value = "home";
    kind.value = "home";
  }
  if (homeButton) homeButton.addEventListener("click", homepagePreview);
  form.addEventListener("input", function (event) {
    changed();
    if (/^(appearance\.hero_|hero_|remove_hero_)/.test(event.target.name || "")) homepagePreview();
    if (event.target.name === "appearance.dashboard_theme") update();
    if (event.target.matches("[data-color-for]")) form.elements.namedItem(event.target.dataset.colorFor).value = event.target.value;
    clearTimeout(timer);
    if (!event.target.matches("[type=file], [type=radio]")) timer = setTimeout(update, 900);
  });
  if (window.location.hash === "#design-hero" && document.getElementById("design-hero")) {
    document.getElementById("design-hero").open = true;
    homepagePreview(); update();
  }
  form.addEventListener("change", function (event) { if (event.target.type === "file" && event.target.name !== "design_file") update(); });
  form.querySelector("[data-load-preset]").addEventListener("click", function (event) {
    var checked = form.querySelector('[name="preset"]:checked');
    if (!checked) return;
    event.preventDefault();
    Object.keys(presets[checked.value]).forEach(function (key) {
      var input = form.elements.namedItem(key); if (!input) return;
      input.value = presets[checked.value][key];
      var picker = Array.from(form.querySelectorAll("[data-color-for]")).find(function (p) { return p.dataset.colorFor === key; });
      if (picker && input.value) picker.value = input.value;
    });
    changed(); update();
  });
  if (kind) kind.addEventListener("change", function (event) { form.querySelector("[data-preview-format]").value = event.target.value; update(); });
  form.querySelectorAll("[data-preview-size]").forEach(function (button) {
    button.addEventListener("click", function () {
      mobile = button.dataset.previewSize === "mobile"; resizePreview();
      form.querySelectorAll("[data-preview-size]").forEach(function (b) { b.setAttribute("aria-pressed", String(b === button)); });
    });
  });
  form.addEventListener("submit", function (event) { if (event.submitter !== preview && event.submitter && event.submitter.value === "save") dirty = false; });
  window.addEventListener("beforeunload", function (event) { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
})();
