# Architecture

A guide to the codebase for contributors. QuillSail is a server-rendered Flask application with a database-backed job queue, a small extension system, and optional desktop and update tooling around it. [Contributing](../CONTRIBUTING.md) covers setup and the checks to run.

## The shape of the application

```text
browser ──▶ Flask views (src/copydesk/views/) ──▶ domain modules ──▶ SQLAlchemy models ──▶ database
                │                                    │
                └── Jinja templates and themes       └── jobs.enqueue() ──▶ jobs table ──▶ worker ──▶ mail
```

- **Views** validate requests, check permissions and render templates. They don't hold business rules.
- **Domain modules** own the rules: `workflow.py` for editorial statuses, `groups.py` for joining, `subscribers.py` for subscriptions, `newsletter.py` for issues and sending, `competitions.py`, `publication.py` and `business.py`.
- **Background work** is saved as rows in the `jobs` table in the same transaction as the change that caused it, then run by the worker. Email is never sent during a request.

The package is named `copydesk` for compatibility with existing installations; the product, command and documentation say QuillSail.

## Where things live

| Path | What it does |
| --- | --- |
| `app.py` | `create_app()`, the per-app state in `app.extensions["copydesk"]`, request hooks, error handlers, Jinja filters, and the prefix middleware for sub-path installs |
| `config.py`, `config_template.toml` | Server configuration from TOML and `COPYDESK_*` environment variables |
| `settings.py` | Editor-facing settings, declared with `define()`; the settings screens are generated from these declarations |
| `models.py` | Every table, as typed SQLAlchemy 2 models |
| `permissions.py` | The permission registry, `permissions_for()`, `@require(...)` and the anti-escalation checks such as `can_assign()` |
| `workflow.py` | Article statuses and transitions, `can_view` and `can_edit`, revisions and comments |
| `newsletter.py` | Issue rendering, recipients, audience targeting and the send pipeline |
| `subscribers.py`, `groups.py`, `competitions.py`, `publication.py`, `business.py`, `issue_previews.py` | Domain rules for each feature |
| `notify.py` | Transactional email, rendered from `templates/email/<name>.html` and `.txt` |
| `mail.py`, `email_connections.py`, `email_assets.py` | Mail backends, encrypted senders, OAuth flows and inline logos |
| `jobs.py` | The job queue, worker, leases, heartbeat and maintenance |
| `hooks.py` | Extensions: events, filters, template slots, and the documented `EVENTS`, `FILTERS` and `SLOTS` |
| `themes.py`, `appearance.py`, `colors.py` | Template themes, the publication designer, and accent colors adjusted for contrast |
| `text.py` | Markdown to sanitized HTML, email styling, excerpts and revision diffs |
| `security.py`, `auth.py`, `audit.py` | CSRF, CSP nonces, headers and rate limits; sessions, passwords and signed tokens; the activity log |
| `uploads.py` | Image processing |
| `views/` | Blueprints: `public`, `auth`, `account`, `subscribe`, `write`, `competitions`, `business`, `api` (`/api/v1`), `setup`, and `dashboard/` with one module per area |
| `cli.py` | The `quillsail` command, built with Click |
| `migrations/versions/` | Alembic migrations, numbered `0001`, `0002`… |
| `desktop.py`, `desktop_ui.py`, `launcher.py`, `instances.py`, `installed_command.py` | The desktop runtime, the Qt launcher, the local control socket, named instances and repairing the installer's `quillsail` command |
| `updater.py`, `update_metadata.py`, `update_install.py`, `update_commands.py` | Signed updates with TUF, and the separate installer helper |
| `server_update.py`, `compose_update.py`, `server_backup.py`, `server_command.py`, `maintenance.py` | Transactional server updates and recovery |
| `extensions/webhooks` | The bundled webhooks extension |
| `themes/` | The bundled `default` and `broadsheet` themes |
| `demo.py` | Fictional sample content for `quillsail demo` |

Outside the package: `tests/`, `scripts/` (builds, smoke tests, release publishing and the [reference generator](#generated-reference-pages)), `deploy/` (systemd, Compose, Caddy and the server bootstrap), `docs/`, and `website/`, the source of quillsail.blog and this documentation site.

## Key ideas

**Groups are roles and reader types.** `everyone` and `members` are implicit groups; `editors` and `admins` are system groups, and admins always hold every permission. A person's permissions are the union of their groups' permissions. People can grant only permissions they hold: keep enforcing that through `permissions.can_assign()` and `can_manage_group()`.

**Every status change goes through `workflow.transition()`.** It checks the move is allowed, records the timeline event, writes the activity log, fires `article.status_changed`, and queues notifications.

**Sending is idempotent.** Starting a send uses a conditional `UPDATE`, so only one request can start it. Each subscriber gets one `Delivery` row, batches commit each delivery as it's sent, and batch jobs renew their lease while they work.

**Settings and permissions are registries.** `settings.define()` and `permissions.register()` declare everything in one place; the dashboard screens and the [reference pages](reference/settings.md) are built from them. Extensions add to the same registries.

**Templates resolve through themes.** `ThemeLoader` looks in the active theme, then its parent, then extensions, then the core templates.

**Each Flask app has its own database binding.** Engines and sessions resolve through the active app context, so several publications can run in one process, as the desktop launcher does.

## Conventions

- Keep SQL portable across SQLite, PostgreSQL and MySQL/MariaDB. Schema changes need an Alembic migration that works on all three (SQLite uses batch mode) and an upgrade test.
- Store naive UTC datetimes from `utils.utcnow()`, and display them with the `date`, `datetime` and `time_ago` filters, which use the publication's time zone.
- Build absolute links with `helpers.external_url()` in emails, feeds, the API and jobs.
- Every state-changing form includes `forms.csrf()`. Only token-authorized or deliberately public endpoints use `@csrf_exempt`.
- No inline `style` attributes or scripts in web templates; the Content Security Policy forbids them. Inline styles are fine in email templates.
- Use the form and UI macros in `templates/macros/`. Every field has a label, help text, and an error linked with `aria-describedby`.
- Dashboard actions that change something call `audit.record(...)`.
- Interface text is plain English in short sentences, and says what happens next.
- Don't hard-code any one organization's names or addresses: keep them in settings, themes or extensions.

## Tests

```sh
pip install -e '.[dev]'
pytest
ruff check src tests scripts deploy
```

`tests/conftest.py` provides an app with memory mail, migrations and seed data applied, an `admin` account and an `editor_client`. Sent mail collects in `copydesk.mail.outbox`, and `jobs.run_pending()` runs queued jobs inside a test. Set `COPYDESK_TEST_DATABASE_URL` to run the suite against PostgreSQL or MariaDB. Add a regression test with every bug fix.

## Generated reference pages

The pages under [Reference](reference/cli.md) are generated from the code by `scripts/build_reference_docs.py`. After changing commands, settings, permissions, workflow transitions or hooks, run:

```sh
python scripts/build_reference_docs.py
```

CI runs it with `--check` and fails if a page is out of date.

## The website

`website/` is a separate Flask application that serves quillsail.blog, docs.quillsail.blog and updates.quillsail.blog. It renders this `docs/` folder as the documentation site, serves the terminal installers, and offers downloads only after verifying them in the signed update feed. Its [README](../website/README.md) covers development and deployment.
