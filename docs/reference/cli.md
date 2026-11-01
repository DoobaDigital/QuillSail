# Command line

Every command starts with `quillsail`. The older `copydesk` name still works as an alias. Commands that work on a publication find its configuration from `--config`, then the `COPYDESK_CONFIG` environment variable, then `./copydesk.toml`, then `/etc/copydesk/copydesk.toml`. Use `--instance NAME` instead for a named local publication.

This page covers the full command-line tool that comes with the Python package and server installations. The `quillsail` command added by the [terminal installer](../install-script.md) opens the desktop app instead.

Run `quillsail COMMAND --help` for the same details in your terminal.

## Options for every command

The `quillsail` command. `copydesk` is kept as an alias for existing installs.

```text
quillsail [OPTIONS] COMMAND [ARGS]...
```

| Argument or option | What it does |
| --- | --- |
| `--config FILE` | Path to copydesk.toml (default: ./copydesk.toml, then /etc/copydesk/copydesk.toml). |
| `--instance TEXT` | Use a named local instance (see `quillsail instance list`). |
| `--version` | Show the version and exit. |

## `quillsail check`

Check the configuration, database, folders and email settings.

```text
quillsail check [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--smtp` | Also connect and sign in to the mail server. |
| `--send-test EMAIL` | Send a test email to this address (needs a running worker or --now). |
| `--now` | With --send-test, send immediately instead of queueing. |

## `quillsail demo`

Fill an EMPTY test site with sample writers, articles and an issue.

```text
quillsail demo [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--yes` | Don't ask for confirmation. |

## `quillsail desktop`

Open the desktop launcher and start a local publication in your browser.

```text
quillsail desktop [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--data-dir DIRECTORY` | Use a separate desktop publication folder. |

## `quillsail export`

Save every table as JSON (a database-independent backup).

```text
quillsail export [OPTIONS] OUTPUT
```

| Argument or option | What it does |
| --- | --- |
| `OUTPUT` | Required. |

## `quillsail ext`

Commands added by extensions, named extension:command.

```text
quillsail ext [OPTIONS] COMMAND [ARGS]...
```

## `quillsail import`

Load a JSON export into an EMPTY database (e.g. to move from SQLite to PostgreSQL).

```text
quillsail import [OPTIONS] SOURCE
```

| Argument or option | What it does |
| --- | --- |
| `SOURCE` | Required. |
| `--yes` | Don't ask for confirmation. |

## `quillsail init`

Set up a new site: write copydesk.toml, create the database and the first administrator.

```text
quillsail init [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--dir DIRECTORY` | Where to create copydesk.toml and the data folder. [default: .] |
| `--site-name TEXT` | The publication's name. |
| `--mode [newsletter\|blog\|hybrid]` | Run as a newsletter, a blog, or a blog with a newsletter. [default: newsletter] |
| `--base-url TEXT` | The public address, e.g. https://news.example.edu |
| `--database-url TEXT` | Leave out to use SQLite in the data folder. |
| `--admin-email TEXT` |  |
| `--admin-name TEXT` |  |
| `--admin-password TEXT` | Better to type it when asked, so it doesn't end up in your shell history. |
| `--from-email TEXT` | The address emails come from. |
| `--behind-proxy` | QuillSail will run behind nginx, Apache or another proxy. |
| `-y, --yes` | Don't ask questions; use the options and defaults. |
| `--force` | Overwrite an existing copydesk.toml. |

## `quillsail instance`

Create, list, delete and run independent local publications.

```text
quillsail instance [OPTIONS] COMMAND [ARGS]...
```

### `quillsail instance add`

Register an existing desktop publication without changing its data.

```text
quillsail instance add [OPTIONS] NAME DATA_DIR
```

| Argument or option | What it does |
| --- | --- |
| `NAME` | Required. |
| `DATA_DIR` | Required. |

### `quillsail instance create`

Create a private publication. Complete its account setup in the browser.

```text
quillsail instance create [OPTIONS] NAME
```

| Argument or option | What it does |
| --- | --- |
| `NAME` | Required. |
| `--data-dir DIRECTORY` | Use an empty folder instead of the managed data folder. |

