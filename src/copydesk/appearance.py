"""Publication design tokens, portable presets and offline email styling.

Preview overrides live only in Flask's request-local settings cache. They never
change the app's template loader, settings rows, uploads or email queue.
"""

from __future__ import annotations

import hashlib
import json
import re
from html import escape

from flask import g, url_for
from markupsafe import Markup
from sqlalchemy import select

from copydesk import publication, settings
from copydesk.colors import accent_tokens, ensure_contrast, mix

FONTS = {
    "serif": "Iowan Old Style,Charter,Palatino,Georgia,serif",
    "book": "Iowan Old Style,Charter,Sitka Text,Palatino Linotype,Georgia,serif",
    "amiri": "Amiri,Georgia,serif",
    "sans": "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif",
    "humanist": "Optima,Candara,Calibri,Trebuchet MS,sans-serif",
    "slab": "Rockwell,Roboto Slab,Georgia,serif",
    "mono": "SFMono-Regular,Consolas,Liberation Mono,monospace",
}
UPLOADS = {"logo": "Publication logo", "logo_dark": "Logo for dark backgrounds",
           "email_logo": "Email logo", "favicon": "Publication icon",
           "hero_logo": "Homepage hero logo", "hero_logo_dark": "Homepage hero logo for dark backgrounds"}
# The defaults before QuillSail's own style became the default look. The other
# starting styles build on these, so they look the same as they always have.
CLASSIC = {
    "appearance.accent_color": "#1F5BD8", "appearance.article_font": "serif", "appearance.heading_font": "inherit",
    "appearance.text_color": "#16181d", "appearance.muted_color": "#525866", "appearance.border_color": "#e1e4e9",
    "appearance.dark_background": "", "appearance.dark_surface": "", "appearance.dark_text": "",
    "appearance.corner_radius": 10, "appearance.color_mode": "auto",
}
PRESETS = {
    "quillsail": {"title": "QuillSail", "description": "Ink on paper, hairline rules and one purple accent.", "values": {
        "accent_color": "#6E4CC2", "background": "#ffffff", "surface": "#ffffff", "text_color": "#000000",
        "muted_color": "#000000", "border_color": "#000000", "dark_background": "#000000",
        "dark_surface": "#000000", "dark_text": "#dbdbdb", "article_font": "book", "heading_font": "amiri",
        "corner_radius": 0, "color_mode": "light"}},
    "classic": {"title": "Classic", "description": "A familiar publication with generous reading space.", "values": {}},
    "broadsheet": {"title": "Broadsheet", "description": "Ink, warm paper, serif headlines and strong editorial rules.", "values": {
        "accent_color": "#222222", "background": "#faf8f2", "surface": "#faf8f2", "text_color": "#20201e",
        "muted_color": "#62605a", "border_color": "#bdb9ae", "heading_font": "serif", "masthead": "center",
        "corner_radius": 0, "content_width": 1280, "reading_width": 760, "body_size": 19,
        "issue_layout": "columns", "email_layout": "editorial", "email_width": 680}},
    "brief": {"title": "Brief", "description": "A compact, fast-scanning digest with bold sans serif type.", "values": {
        "accent_color": "#3659c9", "article_font": "sans", "heading_font": "sans", "density": "compact",
        "body_size": 17, "line_height": 160, "reading_width": 700, "corner_radius": 4,
        "email_layout": "digest", "email_padding": 24}},
    "reference": {"title": "Reference", "description": "An orderly knowledge journal with restrained links and fine rules.", "values": {
        "accent_color": "#3366cc", "background": "#f8f9fa", "surface": "#ffffff", "text_color": "#202122",
        "muted_color": "#54595d", "border_color": "#a2a9b1", "article_font": "sans", "heading_font": "serif",
        "corner_radius": 0, "content_width": 1280, "reading_width": 880, "body_size": 17,
        "email_layout": "reference", "email_width": 680}},
    "canvas": {"title": "Canvas", "description": "Colorful cards, expressive headings and room for your own identity.", "values": {
        "accent_color": "#7440aa", "background": "#f4f0fa", "surface": "#ffffff", "text_color": "#292035",
        "muted_color": "#62546e", "border_color": "#ddd2e8", "article_font": "humanist", "heading_font": "slab",
        "corner_radius": 22, "density": "spacious", "issue_layout": "cards", "email_layout": "cards",
        "email_padding": 28}},
}

