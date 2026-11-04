"""Generate the reference pages in docs/reference/ from the source code.

The command line, configuration, dashboard settings, permissions, editorial
workflow and extension hooks are all declared in code. These pages are built
from those declarations, so they always match the installed version.

    python scripts/build_reference_docs.py          # rewrite docs/reference/
    python scripts/build_reference_docs.py --check  # fail if a page is out of date
"""

from __future__ import annotations

import argparse
import inspect
import string
import sys
from pathlib import Path

import click

from copydesk import __version__, hooks, permissions, seed, settings, workflow
from copydesk.cli import main as cli
from copydesk.config import ENV_OVERRIDES

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/reference"
FOOTER = "\n---\n\n*Generated from the QuillSail {version} source code by `scripts/build_reference_docs.py`.*\n"


def cell(text) -> str:
    """Make text safe inside a Markdown table cell."""
    return " ".join(str(text).split()).replace("|", "\\|")


def table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def page(title: str, intro: str, body: str) -> str:
    return f"# {title}\n\n{intro.strip()}\n\n{body.strip()}\n" + FOOTER.format(version=__version__)


# --- command line ----------------------------------------------------------------------------------


def command_details(command: click.Command, name: str) -> list[str]:
    """The description, usage line and options of one command."""
    context = click.Context(command, info_name=name)
    out = []
    description = inspect.cleandoc(command.help or command.short_help or "")
    if description:
        out.append(description.replace("\b\n", "") + "\n")
    usage = " ".join(command.collect_usage_pieces(context))
    out.append(f"```text\n{name} {usage}\n```\n")
    rows = []
    for parameter in command.get_params(context):
        if isinstance(parameter, click.Argument):
            rows.append([f"`{parameter.human_readable_name}`", "Required." if parameter.required else "Optional."])
        elif "--help" not in parameter.opts:
            record = parameter.get_help_record(context)
            if record:
                rows.append([f"`{record[0]}`", record[1] or ""])
    if rows:
        out.append(table(["Argument or option", "What it does"], rows))
    return out


def command_section(command: click.Command, path: list[str], level: int) -> list[str]:
    name = " ".join(path)
    out = [f"{'#' * level} `{name}`\n", *command_details(command, name)]
    if isinstance(command, click.Group):
        for child_name, child in sorted(command.commands.items()):
            if not child.hidden:
                out.extend(command_section(child, [*path, child_name], min(level + 1, 4)))
    return out


def cli_page() -> str:
    body = []
    for name, command in sorted(cli.commands.items()):
        if not command.hidden:
            body.extend(command_section(command, ["quillsail", name], 2))
    intro = (
        "Every command starts with `quillsail`. The older `copydesk` name still works as an alias. "
        "Commands that work on a publication find its configuration from `--config`, then the "
        "`COPYDESK_CONFIG` environment variable, then `./copydesk.toml`, then `/etc/copydesk/copydesk.toml`. "
        "Use `--instance NAME` instead for a named local publication.\n\n"
        "This page covers the full command-line tool. It comes with the Python package, server "
        "installations and the [terminal installer](../install-script.md). Without a command, `quillsail` "
        "prints this list.\n\n"
        "Run `quillsail COMMAND --help` for the same details in your terminal."
    )
    options = "## Options for every command\n\n" + "\n".join(command_details(cli, "quillsail"))
    return page("Command line", intro, options + "\n" + "\n".join(body))


# --- configuration ---------------------------------------------------------------------------------


def configuration_page() -> str:
    template = (ROOT / "src/copydesk/config_template.toml").read_text(encoding="utf-8")
    example = string.Template(template).safe_substitute(
        base_url="https://news.example.edu", secret_key="(a long random value written by quillsail init)",
        database_url="sqlite:///data/copydesk.db", mail_backend="console", from_email="newsletter@example.edu",
        proxy_hops="0",
    )
    rows = [[f"`{name}`", f"`[{section}] {key}`"] for name, (section, key) in ENV_OVERRIDES.items()]
    body = (
        "## Environment variables\n\n"
        "Each variable overrides one value in the file. Lists, such as `COPYDESK_EXTENSIONS`, are comma-separated.\n\n"
        + table(["Variable", "Overrides"], rows)
        + "\n## The configuration file\n\n"
        "`quillsail init` writes this file, with your answers filled in. The values below are examples.\n\n"
        f"```toml\n{example.strip()}\n```\n"
    )
    intro = (
        "The configuration file, `copydesk.toml`, holds what the server needs to run: the public address, "
        "the database, email delivery and a secret key. Everything editors change, such as the publication's "
        "name, look and sign-up rules, lives in the dashboard instead (see [dashboard settings](settings.md)). "
        "Restart the web and worker processes after changing the file. [Configuration](../configuration.md) "
        "explains how the file is found."
    )
    return page("Configuration file", intro, body)