### `quillsail instance delete`

Remove a stopped instance, including default. Keep files unless --delete-data is used.

```text
quillsail instance delete [OPTIONS] NAME
```

| Argument or option | What it does |
| --- | --- |
| `NAME` | Required. |
| `--delete-data` | Permanently delete the publication folder and all its contents. |
| `--yes` | Skip the confirmation prompt. |

### `quillsail instance list`

```text
quillsail instance list [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--json` | Print names, paths and running addresses as JSON. |

### `quillsail instance run`

Run one or more instances until Ctrl+C; each gets an available local port.

```text
quillsail instance run [OPTIONS] NAMES...
```

| Argument or option | What it does |
| --- | --- |
| `NAMES` | Required. |
| `--no-browser` | Print local setup/dashboard links without opening a browser. |
| `--no-worker` | Run websites without processing background jobs. |

## `quillsail jobs`

Background jobs: run, list and retry.

```text
quillsail jobs [OPTIONS] COMMAND [ARGS]...
```

### `quillsail jobs list`

Show jobs with a given status.

```text
quillsail jobs list [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--status [queued\|running\|failed\|done]` |  |

### `quillsail jobs retry-failed`

Queue every failed job to run again.

```text
quillsail jobs retry-failed [OPTIONS]
```

### `quillsail jobs run`

Process waiting jobs, then exit. Good for cron: * * * * * quillsail jobs run

```text
quillsail jobs run [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--max-jobs INTEGER` | Stop after this many jobs. |
| `--max-time FLOAT` | Stop after this many seconds (fits a once-a-minute cron job). [default: 55] |

## `quillsail quit`

Quit the desktop app and stop the publications it started.

```text
quillsail quit [OPTIONS]
```

## `quillsail serve`

Run a development server. For production, use gunicorn (see docs/installation.md).

```text
quillsail serve [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--host TEXT` | [default: 127.0.0.1] |
| `--port INTEGER` | [default: 5000] |
| `--no-worker` | Don't run the background worker in this process. |
| `--no-reload` | Don't restart when code changes. |

## `quillsail subscribers`

Import and export the subscriber list.

```text
quillsail subscribers [OPTIONS] COMMAND [ARGS]...
```

### `quillsail subscribers export`

Write subscribers as CSV.

```text
quillsail subscribers export [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--status [active\|pending\|unsubscribed\|bounced\|all]` | [default: active] |
| `-o, --output FILENAME` |  |

### `quillsail subscribers import`

Import a CSV with an "email" column (and optional "name" and "groups").

```text
quillsail subscribers import [OPTIONS] CSV_FILE
```

| Argument or option | What it does |
| --- | --- |
| `CSV_FILE` | Required. |
| `--confirmed` | Subscribe everyone straight away. Only if they already agreed to get this newsletter. |

## `quillsail tunnel`

Run a connected Cloudflare tunnel on a server.

```text
quillsail tunnel [OPTIONS] COMMAND [ARGS]...
```

### `quillsail tunnel run`

Run the tunnel with encrypted credentials and automatic restart.

```text
quillsail tunnel run [OPTIONS]
```

## `quillsail update`

Update a desktop app or a registered Python/Compose server.

Servers: run 'quillsail update setup' once, then 'quillsail update'. The
command verifies the release, prepares it, backs up, migrates, activates,
checks web/worker health and recovers failures. No mail test is sent.

```text
quillsail update [OPTIONS] [COMMAND] [ARGS]...
```

| Argument or option | What it does |
| --- | --- |
| `--check` | Check availability without changing the installation. |
| `--app DIRECTORY` | Desktop application folder. |
| `--desktop` | Check desktop releases rather than server packages. |
| `--profile PATH` | Registered server update profile. |
| `--resume` | Recover or finish an interrupted server update. |
| `--channel [stable\|beta]` | Override the registered update channel. |
| `-y, --yes` | Approve the update without an interactive confirmation. |

### `quillsail update bootstrap`

One-time/offline installation of an explicitly checksum-pinned server wheel.