# Loading a preset resets visual controls, while retaining logos, custom code,
# homepage copy and installed template choice. Nothing is saved by loading it.
VISUAL_KEYS = [d.key for d in settings.for_tab("appearance") if not d.key.startswith("appearance.hero_") and d.key not in {
    "appearance.theme", "appearance.custom_css", "appearance.email_css", "appearance.home_intro",
    "appearance.show_subscriber_count", "appearance.brand_display", "appearance.logo_height",
    "appearance.custom_body_font", "appearance.custom_heading_font",
}]


DASHBOARD_SOURCES = {
    "own": ("Its own design", "Starts in QuillSail's style. Choose a starting style and shape it below."),
    "publication": ("Match the publication", "Uses your publication's colors, typography, spacing and installed theme."),
}
# Design files: settings tab, file format and the prefix of the keys they hold.
DESIGN_FILES = {"appearance": ("quillsail.appearance.v1", "appearance", "publication"),
                "dashboard_design": ("quillsail.dashboard.v1", "dashboard", "dashboard")}


def preset_values(name: str) -> dict:
    values = {key: CLASSIC.get(key, settings.REGISTRY[key].default) for key in VISUAL_KEYS}
    values.update({f"appearance.{key}": value for key, value in PRESETS[name]["values"].items()})
    values["appearance.style"] = name
    return values


def dashboard_preset_values(name: str) -> dict:
    """A starting style for the dashboard's own design. The sidebar logo choices stay."""
    keep = {"brand_display", "logo_height", "custom_body_font", "custom_heading_font"}
    return {f"dashboard.{key.removeprefix('appearance.')}": value for key, value in preset_values(name).items()
            if key.removeprefix("appearance.") in settings.DASHBOARD_DESIGN_KEYS
            and key.removeprefix("appearance.") not in keep}


def dashboard_values() -> dict:
    """The dashboard's own design, as the appearance keys design() reads."""
    values = {f"appearance.{key}": settings.get(f"dashboard.{key}") for key in settings.DASHBOARD_DESIGN_KEYS}
    for key in ("content_width", "reading_width"):
        values[f"appearance.{key}"] = settings.REGISTRY[f"appearance.{key}"].default
    return values


def validate(values: dict, prefix: str = "appearance") -> dict[str, str]:
    errors = {}
    for key in (f"{prefix}.custom_body_font", f"{prefix}.custom_heading_font"):
        value = values.get(key, "")
        if value and not re.fullmatch(r"[\w\s,'\".\-]+", value, flags=re.UNICODE):
            errors[key] = "Use font names separated by commas, without CSS declarations or URLs."
    for role in ("body", "heading"):
        key = f"{prefix}.article_font" if role == "body" else f"{prefix}.heading_font"
        if values.get(key) == "custom" and not values.get(f"{prefix}.custom_{role}_font", "").strip():
            errors[f"{prefix}.custom_{role}_font"] = "Enter a font stack, or choose one of the built-in typefaces."
    return errors


def export_design(tab: str = "appearance") -> str:
    return json.dumps({"format": DESIGN_FILES[tab][0], "settings": {
        d.key: settings.get(d.key) for d in settings.for_tab(tab)
    }}, indent=2) + "\n"


