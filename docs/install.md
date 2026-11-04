# Ways to install

QuillSail runs in three ways. They use the same software and the same data format, so you can start on the desktop and move to a server later.

| | Desktop app | Docker Compose | Python package |
| --- | --- | --- | --- |
| Best for | Trying QuillSail, preparing a publication, local use | A public publication on one server | A public publication on a server you manage closely |
| Who can reach it | Only your computer | Anyone, through your HTTPS proxy | Anyone, through your HTTPS proxy |
| What you need | macOS, Windows or Linux with a desktop | A Linux server with Docker | Python 3.11 or newer |
| Background worker | Built in | Its own container | A separate service, such as systemd |
| Database | SQLite | SQLite, PostgreSQL or MySQL/MariaDB | SQLite, PostgreSQL or MySQL/MariaDB |
| Updates | The **Check for updates** button | `sudo quillsail update` | `sudo quillsail update` |
| Guide | [Desktop app](desktop.md) | [Server installation](installation.md#docker-compose) | [Server installation](installation.md#python-installation) |

## The desktop app

The desktop app includes Python and everything else QuillSail needs. Install it with one command:

```sh
curl -fsSL https://quillsail.blog/install.sh | bash
```

```powershell
irm https://quillsail.blog/install.ps1 | iex
```

Or download it from [quillsail.blog/download](https://quillsail.blog/download):

| Your computer | Download |
| --- | --- |
| Mac with Apple silicon (M1 and later) | `QuillSail-VERSION-macos-arm64.zip` |
| Mac with an Intel processor | `QuillSail-VERSION-macos-x86_64.zip` |
| 64-bit Windows | `QuillSail-VERSION-windows-x86_64.zip` |
| 64-bit Linux with a desktop (Ubuntu 22.04 or newer) | `QuillSail-VERSION-linux-x86_64.tar.gz` |

Every version, with its checksums, is also on [GitHub Releases](https://github.com/DoobaDigital/QuillSail/releases). No desktop on that computer? [`quillsail instance`](desktop.md#using-quillsail-from-the-terminal) runs the same app from a terminal. The [terminal installer](install-script.md) and the [desktop app guide](desktop.md) cover both routes in detail.

## A server

A public publication needs an always-on server with a domain name and HTTPS, plus a mail server or a Gmail or Outlook account to send from. The [server installation](installation.md) guide covers Docker Compose and the Python package, the reverse proxy, and the first-run setup code.

After installation, register the server once for [one-command updates](server-updates.md), and set up [backups](maintenance.md).

## Requirements at a glance

- **Python**: 3.11, 3.12, 3.13 or 3.14 for the Python package. The desktop app and container include their own.
- **Databases**: SQLite (the default), PostgreSQL, or MySQL/MariaDB. Install the `postgres` or `mysql` extra for those drivers.
- **Email**: any SMTP server, or a Gmail or Outlook account after a one-time app registration. See [email and delivery](email.md).
- **Desktop builds**: macOS on Apple silicon or Intel, 64-bit Windows, and 64-bit Linux with a desktop environment. There's no ARM Linux or 32-bit Windows build. Windows on ARM runs the 64-bit build through emulation.

## Moving between installations

`quillsail export` saves every table as JSON, and `quillsail import` loads that file into an empty database. To bring in a blog from elsewhere instead, see [importing a blog](importing-a-blog.md). Use it to move between databases, for example from SQLite to PostgreSQL. [Backups and upgrades](maintenance.md) explains what to copy alongside the export, including uploads and the secret key.
