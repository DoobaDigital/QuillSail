"""Keep the accent color readable.

Editors can pick any accent color. Before using it, QuillSail darkens it (for
light backgrounds) or lightens it (for dark mode) just enough to meet WCAG AA
contrast for normal text (4.5:1), so a pale yellow never ends up as unreadable
link text.
"""

from __future__ import annotations

from functools import lru_cache

from copydesk.utils import COLOR_RE

LIGHT_BACKGROUND = "#ffffff"
DARK_BACKGROUND = "#1e2129"
DEFAULT_ACCENT = "#6E4CC2"


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(c))) for c in rgb))


def _channel(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    r, g, b = hex_to_rgb(color)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def mix(a: str, b: str, amount: float) -> str:
    """Blend ``amount`` (0-1) of color ``b`` into color ``a``."""
    ra, ga, ba = hex_to_rgb(a)
    rb, gb, bb = hex_to_rgb(b)
    return rgb_to_hex((ra + (rb - ra) * amount, ga + (gb - ga) * amount, ba + (bb - ba) * amount))


def ensure_contrast(color: str, background: str, minimum: float = 4.5) -> str:
    """Nudge ``color`` toward black or white until it reaches ``minimum`` contrast."""
    if contrast(color, background) >= minimum:
        return color
    target = "#000000" if luminance(background) > 0.5 else "#ffffff"
    for step in range(1, 101):
        candidate = mix(color, target, step / 100)
        if contrast(candidate, background) >= minimum:
            return candidate
    return target


@lru_cache(maxsize=32)
def accent_tokens(accent: str | None) -> dict[str, str]:
    """CSS custom-property values derived from one accent color."""
    if not accent or not COLOR_RE.match(accent):
        accent = DEFAULT_ACCENT
    accent = accent.lower()
    light = ensure_contrast(accent, LIGHT_BACKGROUND)
    # White text sits on the light-mode accent, so it needs the same contrast with white.
    light = ensure_contrast(light, "#ffffff")
    dark = ensure_contrast(accent, DARK_BACKGROUND)
    on_dark = "#0b0c0f" if contrast(dark, "#0b0c0f") >= 4.5 else "#ffffff"
    return {
        "accent": light,
        "accent_hover": mix(light, "#000000", 0.15),
        "accent_soft": mix(light, "#ffffff", 0.9),
        "on_accent": "#ffffff",
        "accent_dark": dark,
        "accent_dark_hover": mix(dark, "#ffffff", 0.15),
        "accent_dark_soft": mix(dark, DARK_BACKGROUND, 0.85),
        "on_accent_dark": on_dark,
    }