# --- dashboard settings ----------------------------------------------------------------------------


def describe_default(definition: settings.SettingDef) -> str:
    value = definition.default
    if definition.type == "bool":
        return "On" if value else "Off"
    if value in ("", [], None):
        return "Blank"
    if isinstance(value, list):
        return ", ".join(f"`{item}`" for item in value)
    text = str(value)
    if definition.type in {"markdown", "textarea"} and len(text) > 80:
        return "A starter message"
    if definition.type == "choice" and not callable(definition.choices):
        labels = dict(definition.get_choices())
        if value in labels:
            return f"{labels[value]} (`{value}`)"
    return f"`{text}`"


def settings_page() -> str:
    tabs = dict(settings.TABS)
    sections = []
    for tab, label in tabs.items():
        definitions = [d for d in settings.REGISTRY.values() if d.tab == tab]
        if not definitions:
            continue
        rows = []
        for definition in definitions:
            notes = definition.help
            if definition.type == "choice" and not callable(definition.choices):
                options = ", ".join(choice_label for _value, choice_label in definition.get_choices())
                notes = (notes + " " if notes else "") + f"Options: {options}."
            if definition.type == "int" and "min" in definition.extra:
                notes = (notes + " " if notes else "") + f"From {definition.extra['min']} to {definition.extra['max']}."
            rows.append([definition.label, f"`{definition.key}`", describe_default(definition), notes])
        sections.append(f"## {label}\n\n" + table(["Setting", "Key", "Default", "Notes"], rows))
    intro = (
        "Administrators change these under **Dashboard → Settings**, and they're stored in the database, so "
        "they take effect without a restart. Settings marked as uploads, such as logos, are changed on the "
        "Appearance page. Extensions can add their own settings, which appear under **Extensions**. "
        "Keys are what templates and extensions read, for example `setting('site.name')`."
    )
    return page("Dashboard settings", intro, "\n".join(sections))


# --- permissions -----------------------------------------------------------------------------------


def permissions_page() -> str:
    by_key = {permission.key: permission.label for permission in permissions.all_permissions()}
    areas = []
    for area, items in permissions.by_area().items():
        areas.append(f"### {area}\n\n" + table(["Permission", "Key", "What it allows"],
                                               [[p.label, f"`{p.key}`", p.description] for p in items]))
    group_rows = []
    for group in seed.DEFAULT_GROUPS:
        if group.get("is_implicit"):
            kind = "Implicit"
        elif group.get("is_system"):
            kind = "System"
        else:
            kind = "Reader group"
        granted = "Every permission" if group["slug"] == "admins" else (
            ", ".join(by_key.get(key, key) for key in group.get("permissions", [])) or "None")
        policy = {"open": "Open", "approval": "Approval", "closed": "Closed"}.get(group.get("join_policy", ""), "—")
        group_rows.append([group["name"], f"`{group['slug']}`", kind, policy, granted])
    body = (
        "## Permissions\n\nA person's permissions are the combined permissions of every group they belong to. "
        "Administrators always hold every permission.\n\n" + "\n".join(areas)
        + "\n## Groups on a new site\n\nNew sites start with these groups. Rename, change or remove the reader "
        "groups under **Dashboard → Groups**. System groups can't be deleted.\n\n"
        + table(["Group", "Slug", "Kind", "Joining", "Permissions at the start"], group_rows)
    )
    intro = (
        "Permissions belong to groups, and people collect them by joining groups. Everyone, including "
        "visitors who aren't signed in, gets the **Everyone** group's permissions. People with a confirmed "
        "account also get **Members**. Someone can grant or assign only the permissions they hold "
        "themselves. See [groups and permissions](../groups-and-permissions.md) for how to use them."
    )
    return page("Permissions and groups", intro, body)


# --- editorial workflow ----------------------------------------------------------------------------


