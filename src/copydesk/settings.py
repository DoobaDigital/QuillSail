"""Site settings that editors change in the dashboard.

Each setting is declared once with ``define()``: its default, its label, help
text and type. The settings screen is built from these declarations, so an
extension that calls ``define()`` gets its own fields there for free.

Values live in the ``settings`` table, and each request (or each worker job)
reads them once.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from flask import g, has_app_context
from sqlalchemy import select

from copydesk.db import db
from copydesk.models import Setting
from copydesk.utils import COLOR_RE, is_valid_email, parse_int, parse_lines, utcnow

TABS: list[tuple[str, str]] = [
    ("general", "General"),
    ("appearance", "Appearance"),
    ("accounts", "Accounts"),
    ("writing", "Writing"),
    ("newsletter", "Newsletter"),
    ("email", "Email"),
    ("extensions", "Extensions"),
]

TYPES = ("text", "textarea", "markdown", "code", "bool", "int", "choice", "color", "lines", "email", "url")

Choices = list[tuple[str, str]] | Callable[[], list[tuple[str, str]]]


@dataclass
class SettingDef:
    key: str
    default: Any
    label: str
    type: str = "text"
    help: str = ""
    tab: str = "general"
    choices: Choices | None = None
    placeholder: str = ""
    max_length: int = 0
    required: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def get_choices(self) -> list[tuple[str, str]]:
        if callable(self.choices):
            return self.choices()
        return list(self.choices or [])


REGISTRY: dict[str, SettingDef] = {}
_MISSING = object()


def define(key: str, default: Any, label: str, **kwargs: Any) -> SettingDef:
    definition = SettingDef(key=key, default=default, label=label, **kwargs)
    if definition.type not in TYPES:
        raise ValueError(f"Unknown setting type {definition.type!r} for {key}")
    REGISTRY[key] = definition
    return definition


def _timezones() -> list[tuple[str, str]]:
    import zoneinfo

    zones = sorted(z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/")))
    return [(z, z.replace("_", " ")) for z in zones] or [("UTC", "UTC")]


def _themes() -> list[tuple[str, str]]:
    from copydesk.themes import available_themes

    return [(t.name, t.title) for t in available_themes()]


def _pages() -> list[tuple[str, str]]:
    from copydesk.models import Page

    rows = db.session.scalars(select(Page).order_by(Page.title)).all()
    return [("", "None")] + [(p.slug, p.title) for p in rows]


# --- General -------------------------------------------------------------------------
define("site.name", "My Newsletter", "Publication name", required=True, max_length=80,
       help="Shown at the top of every page and in every email.")
define("site.mode", "newsletter", "Publication type", type="choice",
       choices=[("newsletter", "Newsletter"), ("blog", "Blog"), ("hybrid", "Blog + newsletter")],
       help="Blog puts posts first. Blog + newsletter also offers email subscriptions and newsletter issues. Switching preserves your posts, issues, subscribers and settings.")
define("site.tagline", "", "Tagline", max_length=160,
       help="One short line under the name, e.g. “News and ideas from our members.”")
define("site.description", "", "Description", type="textarea", max_length=500,
       help="A sentence or two about the publication. Used by search engines and link previews.")
define("site.organization", "", "Published by", max_length=120,
       help="The club, department or organization behind the publication.")
define("site.organization_url", "", "Organization website", type="url")
define("site.contact_email", "", "Contact email", type="email",
       help="Shown in the footer so readers can reach the editors.")
define("site.timezone", "America/New_York", "Time zone", type="choice", choices=_timezones,
       help="Dates are shown, and issues are scheduled, in this time zone.")
define("site.footer", "", "Footer text", type="markdown",
       help="Optional. Appears at the bottom of every page.")
define("blog.newsletter_url", "", "External newsletter website", type="url",
       help="Optional. The base URL of another QuillSail newsletter, such as https://acm.cse.sc.edu/newsletter. Public blog posts can be offered there for editorial review. Nothing is submitted automatically.")

# --- Business outreach ---------------------------------------------------------------
define("business.enabled", False, "Accept business outreach", type="bool",
       help="Adds a For businesses form for workforce opportunities, projects, partnerships, and feedback. Contacts confirm their email before staff review requests in Business outreach.")


# --- Appearance ----------------------------------------------------------------------
define("appearance.theme", "default", "Theme", type="choice", choices=_themes, tab="appearance",
       help="Themes change the overall look. More can be installed in the themes folder.")
define("appearance.accent_color", "#6E4CC2", "Accent color", type="color", tab="appearance",
       help="Used for links and buttons. If it's too light or too dark to read, QuillSail adjusts it automatically.")
define("appearance.article_font", "book", "Article typeface", type="choice", tab="appearance",
       choices=[("serif", "Serif (traditional, bookish)"), ("sans", "Sans-serif (clean, modern)")])
define("appearance.logo", "", "Logo", type="text", tab="appearance",
       help="Upload on the Appearance page. Shown instead of the publication name in the header.")
define("appearance.show_subscriber_count", False, "Show the number of subscribers", type="bool",
       tab="appearance", help="Adds “Join 1,234 readers” under the sign-up form once you have 25 or more.")
define("appearance.home_intro", "", "Home page introduction", type="markdown", tab="appearance",
       help="Optional. A short welcome shown on the home page under the sign-up form.")
define("appearance.custom_css", "", "Custom CSS", type="code", tab="appearance",
       help="Advanced. Added after the theme's styles on the website and dashboard. Use .dashboard for dashboard-specific rules.")

# Designer values are stored in the existing settings table. The defaults are
# QuillSail's own style (assets/README.md). Migration 0008 stored the previous
# defaults for installations that had already changed their design.
DESIGN_FONTS = [("inherit", "Follow body type"), ("serif", "Editorial serif"), ("book", "Book serif"),
                ("sans", "Modern sans serif"), ("humanist", "Humanist sans serif"),
                ("slab", "Bookish slab serif"), ("mono", "Monospace"), ("custom", "Custom font stack")]
REGISTRY["appearance.article_font"].choices = DESIGN_FONTS[1:]
REGISTRY["appearance.article_font"].label = "Body typeface"
REGISTRY["appearance.theme"].label = "Installed template theme"
REGISTRY["appearance.logo"].extra["upload"] = True
define("appearance.style", "quillsail", "Starting style", type="choice", tab="appearance",
       choices=[("quillsail", "QuillSail"), ("classic", "Classic"), ("broadsheet", "Broadsheet"),
                ("brief", "Brief"), ("reference", "Reference"), ("canvas", "Canvas")])
define("appearance.dashboard_theme", "own", "Dashboard design", type="choice", tab="dashboard_design",
       choices=[("own", "Its own design"), ("publication", "Match the publication")])
# Installations that changed their look before saving a design keep the built-in styles.
define("appearance.core_styles", False, "Use the original built-in styles", type="bool", tab="internal")
define("onboarding.appearance", "", "Getting started: appearance", type="choice", tab="internal",
       choices=[("", "To do"), ("done", "Done"), ("skipped", "Skipped")])
define("appearance.logo_dark", "", "Logo for dark backgrounds", tab="appearance", extra={"upload": True})
define("appearance.email_logo", "", "Email logo", tab="appearance", extra={"upload": True})
define("appearance.favicon", "", "Publication icon", tab="appearance", extra={"upload": True})
define("appearance.hero_logo", "", "Homepage hero logo", tab="appearance", extra={"upload": True})
define("appearance.hero_logo_dark", "", "Homepage hero logo for dark backgrounds", tab="appearance", extra={"upload": True})
define("appearance.hero_display", "title", "Hero content", type="choice", tab="appearance",
       choices=[("title", "Title text"), ("logo", "Logo"), ("both", "Logo and title text")])
define("appearance.hero_align", "default", "Hero alignment", type="choice", tab="appearance",
       choices=[("default", "Default (centered for newsletters, left for blogs)"), ("left", "Left"),
                ("center", "Centered"), ("right", "Right")],
       help="Lines up the overline, title or logo, and subtitle.")
define("appearance.hero_title", "", "Hero title", tab="appearance", max_length=160,
       help="Homepage only. Leave blank to use the publication name.")
define("appearance.hero_subtitle", "", "Hero subtitle", tab="appearance", max_length=300,
       help="Homepage only. Leave blank to use the publication tagline.")
define("appearance.hero_overline", "", "Hero overline", tab="appearance", max_length=160,
       help="The small line above the title. Leave blank to use Published by from General settings.")
define("appearance.hero_show_subtitle", True, "Show hero subtitle", type="bool", tab="appearance")
define("appearance.hero_show_overline", True, "Show hero overline", type="bool", tab="appearance")
define("appearance.hero_logo_width", 480, "Hero logo width (pixels)", type="int", tab="appearance", extra={"min": 120, "max": 1000})
define("appearance.brand_display", "logo", "Masthead shows", type="choice", tab="appearance",
       choices=[("logo", "Logo, or publication name if no logo is uploaded"), ("both", "Logo and publication name"), ("name", "Publication name")])
define("appearance.heading_font", "amiri", "Heading typeface", type="choice", tab="appearance",
       choices=DESIGN_FONTS[:1] + [("amiri", "Amiri bold display")] + DESIGN_FONTS[1:])
define("appearance.custom_body_font", "", "Custom body font stack", tab="appearance", max_length=200)
define("appearance.custom_heading_font", "", "Custom heading font stack", tab="appearance", max_length=200)
# Dark colors may be blank, which derives them from the light palette.
for _key, _label, _default, _blank in [
    ("background", "Page background", "#ffffff", False), ("surface", "Paper / card background", "#ffffff", False),
    ("text_color", "Body text", "#000000", False), ("muted_color", "Secondary text", "#000000", False),
    ("border_color", "Rules and borders", "#000000", False),
    ("dark_background", "Dark page background", "#000000", True),
    ("dark_surface", "Dark paper / card background", "#000000", True),
    ("dark_text", "Dark body text", "#dbdbdb", True),
]:
    define(f"appearance.{_key}", _default, _label, type="color", tab="appearance", extra={"allow_blank": _blank})
for _key, _label, _default, _minimum, _maximum in [
    ("content_width", "Website width (pixels)", 1152, 720, 1600),
    ("reading_width", "Reading width (pixels)", 640, 420, 1000),
    ("body_size", "Article text size (pixels)", 18, 14, 26),
    ("line_height", "Line height (percent)", 170, 130, 220),
    ("corner_radius", "Corner radius (pixels)", 0, 0, 32),
    ("logo_height", "Website logo height (pixels)", 40, 20, 120),
    ("email_width", "Email width (pixels)", 600, 480, 800),
    ("email_size", "Email text size (pixels)", 16, 14, 24),
    ("email_padding", "Email content padding (pixels)", 32, 12, 56),
]:
    define(f"appearance.{_key}", _default, _label, type="int", tab="appearance", extra={"min": _minimum, "max": _maximum})
define("appearance.masthead", "left", "Masthead alignment", type="choice", tab="appearance", choices=[("left", "Left"), ("center", "Centered")])
define("appearance.density", "comfortable", "Spacing", type="choice", tab="appearance", choices=[("compact", "Compact"), ("comfortable", "Comfortable"), ("spacious", "Spacious")])
define("appearance.issue_layout", "stacked", "Issue layout", type="choice", tab="appearance", choices=[("stacked", "Continuous reading"), ("cards", "Individual story cards"), ("columns", "Two columns on wide screens")])
define("appearance.color_mode", "light", "Default color mode", type="choice", tab="appearance", choices=[("auto", "Follow the reader's device"), ("light", "Light"), ("dark", "Dark")])
define("appearance.email_layout", "classic", "Email presentation", type="choice", tab="appearance", choices=[("classic", "Classic"), ("editorial", "Editorial"), ("digest", "Compact digest"), ("reference", "Reference"), ("cards", "Story cards")])
define("appearance.email_css", "", "Custom email CSS", type="code", tab="appearance", max_length=40000,
       help="Applied to newsletter emails and inlined where supported. Email clients support a smaller set of CSS than browsers.")
REGISTRY["appearance.custom_css"].max_length = 40000

# The dashboard's own design mirrors the publication controls that apply to it.
# It starts in QuillSail's style and shares the publication's uploaded logos.
DASHBOARD_DESIGN_KEYS = [
    "style", "brand_display", "logo_height", "article_font", "heading_font", "custom_body_font",
    "custom_heading_font", "body_size", "line_height", "accent_color", "background", "surface", "text_color",
    "muted_color", "border_color", "color_mode", "dark_background", "dark_surface", "dark_text", "density",
    "corner_radius",
]
for _key in DASHBOARD_DESIGN_KEYS:
    _source = REGISTRY[f"appearance.{_key}"]
    define(f"dashboard.{_key}", _source.default, _source.label, type=_source.type, tab="dashboard_design",
           choices=_source.choices, help=_source.help, max_length=_source.max_length, extra=dict(_source.extra))
REGISTRY["dashboard.brand_display"].label = "Sidebar shows"
REGISTRY["dashboard.logo_height"].label = "Logo height (pixels)"
REGISTRY["dashboard.body_size"].label = "Text size (pixels)"
REGISTRY["dashboard.color_mode"].choices = [("auto", "Follow the device"), ("light", "Light"), ("dark", "Dark")]
define("dashboard.custom_css", "", "Dashboard CSS", type="code", tab="dashboard_design", max_length=40000,
       help="Advanced. Added after the dashboard's design, on dashboard pages only.")

define("hosting.keep_awake", False, "Keep this computer awake while public", type="bool", tab="hosting",
       help="Desktop only. Power settings and battery limits still apply.")

# --- Launch page ---------------------------------------------------------------------
define("launch.heading", "Launching soon", "Launch page heading", tab="launch", max_length=160)
define("launch.message", "We're getting ready. Subscribe to hear when we launch.",
       "Launch page message", type="markdown", tab="launch", max_length=5000)
define("launch.signup", True, "Show the sign-up form", type="bool", tab="launch")
define("launch.date", "", "Expected launch date", tab="launch", max_length=100)


# --- Accounts ------------------------------------------------------------------------
define("accounts.registration", "open", "Who can create an account", type="choice", tab="accounts",
       choices=[("open", "Anyone"), ("domains", "Only people with an email address at the domains below"),
                ("closed", "Nobody (administrators add people)")])
define("accounts.allowed_domains", [], "Allowed email domains", type="lines", tab="accounts",
       placeholder="example.edu", help="One per line. Subdomains are included, so example.edu also allows mail.example.edu.")
define("accounts.ask_audience", True, "Ask new members which groups they belong to", type="bool", tab="accounts",
       help="Shows your reader groups (Students, Staff, Alumni…) on the sign-up form.")
define("accounts.terms_page", "", "Members must agree to", type="choice", choices=_pages, tab="accounts",
       help="Optional. Pick a page, such as a code of conduct, that people must agree to when they sign up.")

# --- Writing -------------------------------------------------------------------------
define("submissions.enabled", True, "Accept submissions", type="bool", tab="writing",
       help="When off, the Write page explains that submissions are closed.")
define("submissions.intro", "Have something to say? We publish writing from our community: "
       "tutorials, opinion, news and stories. Write it here, send it to the editors, "
       "and we'll work with you to get it ready.",
       "Write page introduction", type="markdown", tab="writing")
define("submissions.closed_message", "We're not taking new submissions right now. Check back soon!",
       "Message when submissions are closed", type="textarea", tab="writing")
define("submissions.guidelines_page", "guidelines", "Writing guidelines page", type="choice", choices=_pages,
       tab="writing", help="Linked from the editor so writers can check the rules as they go.")
define("submissions.require_section", False, "Writers must pick a section", type="bool", tab="writing")
define("submissions.max_words", 0, "Word limit", type="int", tab="writing",
       help="0 means no limit. Writers see a warning when they go over.")

# --- Newsletter ----------------------------------------------------------------------
define("newsletter.signup_heading", "Get every issue by email", "Sign-up heading", tab="newsletter", max_length=120)
define("newsletter.signup_text", "Free, and you can unsubscribe in one click.", "Sign-up text",
       type="textarea", tab="newsletter", max_length=300)
define("newsletter.ask_audience", True, "Ask subscribers which groups they belong to", type="bool", tab="newsletter",
       help="Lets you send issues, or parts of issues, to particular groups.")
define("newsletter.reply_to", "", "Reply-to address", type="email", tab="newsletter",
       help="Where replies to the newsletter go. Leave blank to use the contact email.")
define("newsletter.subject_format", "{site} #{number}: {title}", "Default subject line", tab="newsletter",
       help="Used when an issue has no subject of its own. {site}, {number} and {title} are filled in.")
define("newsletter.default_display", "summary", "Articles in emails show", type="choice", tab="newsletter",
       choices=[("summary", "A summary and a link to read more"), ("full", "The full text")])
define("newsletter.welcome_enabled", True, "Send a welcome email", type="bool", tab="newsletter",
       help="Sent once, right after someone confirms their subscription.")
define("newsletter.welcome_subject", "Welcome to {site}", "Welcome email subject", tab="newsletter")
define("newsletter.welcome_body", "Thanks for subscribing! You'll get each new issue in your inbox.\n\n"
       "Want to write for us? Anyone in our community can submit a piece.",
       "Welcome email message", type="markdown", tab="newsletter")
define("newsletter.footer", "", "Email footer", type="markdown", tab="newsletter",
       help="Added to the bottom of every issue, above the unsubscribe link.")
define("newsletter.postal_address", "", "Mailing address", type="textarea", tab="newsletter",
       help="Many email providers and anti-spam laws expect a physical mailing address in newsletters.")
define("newsletter.embed_origins", [], "Websites allowed to embed the sign-up form", type="lines", tab="newsletter",
       placeholder="https://example.edu",
       help="One per line. Lets another site (such as your club's main website) send sign-ups here.")


# --- reading and writing -------------------------------------------------------------


def _cache() -> dict[str, Any]:
    if not has_app_context():
        return {}
    cache = g.get("_settings")
    if cache is None:
        cache = {row.key: row.value for row in db.session.scalars(select(Setting)).all()}
        g._settings = cache
    return cache


def get(key: str, default: Any = _MISSING) -> Any:
    values = _cache()
    if key in values and values[key] is not None:
        return values[key]
    if default is not _MISSING:
        return default
    definition = REGISTRY.get(key)
    return definition.default if definition else None


def set_value(key: str, value: Any) -> None:
    """Stage a change. The caller commits the session."""
    row = db.session.get(Setting, key)
    if row is None:
        db.session.add(Setting(key=key, value=value, updated_at=utcnow()))
    else:
        row.value = value
        row.updated_at = utcnow()
    if has_app_context():
        _cache()[key] = value


def set_values(values: dict[str, Any]) -> None:
    for key, value in values.items():
        set_value(key, value)


def invalidate() -> None:
    if has_app_context():
        g.pop("_settings", None)


def for_tab(tab: str) -> list[SettingDef]:
    return [d for d in REGISTRY.values() if d.tab == tab and d.key != "appearance.logo" and not d.extra.get("upload")]


def parse_form_value(definition: SettingDef, raw: Any) -> tuple[Any, str | None]:
    """Convert a submitted form value. Returns (value, error message or None)."""
    kind = definition.type
    if kind == "bool":
        return raw in ("1", "on", "true", True), None
    text = (raw or "").strip() if isinstance(raw, str) else raw
    if kind == "int":
        number = parse_int(text)
        if number is None or number < 0:
            return definition.default, "Enter a whole number (0 or more)."
        if number < definition.extra.get("min", 0) or number > definition.extra.get("max", float("inf")):
            return definition.default, f"Use a value from {definition.extra['min']} to {definition.extra['max']}."
        return number, None
    if kind == "lines":
        return parse_lines(text), None
    if definition.required and not text:
        return definition.default, "This can't be empty."
    if definition.max_length and len(text) > definition.max_length:
        return text, f"Keep this under {definition.max_length} characters."
    if kind == "email" and text and not is_valid_email(text):
        return text, "Enter a valid email address."
    if kind == "url" and text and not text.startswith(("http://", "https://")):
        return text, "Enter a full web address starting with https://"
    if definition.key == "blog.newsletter_url" and text:
        from copydesk.publication import valid_web_url
        if not valid_web_url(text, base=True):
            return text, "Use the newsletter's base http:// or https:// URL, without credentials, query parameters or a fragment."
    if kind == "color" and not text and definition.extra.get("allow_blank"):
        return "", None
    if kind == "color" and not COLOR_RE.match(text or ""):
        return definition.default, "Use a hex color such as #1F5BD8."
    if kind == "choice":
        valid = {value for value, _ in definition.get_choices()}
        if text not in valid:
            return definition.default, "Pick one of the options."
    return text, None


class SettingsNamespace:
    """``site.name`` in templates means ``settings.get("site.name")``."""

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return get(f"{self._prefix}.{name}")
