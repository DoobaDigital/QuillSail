/*
 * QuillSail: small enhancements shared by every page.
 * Everything here is optional; pages work without JavaScript.
 */
(function () {
  "use strict";

  var root = document.documentElement;
  root.classList.add("js");
  root.classList.remove("no-js");

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  window.Copydesk = window.Copydesk || {};
  window.Copydesk.csrfToken = csrfToken;

  window.Copydesk.post = function (url, body) {
    var headers = { "X-CSRF-Token": csrfToken(), "X-Requested-With": "fetch" };
    var options = { method: "POST", headers: headers, credentials: "same-origin", body: body };
    if (body && !(body instanceof FormData) && typeof body !== "string") {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    return fetch(url, options).then(function (response) {
      return response
        .json()
        .catch(function () {
          return {};
        })
        .then(function (data) {
          if (!response.ok) {
            var error = new Error(data.message || data.error || "Something went wrong (" + response.status + ").");
            error.status = response.status;
            throw error;
          }
          return data;
        });
    });
  };

  // ---------------------------------------------------------------- navigation

  // The publication's Menu button opens the .site-nav around the list it controls.
  // The stylesheet (and custom CSS) shows the links for .site-nav.is-open.
  var siteMenus = [];
  document.querySelectorAll("[data-nav-toggle]").forEach(function (button) {
    var target = document.getElementById(button.getAttribute("aria-controls"));
    var menu = target && (target.closest(".site-nav") || target.parentElement);
    if (!menu) return;
    siteMenus.push({ button: button, menu: menu });
    button.addEventListener("click", function () {
      setSiteMenu(button, menu, button.getAttribute("aria-expanded") !== "true");
    });
  });

  function setSiteMenu(button, menu, open) {
    menu.classList.toggle("is-open", open);
    button.setAttribute("aria-expanded", String(open));
  }

  // On narrow screens the dashboard sidebar is a drawer. The Menu button, the
  // Close button, the dimmed area and Escape all go through setDashNav, so the
  // drawer, aria-expanded and focus always agree.
  var dash = document.querySelector(".dash");
  var dashToggle = document.querySelector("[data-dash-nav-toggle]");
  var dashSidebar = dash && dash.querySelector(".dash-sidebar");

  function dashNavOpen() {
    return !!dash && dash.classList.contains("nav-open");
  }

  function setDashNav(open, returnFocus) {
    if (!dash) return;
    dash.classList.toggle("nav-open", open);
    if (dashToggle) dashToggle.setAttribute("aria-expanded", String(open));
    if (open) {
      var first = dash.querySelector("[data-dash-nav-close]") || dash.querySelector(".dash-sidebar a");
      if (first) first.focus();
    } else if (returnFocus && dashToggle) {
      dashToggle.focus();
    }
  }

  if (dashToggle) {
    dashToggle.addEventListener("click", function () {
      setDashNav(!dashNavOpen(), true);
    });
  }

  document.querySelectorAll("[data-dash-nav-close], .dash-scrim").forEach(function (control) {
    control.addEventListener("click", function () {
      setDashNav(false, true);
    });
  });

  // Tabbing out of the open drawer closes it, so focus never sits behind the dimmed area.
  document.addEventListener("focusin", function (event) {
    if (dashNavOpen() && dashSidebar && !dashSidebar.contains(event.target) && event.target !== dashToggle) {
      setDashNav(false, false);
    }
  });

  // Close open <details> menus on outside click or Escape.
  document.addEventListener("click", function (event) {
    document.querySelectorAll("details.menu[open]").forEach(function (menu) {
      if (!menu.contains(event.target)) menu.removeAttribute("open");
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    document.querySelectorAll("details.menu[open]").forEach(function (menu) {
      menu.removeAttribute("open");
      var summary = menu.querySelector("summary");
      if (summary) summary.focus();
    });
    siteMenus.forEach(function (item) {
      if (item.button.getAttribute("aria-expanded") !== "true") return;
      setSiteMenu(item.button, item.menu, false);
      if (item.menu.contains(document.activeElement)) item.button.focus();
    });
    if (dashNavOpen()) setDashNav(false, true);
  });

  // ---------------------------------------------------------------- light / dark

  var THEME_KEY = "cd-theme";
  var themeLabels = { system: "Theme: default", light: "Theme: light", dark: "Theme: dark" };
  // Design previews and locked pages (desktop setup) ignore the saved choice.
  var fixedTheme = root.hasAttribute("data-design-preview") || root.hasAttribute("data-theme-locked");

  function storedTheme() {
    try {
      var value = localStorage.getItem(THEME_KEY);
      return value === "light" || value === "dark" ? value : "system";
    } catch (e) {
      return "system";
    }
  }

  function applyTheme(value) {
    var effective = fixedTheme || value === "system" ? root.getAttribute("data-default-theme") : value;
    if (effective === "light" || effective === "dark") root.setAttribute("data-theme", effective);
    else root.removeAttribute("data-theme");
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      var label = button.querySelector("[data-theme-label]");
      if (label) label.textContent = themeLabels[value] || themeLabels.system;
      button.setAttribute("data-current", value);
    });
  }

  document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
    if (fixedTheme) return;
    button.hidden = false;
    button.addEventListener("click", function () {
      var order = ["system", "light", "dark"];
      var next = order[(order.indexOf(storedTheme()) + 1) % order.length];
      try {
        if (next === "system") localStorage.removeItem(THEME_KEY);
        else localStorage.setItem(THEME_KEY, next);
      } catch (e) {
        /* storage may be blocked; the change still applies to this page */
      }
      applyTheme(next);
    });
  });
  applyTheme(storedTheme());

  // ---------------------------------------------------------------- forms

  // <form data-confirm="Are you sure?"> or <button data-confirm="...">
  document.addEventListener("submit", function (event) {
    var form = event.target;
    var submitter = event.submitter;
    var message = (submitter && submitter.getAttribute("data-confirm")) || form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
      return;
    }
    form.setAttribute("data-submitting", "true");
  });

  document.querySelectorAll("select[data-autosubmit]").forEach(function (select) {
    select.addEventListener("change", function () {
      if (select.form) select.form.requestSubmit ? select.form.requestSubmit() : select.form.submit();
    });
  });

  // Show or hide parts of a form: data-show-if="field-name:value1,value2"
  var conditionals = document.querySelectorAll("[data-show-if]");

  function currentValues(form, name) {
    var values = [];
    form.querySelectorAll('[name="' + name + '"]').forEach(function (input) {
      if ((input.type === "radio" || input.type === "checkbox") && !input.checked) return;
      values.push(input.type === "checkbox" && input.value === "on" ? "on" : input.value);
    });
    return values;
  }

  function updateConditionals() {
    conditionals.forEach(function (el) {
      var spec = el.getAttribute("data-show-if").split(":");
      var form = el.closest("form") || document;
      var wanted = (spec[1] || "").split(",");
      var have = currentValues(form, spec[0]);
      var show = have.some(function (value) {
        return wanted.indexOf(value) !== -1;
      });
      el.hidden = !show;
    });
  }

  if (conditionals.length) {
    document.addEventListener("change", updateConditionals);
    updateConditionals();
  }

  // Warn before leaving a form with unsaved edits: <form data-warn-unsaved>
  document.querySelectorAll("form[data-warn-unsaved]").forEach(function (form) {
    var dirty = false;
    form.addEventListener("input", function () {
      dirty = true;
    });
    form.addEventListener("submit", function () {
      dirty = false;
    });
    window.addEventListener("beforeunload", function (event) {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  });

  // Copy to clipboard: <button data-copy="#element-id">
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.hidden = false;
    button.addEventListener("click", function () {
      var source = document.querySelector(button.getAttribute("data-copy"));
      if (!source) return;
      var text = "value" in source ? source.value : source.textContent;
      var original = button.textContent;
      navigator.clipboard.writeText(text).then(
        function () {
          button.textContent = "Copied";
          setTimeout(function () {
            button.textContent = original;
          }, 2000);
        },
        function () {
          if (source.select) source.select();
        }
      );
    });
  });

  // Repeating rows (custom profile fields on groups): <div data-repeater> with
  // a <template data-repeater-template> and buttons [data-repeater-add] / [data-repeater-remove].
  document.querySelectorAll("[data-repeater]").forEach(function (repeater) {
    var template = repeater.querySelector("template[data-repeater-template]");
    var list = repeater.querySelector("[data-repeater-list]");
    var add = repeater.querySelector("[data-repeater-add]");
    if (!template || !list || !add) return;
    function revealRemoveButtons() {
      repeater.querySelectorAll("[data-repeater-remove]").forEach(function (button) {
        button.hidden = false;
      });
    }
    add.hidden = false;
    revealRemoveButtons();
    add.addEventListener("click", function () {
      var index = list.children.length + Date.now();
      var html = template.innerHTML.replace(/__INDEX__/g, String(index));
      list.insertAdjacentHTML("beforeend", html);
      revealRemoveButtons();
      var input = list.lastElementChild && list.lastElementChild.querySelector("input");
      if (input) input.focus();
    });
    repeater.addEventListener("click", function (event) {
      var remove = event.target.closest("[data-repeater-remove]");
      if (remove) {
        var row = remove.closest("[data-repeater-row]");
        if (row) row.remove();
      }
    });
  });

  // Live preview of a color picker's hex value: <input type=color data-mirror="#id">
  document.querySelectorAll("input[type=color][data-mirror]").forEach(function (picker) {
    var mirror = document.querySelector(picker.getAttribute("data-mirror"));
    if (!mirror) return;
    picker.addEventListener("input", function () {
      mirror.value = picker.value;
    });
    mirror.addEventListener("input", function () {
      if (/^#[0-9a-fA-F]{6}$/.test(mirror.value)) picker.value = mirror.value;
    });
  });
})();
