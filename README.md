# QuillSail

<img src="assets/QuillSail.svg" alt="QuillSail quill logo" width="120" height="101">

Self-hosted blogs and newsletters where readers write.

Built by [Dooba Digital](https://github.com/DoobaDigital).

QuillSail brings blog publishing, reader submissions, editorial review, customizable community groups, and newsletter delivery into one application. Organizations host their own installation and own their data. Choose Newsletter, Blog, or Blog + newsletter. The publication name, branding, groups, permissions, pages, and email content are configurable.

The product name is **QuillSail**, with capital Q and S. The command is `quillsail`. The older `copydesk` command still works as an alias, and the `copydesk` Python package, configuration names, and integration identifiers are unchanged for compatibility with installed sites.

The project originated in work for **The Tech Stack**, a publication operated by the University of South Carolina Association for Computing Machinery. Other installations choose their own name, branding and community rules.

## What it includes

- A blog mode with direct publishing for trusted publishers, plus optional inclusion in local or separately hosted newsletters.
- Markdown writing with previews, image uploads, co-authors, revision history, and submission timelines.
- Editorial review, feedback, change requests, acceptance, publication, and email notifications.
- Custom groups such as students, staff, and alumni, with custom profile fields, approval rules, domain rules, badges, and permissions.
- Double opt-in subscriptions without requiring an account; preference management and one-click unsubscribe.
- An issue composer with articles, headings, text blocks, audience targeting, test emails, scheduling, and delivery reports.
- Competitions with moderated text/project entries, appointed judges, reader voting, deadlines, and published results.
- Business outreach with confirmed contact emails, a private dashboard inbox, follow-up notes, and opportunities that can become editorial drafts.
- Private draft issue links for external feedback, with expiry, revocation, and no public listing.
- A publication designer with logo variants, QuillSail's own ink-on-paper style and five original starting styles, typography, color and layout controls, private website/email previews, custom CSS, and portable design files. The dashboard has its own designer with the same controls, or can match the publication.
- Public archives, search, Atom feeds, informational pages, and account data export/deletion.
- Themes with template inheritance and Python extensions with events, filters, settings, commands, and background jobs.
- SQLite by default; optional PostgreSQL and MySQL drivers. SMTP delivery with a persistent job queue.

## Open the desktop app

The desktop launcher starts a local publication and opens the dashboard in your browser. A short first-run form creates your administrator; later launches reopen your saved publication. Packaged builds include Python and need no terminal or Docker. The native window offers **Open dashboard**, **Start / Stop**, **View logs**, and **Open data folder**. Starting with 1.9.1, its instance selector can create and run several independent publications at once. The CLI shares the same list through `quillsail instance create`, `list`, and `run`.

### Desktop beta downloads

| Your computer | Download |
| --- | --- |
| Mac — Apple Silicon (M-series) | [macOS arm64](https://github.com/DoobaDigital/QuillSail/releases/download/v1.10.0/QuillSail-1.10.0-macos-arm64.zip) |
| Mac — Intel | [macOS x86-64](https://github.com/DoobaDigital/QuillSail/releases/download/v1.10.0/QuillSail-1.10.0-macos-x86_64.zip) |
| Windows — 64-bit Intel/AMD | [Windows x64](https://github.com/DoobaDigital/QuillSail/releases/download/v1.10.0/QuillSail-1.10.0-windows-x86_64.zip) |
| Linux — 64-bit Intel/AMD | [Linux x86-64](https://github.com/DoobaDigital/QuillSail/releases/download/v1.10.0/QuillSail-1.10.0-linux-x86_64.tar.gz) |

Extract the download and open **QuillSail**. Keep the Windows/Linux bundle folder together. These are beta builds. Mac downloads from 1.11.2 onward are notarized by Apple; Windows code signing isn't configured yet. [Release notes and checksums](https://github.com/DoobaDigital/QuillSail/releases/tag/v1.10.0) · [Desktop guide](docs/desktop.md). The CLI remains available for servers and automation.

## Deploy with Docker Compose

From a checkout of this repository, with Docker and its Compose plugin installed:

```sh
cp deploy/compose.env.example deploy/compose.env
docker compose --env-file deploy/compose.env up -d --build
```

Open `http://localhost:8080`, then retrieve the first-run setup code:

```sh
docker compose --env-file deploy/compose.env exec web cat /var/lib/copydesk/data/setup-code.txt
```

Create your administrator and choose **Newsletter**, **Blog**, or **Blog + newsletter**. There are no default production credentials. Configuration and data persist in a named volume, with separate web and worker containers. Email initially stays in the local file backend until you connect a sender.

For a public deployment, configure your HTTPS hostname and reverse proxy using the [installation guide](docs/installation.md). The software is **beta**; keep backups and verify delivery on your installation.

## Try it with Python

Requires Python 3.11 or newer. From this source directory:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
quillsail init --dir ./instance --site-name 'My publication' --mode hybrid --base-url http://localhost:5055
quillsail --config ./instance/copydesk.toml serve --port 5055
```

Open http://localhost:5055 and sign in with the administrator account you created. The development server runs a background worker. Email defaults to the console backend, so messages appear in the server log. To add fictional example content on an empty test site:

```sh
quillsail --config ./instance/copydesk.toml demo
```

Demo accounts use `demo-password-123`; use the demo only in a local test installation.

## Documentation

The [documentation overview](docs/README.md) lists every guide. The same pages are published as the documentation website from `website/`.

- [How QuillSail works](docs/introduction.md) and the [quickstart](docs/quickstart.md)
- [Ways to install](docs/install.md) and the [terminal installer](docs/install-script.md)
- [Server installation](docs/installation.md)
- [Desktop launcher](docs/desktop.md)
- [GitHub setup and releases](docs/github.md)
- [Configuration](docs/configuration.md)
- [Email and delivery](docs/email.md)
- [Connect Gmail, Outlook, or an SMTP server](docs/email-connectors.md)
- [Editorial and administrator guide](docs/user-guide.md): [setup](docs/publication-setup.md), [groups and permissions](docs/groups-and-permissions.md), [writing and review](docs/writing-and-review.md), [blog and newsletter modes](docs/publication-modes.md), [newsletter issues](docs/newsletter-issues.md), [subscribers and accounts](docs/subscribers.md) and [competitions](docs/competitions.md)
- [Business outreach and private issue previews](docs/business-outreach.md)
- [Themes](docs/theming.md)
- [Extensions](docs/extensions.md)
- [Public API](docs/api.md)
- [Follow-up review](docs/review.md)
- [Database, SMTP, and university deployment verification](docs/verification.md)
- [Backups and upgrades](docs/maintenance.md)
- [One-command server updates and recovery](docs/server-updates.md)
- [Security model](docs/security.md) and [troubleshooting](docs/troubleshooting.md)
- Reference: [command line](docs/reference/cli.md), [configuration file](docs/reference/configuration.md), [dashboard settings](docs/reference/settings.md), [permissions](docs/reference/permissions.md), [editorial workflow](docs/reference/workflow.md) and [extension hooks](docs/reference/hooks.md)
- [Architecture](docs/architecture.md), [contributing](CONTRIBUTING.md) and [security reporting](SECURITY.md)

## Development

```sh
pip install -e '.[dev]'
pytest
ruff check src tests scripts deploy
```

Tests use temporary SQLite databases by default. Install `.[integration]` for real loopback SMTP/TLS tests, or set `COPYDESK_TEST_DATABASE_URL` with the appropriate database driver to run against disposable PostgreSQL or MySQL/MariaDB databases. CI also checks Python 3.11–3.14, built distributions and container startup. See the [verification report](docs/verification.md) for actual runs and remaining limits. This project has not undergone an independent security audit.

Licensed under the [MIT License](LICENSE).