This is an operator-provided installer, not an unsigned network fallback.
Normal future updates authenticate their release metadata with TUF.

```text
quillsail update bootstrap [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--profile PATH` |  |
| `--wheel FILE` | [required] |
| `--sha256 TEXT` | Checksum obtained with the trusted first-install package. [required] |
| `-y, --yes` |  |

### `quillsail update capabilities`

Report the updater/maintenance contract without loading an instance.

```text
quillsail update capabilities [OPTIONS]
```

### `quillsail update install-command`

Install or verify a stable command for an already registered server.

```text
quillsail update install-command [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--profile PATH` |  |
| `--command PATH` | Default: the registered command, or /usr/local/bin/quillsail. |

### `quillsail update rollback`

Restore the last matching app/database backup, preserving current data first.

```text
quillsail update rollback [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--profile PATH` |  |
| `-y, --yes` |  |
| `--acknowledge-mail-replay` | Acknowledge that restored pending jobs may resend mail already delivered since the snapshot. |

### `quillsail update setup`

Register an existing deployment; preserve its configuration and services.

Use the standard versioned Python/systemd layout, or register an existing
Compose project. This command records settings without changing live code.

```text
quillsail update setup [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--profile PATH` |  |
| `--kind [python\|compose]` | [default: python] |
| `--install-root PATH` | [default: /opt/copydesk] |
| `--instance-root PATH` |  |
| `--backup-root PATH` | [default: /var/backups/copydesk] |
| `--service-user TEXT` | [default: copydesk] |
| `--web-service TEXT` | [default: copydesk-web] |
| `--worker-service TEXT` | [default: copydesk-worker] |
| `--health-url TEXT` |  |
| `--compose-file FILE` |  |
| `--project TEXT` | [default: copydesk] |
| `--base-image TEXT` | Pinned Python base image for Compose builds; setup resolves a supplied tag once. |
| `--environment-file FILE` |  |
| `--backup-host TEXT` | Host-reachable database address when container DNS differs. |
| `--backup-port INTEGER` |  |
| `--channel [stable\|beta]` | [default: beta] |
| `--command PATH` | Stable server command; its directory must be on sudo's PATH. [default: /usr/local/bin/quillsail] |
| `--no-command` | Register without installing a system-wide command. |
| `-y, --yes` |  |

### `quillsail update status`

Show the installed server version and its latest transaction state.

```text
quillsail update status [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--profile PATH` |  |

## `quillsail upgrade`

Create or update the database tables. Run after every QuillSail upgrade.

```text
quillsail upgrade [OPTIONS]
```

## `quillsail user`

Manage accounts from the command line.

```text
quillsail user [OPTIONS] COMMAND [ARGS]...
```

### `quillsail user add-group`

Put someone in a group, e.g.: quillsail user add-group ada@example.edu editors

```text
quillsail user add-group [OPTIONS] EMAIL GROUP_SLUG
```

| Argument or option | What it does |
| --- | --- |
| `EMAIL` | Required. |
| `GROUP_SLUG` | Required. |

### `quillsail user create`

Create a confirmed account.

```text
quillsail user create [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--email TEXT` | [required] |
| `--name TEXT` | [required] |
| `--password TEXT` |  |
| `--group TEXT` | Group to add them to (repeatable), e.g. --group editors |
| `--admin` | Make them an administrator. |

### `quillsail user list`

List accounts and their groups.

```text
quillsail user list [OPTIONS]
```

### `quillsail user set-password`

Set someone's password (and sign them out everywhere).

```text
quillsail user set-password [OPTIONS] EMAIL
```

| Argument or option | What it does |
| --- | --- |
| `EMAIL` | Required. |
| `--password TEXT` |  |

## `quillsail worker`

Send email and do other background work. Keep this running (systemd, Docker or supervisor).

```text
quillsail worker [OPTIONS]
```

| Argument or option | What it does |
| --- | --- |
| `--poll FLOAT` | Seconds to wait between checks when idle. [default: 2.0] |

---

*Generated from the QuillSail 1.15.0 source code by `scripts/build_reference_docs.py`.*