def workflow_page() -> str:
    labels = {key: status.label for key, status in workflow.STATUSES.items()}
    statuses = table(["Status", "Key", "What the writer sees", "What editors see"],
                     [[s.label, f"`{s.key}`", s.for_writer, s.for_editor] for s in workflow.STATUSES.values()])
    perm_labels = {p.key: p.label for p in permissions.all_permissions()}
    rows = []
    for transition in workflow.TRANSITIONS.values():
        who = "The writer" if transition.by == "writer" else f"An editor with *{perm_labels.get(transition.permission, transition.permission)}*"
        note = {"required": "Required", "optional": "Optional", "none": "—"}[transition.message]
        rows.append([transition.label, ", ".join(labels[source] for source in transition.sources),
                     labels[transition.target], who, note])
    body = (
        "## Statuses\n\n" + statuses
        + "\n## Moves between statuses\n\nEach move is recorded on the article's timeline, written to the "
        "activity log, emailed to the people involved and announced to extensions as "
        "`article.status_changed`. Writers can edit their piece while it's a draft or has changes requested.\n\n"
        + table(["Action", "From", "To", "Who can do it", "Note to the writer"], rows)
    )
    intro = (
        "Every piece of writing has a status. It changes only through the actions below, which check "
        "permissions on the server. Drafts are private to their writers and co-authors. "
        "[Writing and review](../writing-and-review.md) walks through the process."
    )
    return page("Editorial workflow", intro, body)


# --- hooks -----------------------------------------------------------------------------------------

# For Extension methods whose behavior is clear from the code but that have no docstring.
API_NOTES = {
    "on": "Decorator: run the function when an event happens.",
    "filter": "Decorator: let the function change a value before QuillSail uses it.",
    "slot": "Decorator: insert the function's HTML into a template slot.",
    "add_blueprint": "Add a Flask blueprint with the extension's own pages.",
    "add_dashboard_link": "Add a link to the dashboard menu, shown to people with the given permission.",
    "permission": "Add a permission to the permission editor, listed under the extension's title.",
}


def hooks_page() -> str:
    def rows(entries: dict[str, str]):
        result = []
        for name, description in entries.items():
            arguments, _, meaning = description.partition(" — ")
            result.append([f"`{name}`", arguments if meaning else "", meaning or description])
        return result

    api = []
    for name, member in inspect.getmembers(hooks.Extension, predicate=inspect.isfunction):
        if name.startswith("_") or name == "install":
            continue
        signature = inspect.signature(member)
        parameters = [parameter.replace(annotation=inspect.Parameter.empty)
                      for parameter in signature.parameters.values() if parameter.name != "self"]
        plain = signature.replace(parameters=parameters, return_annotation=inspect.Signature.empty)
        summary = (inspect.getdoc(member) or "").split("\n")[0] or API_NOTES.get(name, "")
        api.append([f"`{name}{plain}`", summary.replace("``", "`")])
    body = (
        "## Events\n\nRegister a handler with `@extension.on(\"event.name\")`. Handlers receive these keyword "
        "arguments.\n\n" + table(["Event", "Arguments", "When"], rows(hooks.EVENTS))
        + "\n## Filters\n\nRegister with `@extension.filter(\"filter.name\")`. A filter receives the current "
        "value, plus any extra arguments, and returns the value to use.\n\n"
        + table(["Filter", "Arguments", "What it changes"], rows(hooks.FILTERS))
        + "\n## Template slots\n\nRegister with `@extension.slot(\"slot\")` and return HTML to insert. Return "
        "markup from a template, or escape values yourself.\n\n"
        + table(["Slot", "Where it appears"], [[f"`{name}`", description] for name, description in hooks.SLOTS.items()])
        + "\n## The `Extension` object\n\n" + table(["Method", "What it does"], api)
    )
    intro = (
        "Extensions are Python modules that create `extension = Extension(\"name\")` and register hooks on it. "
        "[Extensions](../extensions.md) shows how to write and enable one. Handlers run in the web and worker "
        "processes with full access to the application, so install only extensions you trust."
    )
    return page("Extension hooks", intro, body)


PAGES = {
    "cli.md": cli_page,
    "configuration.md": configuration_page,
    "settings.md": settings_page,
    "permissions.md": permissions_page,
    "workflow.md": workflow_page,
    "hooks.md": hooks_page,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Report pages that don't match the code, without writing.")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    stale = []
    for name, build in PAGES.items():
        content = build()
        path = OUTPUT / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(ROOT).as_posix())
        else:
            path.write_text(content, encoding="utf-8")
    if stale:
        print("Out of date: " + ", ".join(stale) + ". Run: python scripts/build_reference_docs.py", file=sys.stderr)
        return 1
    print("Reference pages are up to date." if args.check else f"Wrote {len(PAGES)} pages to docs/reference/.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
