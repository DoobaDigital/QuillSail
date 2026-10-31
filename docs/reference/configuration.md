# Configuration file

The configuration file, `copydesk.toml`, holds what the server needs to run: the public address, the database, email delivery and a secret key. Everything editors change, such as the publication's name, look and sign-up rules, lives in the dashboard instead (see [dashboard settings](settings.md)). Restart the web and worker processes after changing the file. [Configuration](../configuration.md) explains how the file is found.

## Environment variables

Each variable overrides one value in the file. Lists, such as `COPYDESK_EXTENSIONS`, are comma-separated.

| Variable | Overrides |
| --- | --- |
| `CLOUDFLARE_CLIENT_ID` | `[oauth] cloudflare_client_id` |
| `COPYDESK_CLOUDFLARE_CLIENT_ID` | `[oauth] cloudflare_client_id` |
| `COPYDESK_CLOUDFLARE_EDGE_SCOPES` | `[oauth] cloudflare_edge_scopes` |
| `COPYDESK_CLOUDFLARE_SCOPES` | `[oauth] cloudflare_scopes` |
| `COPYDESK_CLOUDFLARE_RELAY_URL` | `[oauth] cloudflare_relay_url` |
| `COPYDESK_CLOUDFLARE_METADATA_URL` | `[oauth] cloudflare_metadata_url` |
| `COPYDESK_BASE_URL` | `[site] base_url` |
| `COPYDESK_SECRET_KEY` | `[site] secret_key` |
| `COPYDESK_DATA_DIR` | `[site] data_dir` |
| `COPYDESK_DEBUG` | `[site] debug` |
| `COPYDESK_DATABASE_URL` | `[database] url` |
| `COPYDESK_MAIL_BACKEND` | `[mail] backend` |
| `COPYDESK_MAIL_HOST` | `[mail] host` |
| `COPYDESK_MAIL_PORT` | `[mail] port` |
| `COPYDESK_MAIL_SECURITY` | `[mail] security` |
| `COPYDESK_MAIL_USERNAME` | `[mail] username` |
| `COPYDESK_MAIL_PASSWORD` | `[mail] password` |
| `COPYDESK_MAIL_FROM_EMAIL` | `[mail] from_email` |
| `COPYDESK_MAIL_RATE_PER_MINUTE` | `[mail] rate_per_minute` |
| `COPYDESK_UPLOADS_DIR` | `[uploads] dir` |
| `COPYDESK_UPLOADS_MAX_SIZE_MB` | `[uploads] max_size_mb` |
| `COPYDESK_JOBS_RUN_IN_WEB` | `[jobs] run_in_web` |
| `COPYDESK_PROXY_HOPS` | `[server] proxy_hops` |
| `COPYDESK_EXTENSIONS` | `[extensions] enabled` |
| `COPYDESK_LOG_LEVEL` | `[logging] level` |
| `GOOGLE_CLIENT_ID` | `[oauth] google_client_id` |
| `GOOGLE_CLIENT_SECRET` | `[oauth] google_client_secret` |
| `MICROSOFT_CLIENT_ID` | `[oauth] microsoft_client_id` |
| `MICROSOFT_CLIENT_SECRET` | `[oauth] microsoft_client_secret` |
| `MICROSOFT_TENANT` | `[oauth] microsoft_tenant` |
| `COPYDESK_GOOGLE_CLIENT_ID` | `[oauth] google_client_id` |
| `COPYDESK_GOOGLE_CLIENT_SECRET` | `[oauth] google_client_secret` |
| `COPYDESK_GOOGLE_METADATA_URL` | `[oauth] google_metadata_url` |
| `COPYDESK_MICROSOFT_CLIENT_ID` | `[oauth] microsoft_client_id` |
| `COPYDESK_MICROSOFT_CLIENT_SECRET` | `[oauth] microsoft_client_secret` |
| `COPYDESK_MICROSOFT_METADATA_URL` | `[oauth] microsoft_metadata_url` |
| `COPYDESK_MICROSOFT_TENANT` | `[oauth] microsoft_tenant` |

## The configuration file

`quillsail init` writes this file, with your answers filled in. The values below are examples.