def import_design(data: bytes, tab: str = "appearance") -> dict:
    file_format, prefix, kind = DESIGN_FILES[tab]
    if len(data) > 100_000:
        raise ValueError("Design files must be smaller than 100 KB.")
    try:
        document = json.loads(data)
        if document.get("format") != file_format or not isinstance(document.get("settings"), dict):
            raise ValueError
        allowed = {d.key: d for d in settings.for_tab(tab)}
        values = {}
        for key, raw in document["settings"].items():
            if key not in allowed or not isinstance(raw, (str, int, bool)):
                raise ValueError
            value, error = settings.parse_form_value(allowed[key], str(raw) if not isinstance(raw, bool) else raw)
            if error:
                raise ValueError(error)
            values[key] = value
        combined = {key: settings.get(key) for key in allowed} | values
        if validate(combined, prefix):
            raise ValueError("Check the custom font stacks in this design.")
        return values
    except (UnicodeError, TypeError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Choose a QuillSail {kind} design JSON file.") from exc


def override(values: dict, images: dict | None = None) -> None:
    settings._cache().update(values)
    g.appearance_images = images or {}
    g.appearance_preview = True
    g.preview_theme = settings.get("appearance.theme")


def image_url(role: str = "logo", *, external: bool = False) -> str:
    from copydesk.helpers import external_url

    previews = g.get("appearance_images", {})
    if role in previews:
        return previews[role]
    path = settings.get(f"appearance.{role}")
    if not path:
        return ""
    return external_url("public.upload", path=path) if external else url_for("public.upload", path=path)


def css_version() -> str:
    return hashlib.sha256(settings.get("appearance.custom_css").encode()).hexdigest()[:12]


def home_hero() -> dict:
    """Homepage branding is independent of navigation and email branding."""
    custom_logo = image_url("hero_logo")
    logo = custom_logo or image_url("logo")
    dark = image_url("hero_logo_dark") or (image_url("logo_dark") if not custom_logo else "")
    display = settings.get("appearance.hero_display")
    align = settings.get("appearance.hero_align")
    if align not in {"left", "center", "right"}:
        align = "left" if publication.is_blog() else "center"
    return {
        "title": settings.get("appearance.hero_title") or settings.get("site.name"),
        "subtitle": settings.get("appearance.hero_subtitle") or settings.get("site.tagline"),
        "overline": settings.get("appearance.hero_overline") or settings.get("site.organization"),
        "show_subtitle": settings.get("appearance.hero_show_subtitle"),
        "show_overline": settings.get("appearance.hero_show_overline"),
        "logo": logo, "logo_dark": dark, "show_logo": display in {"logo", "both"} and bool(logo),
        "show_title": display != "logo" or not logo, "align": align,
    }


def email_brand() -> dict:
    """Explicit image dimensions keep wide logos within narrow email tables."""
    from copydesk.db import db
    from copydesk.models import Upload

    role = "email_logo" if image_url("email_logo") else "logo"
    src = image_url(role, external=True)
    sizes = g.setdefault("appearance_sizes", {})
    if role not in sizes:
        upload = db.session.scalar(select(Upload).where(Upload.path == settings.get(f"appearance.{role}"))) if src else None
        sizes[role] = (upload.width, upload.height) if upload else (240, 40)
    width, height = sizes[role]
    ratio = min(240 / max(1, width), 40 / max(1, height))
    return {"src": src, "width": max(1, round(width * ratio)), "height": max(1, round(height * ratio))}


def design(values: dict | None = None) -> dict:
    values = values or {}
    d = {key.removeprefix("appearance."): values.get(key, settings.get(key))
         for key in settings.REGISTRY if key.startswith("appearance.")}
    d["enabled"] = not d["core_styles"] or g.get("appearance_preview", False)
    d["body_font"] = FONTS.get(d["article_font"], d["custom_body_font"] or FONTS["sans"])
    d["heading_stack"] = d["body_font"] if d["heading_font"] == "inherit" else FONTS.get(
        d["heading_font"], d["custom_heading_font"] or FONTS["serif"])
    d["line_spacing"] = d["line_height"] / 100
    d["space"] = {"compact": 20, "comfortable": 32, "spacious": 44}.get(d["density"], 32)
    d["dark_background"] = d["dark_background"] or "#121419"
    d["dark_surface"] = d["dark_surface"] or "#181b21"
    d["dark_text"] = d["dark_text"] or "#e8eaee"
    if d["style"] == "quillsail":
        # Ink on paper: secondary text stays full ink, and dark mode softens white
        # to 40% for rules and 14% for hover fills.
        d["dark_muted"] = d["dark_text"]
        d["dark_border"] = mix(d["dark_background"], "#ffffff", 0.4)
        d["dark_fill"] = mix(d["dark_surface"], "#ffffff", 0.14)
    else:
        d["dark_muted"] = mix(d["dark_background"], d["dark_text"], 0.7)
        d["dark_border"] = mix(d["dark_background"], d["dark_text"], 0.2)
        d["dark_fill"] = mix(d["dark_surface"], d["dark_text"], .05)
    d["link"] = ensure_contrast(d["accent_color"], d["surface"], 4.5)
    d["dark_link"] = ensure_contrast(d["accent_color"], d["dark_surface"], 4.5)
    # Primary actions keep white text on the accent in both color modes.
    d["action"] = ensure_contrast(d["accent_color"], "#ffffff", 4.5)
    return d


def dashboard_design(publication_design: dict | None = None) -> dict:
    """The dashboard's own design, or the publication's when it matches.

    Its own design still shows the publication's uploaded logos, so the
    dashboard always shows whose publication it is.
    """
    d = publication_design or design()
    if d["dashboard_theme"] == "publication":
        return d
    own = design(dashboard_values())
    own["enabled"] = True
    own["dashboard_css"] = settings.get("dashboard.custom_css")
    return own


def web_tokens(d: dict, *, dashboard: bool = False) -> Markup:
    if not d["enabled"]:
        return Markup("")
    # Values only come from typed settings; font strings cannot contain CSS/HTML.
    safe_font = lambda value: escape(value, quote=False).replace("<", "").replace(">", "")  # noqa: E731
    common = {
        "font-article": safe_font(d["body_font"]), "font-display": safe_font(d["heading_stack"]),
        "design-size": f"{d['body_size']}px", "design-leading": d["line_spacing"],
        "container": f"{d['content_width']}px", "measure": f"{d['reading_width']}px",
        "radius": f"{d['corner_radius']}px", "design-space": f"{d['space']}px", "logo-height": f"{d['logo_height']}px",
        "hero-logo-width": f"{d['hero_logo_width']}px",
    }
    light = {"bg": d["background"], "surface": d["surface"], "surface-2": mix(d["surface"], d["text_color"], .04),
             "text": d["text_color"], "muted": d["muted_color"], "border": d["border_color"],
             "accent": d["link"], "accent-hover": d["link"], "accent-soft": mix(d["surface"], d["link"], .08),
             "on-accent": ensure_contrast("#ffffff", d["link"], 4.5)}
    dark = {"bg": d["dark_background"], "surface": d["dark_surface"], "surface-2": d["dark_fill"],
            "text": d["dark_text"], "muted": d["dark_muted"], "border": d["dark_border"],
            "accent": d["dark_link"], "accent-hover": d["dark_link"], "accent-soft": mix(d["dark_surface"], d["dark_link"], .12),
            "on-accent": ensure_contrast("#16181d", d["dark_link"], 4.5)}
    # Styles that keep the accent for actions only (QuillSail) use these.
    light.update({"action": d["action"], "on-action": "#ffffff", "action-hover": light["text"],
                  "on-action-hover": light["bg"], "disabled-opacity": ".4"})
    dark.update({"action": d["action"], "on-action": "#ffffff", "action-hover": dark["surface-2"],
                 "on-action-hover": dark["text"], "disabled-opacity": ".3"})
    for palette in (light, dark):
        if dashboard:
            # A host may choose very different page and panel backgrounds.
            for key in ("text", "muted"):
                palette["panel-" + key] = ensure_contrast(palette[key], palette["surface"])
                palette[key] = ensure_contrast(palette[key], palette["bg"])
            palette["on-accent-soft"] = ensure_contrast(palette["accent"], palette["accent-soft"])
        palette.update({"text-muted": palette["muted"], "text-subtle": palette["muted"],
                        "bg-subtle": palette["surface-2"], "bg-muted": palette["surface-2"],
                        "surface-raised": palette["surface"], "border-strong": palette["border"]})
    declarations = lambda values: ";".join(f"--{k}:{v}" for k, v in values.items())  # noqa: E731
    selector = ".dashboard" if dashboard else ".publication"
    return Markup(selector + "{" + declarations(common | light) + "}"
                  "@media(prefers-color-scheme:dark){:root:not([data-theme=light]) " + selector + "{" + declarations(dark) + "}}"
                  ":root[data-theme=dark] " + selector + "{" + declarations(dark) + "}")


def inline_email_css(html: str) -> str:
    css = settings.get("appearance.email_css")
    if not css.strip():
        return html
    import cssutils
    from lxml import html as lxml_html
    from premailer import Premailer

    # cssutils otherwise resolves @import while parsing, independently of
    # Premailer's network switch. Disable its fetcher and discard import rules.
    parser = cssutils.CSSParser(fetcher=lambda url: (None, b""), loglevel=50)
    sheet = parser.parseString(css)
    for rule in list(sheet.cssRules):
        if rule.type in (rule.IMPORT_RULE, rule.CHARSET_RULE):
            sheet.deleteRule(rule)
    safe_css = sheet.cssText.decode("utf-8").replace("<", "\\3c ")
    # Premailer always gives an existing style attribute precedence, even over
    # !important. Move the generated base styles into a stylesheet first, so
    # an administrator's overrides participate in the normal CSS cascade.
    document = lxml_html.document_fromstring(html)
    base_rules = []
    for index, element in enumerate(document.xpath("//*[@style]")):
        name = f"qs-inline-{index}"
        base_rules.append(f".{name}{{{element.attrib.pop('style')}}}")
        element.attrib["class"] = (element.attrib.get("class", "") + " " + name).strip()
    return Premailer(lxml_html.tostring(document, encoding="unicode"), css_text="\n".join(base_rules) + "\n" + safe_css,
                     allow_network=False, allow_loading_external_files=False, include_star_selectors=True,
                     disable_link_rewrites=True, disable_validation=True, keep_style_tags=False,
                     strip_important=False).transform()


def email_design(d: dict) -> dict:
    from copydesk.notify import EMAIL_STYLE

    e = dict(EMAIL_STYLE)
    enabled = d["enabled"]
    e.update(width=d["email_width"] if enabled else 600, padding=d["email_padding"] if enabled else 32,
             size=d["email_size"] if enabled else 16, leading=d["line_spacing"] if enabled else 1.65,
             background=d["background"] if enabled else "#f3f4f6", surface=d["surface"] if enabled else "#ffffff",
             text=d["text_color"] if enabled else "#16181d", muted=d["muted_color"] if enabled else "#6b7280",
             border=d["border_color"] if enabled else "#e5e7eb", radius=d["corner_radius"] if enabled else 12,
             font=d["body_font"] if enabled else EMAIL_STYLE["font"],
             heading_font=d["heading_stack"] if enabled else EMAIL_STYLE["font"],
             layout=d["email_layout"] if enabled else "classic", align=d["masthead"] if enabled else "left",
             link=d["link"] if enabled else accent_tokens(d["accent_color"])["accent"])
    e["soft"] = mix(e["surface"], e["text"], .04)
    for key, size in (("h1", 32 if e["layout"] == "editorial" else 28), ("h2", 23 if e["layout"] == "editorial" else 21)):
        e[key] = f"margin:0 0 12px;font-family:{e['heading_font']};font-size:{size}px;line-height:1.25;color:{e['text']};font-weight:700;"
    e["p"] = f"margin:0 0 16px;font-family:{e['font']};font-size:{e['size']}px;line-height:{e['leading']};color:{e['text']};"
    e["small"] = f"margin:0 0 12px;font-family:{e['font']};font-size:13px;line-height:1.5;color:{e['muted']};"
    e["label"] = f"margin:0 0 8px;font-family:{e['font']};font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:{e['muted']};"
    e["story"] = f"margin:24px 0 0;padding:24px 0 0;border-top:1px solid {e['border']};"
    if e["layout"] == "digest":
        e["story"] = f"margin:18px 0 0;padding:0 0 0 14px;border-left:3px solid {e['link']};"
    elif e["layout"] == "cards":
        e["story"] = f"margin:20px 0 0;padding:20px;background:{e['soft']};border:1px solid {e['border']};border-radius:{e['radius']}px;"
    elif e["layout"] == "reference":
        e["story"] = f"margin:24px 0 0;padding:12px 0 0;border-top:1px solid {e['border']};"
    return e
