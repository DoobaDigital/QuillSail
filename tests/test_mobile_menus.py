"""Menu buttons on narrow screens (issue #34).

The templates, app.js and copydesk.css must agree on the classes that open the
publication menu and the dashboard drawer. tests/js/navigation.test.cjs runs
app.js against the markup checked here.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from lxml import html

import copydesk

STATIC = Path(copydesk.__file__).parent / "static"
CSS = (STATIC / "css/copydesk.css").read_text()
APP_JS = (STATIC / "js/app.js").read_text()


def rule(selector: str) -> str:
    """Declarations of the first CSS rule with exactly this selector."""
    match = re.search(r"(?:^|[}\n])\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert match, f"Missing CSS rule {selector}"
    return match.group(1)


def test_publication_menu_markup_script_and_styles_agree(client):
    page = html.fromstring(client.get("/").data)
    (button,) = page.xpath("//button[@data-nav-toggle]")
    assert button.get("aria-expanded") == "false" and "Menu" in button.text_content()
    (target,) = page.xpath(f"//*[@id='{button.get('aria-controls')}']")
    assert "nav-list" in target.get("class", "").split()
    assert target.xpath("ancestor::nav[contains(concat(' ', @class, ' '), ' site-nav ')]")
    assert 'closest(".site-nav")' in APP_JS and 'classList.toggle("is-open", open)' in APP_JS
    assert "display: none" in rule(".js .site-nav .nav-list")
    assert "display: flex" in rule(".js .site-nav.is-open .nav-list")
    # Without JavaScript the links stay visible: only .js hides them.
    assert not re.search(r"(?:^|[}\n])\s*\.site-nav \.nav-list\s*\{[^}]*display: none", CSS)


def test_dashboard_drawer_markup_script_and_styles_agree(editor_client):
    page = html.fromstring(editor_client.get("/dashboard/").data)
    (toggle,) = page.xpath("//button[@data-dash-nav-toggle]")
    assert toggle.get("aria-expanded") == "false" and toggle.get("aria-controls") == "cd-dash-nav"
    (sidebar,) = page.xpath("//aside[@id='cd-dash-nav']")
    assert "dash-sidebar" in sidebar.get("class").split()
    assert "dash" in sidebar.getparent().get("class").split()
    (close,) = sidebar.xpath(".//button[@data-dash-nav-close]")
    assert close.get("type") == "button" and close.text_content().strip() == "Close menu"
    assert sidebar.index(close) == 0, "Close sits where the Menu button was, at the top of the drawer"
    assert page.xpath("//div[contains(concat(' ', @class, ' '), ' dash-scrim ')]")
    assert '"[data-dash-nav-close], .dash-scrim"' in APP_JS and 'dash.classList.toggle("nav-open", open)' in APP_JS
    assert "display: flex" in rule(".js .dash.nav-open .dash-sidebar")
    assert "display: none" in rule(".dash-nav-close")
    assert "display: inline-flex" in rule(".js .dash-nav-close")


@pytest.mark.skipif(not shutil.which("node"), reason="Node is needed for the menu script tests")
def test_menu_scripts_open_close_and_return_focus():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["node", "--test", "tests/js/navigation.test.cjs"], cwd=root, check=True)