```toml
# QuillSail configuration
# ======================
#
# This file holds what the server needs to run: where the database is, how
# to send email, and a secret key. Everything editors might want to change
# (the publication's name, colours, reader groups, permissions, sign-up
# options) is in the dashboard instead.
#
# Any value can also come from an environment variable, which is handy for
# Docker or for keeping passwords out of this file. For example,
# COPYDESK_MAIL_PASSWORD overrides [mail] password. See docs/configuration.md.
#
# Restart QuillSail (and the worker) after editing this file.

[site]
# The public address of the site, exactly as readers type it. Links in
# emails are built from this. It can include a path, such as
# "https://example.edu/newsletter".
base_url = "https://news.example.edu"

# Signs sessions and email links. Keep it secret and don't change it once
# the site is live, or every emailed link and session stops working.
secret_key = "(a long random value written by quillsail init)"

# Where the SQLite database (if you use one) and uploaded images live,
# relative to this file.
data_dir = "data"

# Shows detailed error pages. Never turn this on for a public site.
debug = false


[database]
# SQLite needs no setup and is fine for most publications:
#   url = "sqlite:///data/copydesk.db"
# PostgreSQL (install with: pip install "copydesk[postgres]"):
#   url = "postgresql+psycopg://copydesk:PASSWORD@localhost/copydesk"
# MySQL or MariaDB (pip install "copydesk[mysql]"):
#   url = "mysql+pymysql://copydesk:PASSWORD@localhost/copydesk?charset=utf8mb4"
url = "sqlite:///data/copydesk.db"


[mail]
# How email is sent:
#   "smtp"    a real mail server (your university's relay, Amazon SES,
#             Postmark, Mailgun, Purelymail, Google Workspace...)
#   "console" print emails to the log instead of sending them (for testing)
#   "file"    save each email as a .eml file in data/mail (for testing)
backend = "console"

# The address emails come from. Your mail server must be allowed to send
# as this address, and its domain needs SPF and DKIM records or your
# newsletter will land in spam. See docs/email.md.
from_email = "newsletter@example.edu"

# SMTP settings (only used when backend = "smtp").
host = "smtp.example.edu"
port = 587
security = "starttls"   # "starttls" (port 587), "ssl" (port 465) or "none" (port 25)
username = ""
password = ""           # or set COPYDESK_MAIL_PASSWORD instead
timeout = 30

# Newsletters go out at a steady pace so mail servers don't flag them.
# Many university relays allow about 60 to 120 a minute; ask your IT team.
rate_per_minute = 120


[uploads]
# Uploaded images (covers, avatars, pictures in articles). Back this folder up.
dir = "data/uploads"
max_size_mb = 10


[jobs]
# Emails are sent by a background worker. Run `quillsail worker` as a
# service (see docs/installation.md), or `quillsail jobs run` from cron.
# If you can't run a second process, set this to true to run the worker
# inside the web server instead.
run_in_web = false


[server]
# Behind a reverse proxy (nginx, Apache, a load balancer)? Set this to the
# number of proxies in front of QuillSail, usually 1, so it sees visitors'
# real IP addresses and HTTPS.
proxy_hops = 0


[extensions]
# Extensions add features. List the ones to turn on. QuillSail looks in the
# "extensions" folder next to this file, then at the ones it ships with,
# then at installed Python packages. See docs/extensions.md.
#   enabled = ["webhooks"]
enabled = []

# Each extension can have its own settings table:
# [extensions.webhooks]
# endpoints = [
#   { url = "https://discord.com/api/webhooks/...", format = "discord", events = ["issue.sent", "article.published"] },
# ]


[themes]
# Extra themes live here, one folder each. See docs/theming.md.
dir = "themes"


[logging]
level = "INFO"   # DEBUG, INFO, WARNING or ERROR


[oauth]
# Optional custom registrations; Gmail and Outlook use shared apps by default.
# These can also be entered by an administrator in Settings -> Email.
# Register the exact callback URL displayed there with the provider.
# Secrets may instead come from COPYDESK_GOOGLE_CLIENT_SECRET and
# COPYDESK_MICROSOFT_CLIENT_SECRET environment variables.
google_client_id = ""
google_client_secret = ""
microsoft_client_id = ""
microsoft_client_secret = ""
microsoft_tenant = "common"
# Shared discovery overrides; set empty to disable the respective shared app.
# google_metadata_url = "https://quillsail.blog/.well-known/quillsail/gmail.json"
# microsoft_metadata_url = "https://quillsail.blog/.well-known/quillsail/outlook.json"
```

---

*Generated from the QuillSail 1.14.1 source code by `scripts/build_reference_docs.py`.*
