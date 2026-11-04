# Troubleshooting

Start with the tools QuillSail gives you:

- **`quillsail check`** checks the configuration, database, folders and email settings, and says how to fix each problem it finds. Add `--smtp` to sign in to the mail server too.
- **Dashboard → System status** shows the worker's last heartbeat and the job queue.
- **`/healthz`** answers when the web process can reach the database. It doesn't prove that email works.
- **The logs**: the launcher's **View logs**, `journalctl -u copydesk-web -u copydesk-worker` for systemd, or `docker compose logs web worker` for Compose.

Never paste configuration files, setup codes, tokens or subscriber data into a public issue.

## The desktop app

### macOS says it can't check QuillSail

Downloads from QuillSail 1.11.2 onward are notarized by Apple and open without this step. Version 1.11.1 and earlier, and apps you build yourself, aren't notarized, so macOS asks before opening them the first time. Open **System Settings → Privacy & Security**, scroll down, and choose **Open Anyway** next to the message about QuillSail.

### Windows SmartScreen appears

The Windows app isn't code-signed yet. Choose **More info**, then **Run anyway**.

### "Move QuillSail to a writable application folder before updating it"

macOS runs apps opened straight from a download in a temporary, read-only location. Move **QuillSail.app** into your Applications folder, open it from there, then check for updates again.

### The Linux app doesn't open

A minimal Linux system may be missing desktop libraries. On Ubuntu, install them with:

```sh
sudo apt-get install libegl1 libopengl0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libxcb-render-util0 libxcb-xfixes0
```

The window needs a graphical desktop. Without one, run `quillsail instance` from a terminal. Both need glibc 2.35 or newer (Ubuntu 22.04 or later).

### "QuillSail could not start"

Choose **View logs** for the details. Your publication's files are safe in its data folder; choose **Open data folder** to see them. If a schema upgrade failed, keep the backup the launcher made under `backups/`, and see [backups and upgrades](maintenance.md) before trying again.

### The browser didn't open

Choose **Open dashboard** in the launcher. If the window is closed, QuillSail is still running in the menu bar or system tray; open it again from there, or launch QuillSail again to bring its window forward.

### My publications keep running after I close the window

That's on purpose, so readers and the worker aren't interrupted. To stop everything, choose **Quit QuillSail** in the launcher, use ⌘Q (Ctrl+Q on Windows and Linux), or quit from the menu bar or tray icon.

## A server

### Where's the setup code?

The first visit to a new server asks for a setup code, so nobody else can claim it first. It's in the server log and in `data/setup-code.txt` beside `copydesk.toml`. With Docker Compose:

```sh
docker compose --env-file deploy/compose.env exec web cat /var/lib/copydesk/data/setup-code.txt
```

### "Database … needs updating"

The installed version is newer than the database. Back up, then run `quillsail upgrade` with the instance's configuration. QuillSail won't run against a database that hasn't been upgraded.

### Links in emails use the wrong address

Emails, feeds and the API build links from `[site] base_url`. Set it to the exact public `https://` address, including any path such as `/newsletter`, then restart the web and worker processes.

### Sign-in doesn't stick, or forms fail behind a proxy

When QuillSail runs behind a reverse proxy, set `[server] proxy_hops` to the number of proxies in front of it, usually 1. Without it, QuillSail can't see that the site uses HTTPS. Make sure the proxy passes the original `Host` header and the `X-Forwarded-For` and `X-Forwarded-Proto` headers. Also check that `base_url` uses `https://`.

### "site.secret_key is too short"

The secret key must be at least 32 random characters. Keep the existing key if the site is already live: changing it signs everyone out and breaks every link already sent.

## Email

### Nothing is being sent

1. **Is the worker running?** **Dashboard → System status** shows its last heartbeat. Start it with `quillsail worker`, as a service, or run `quillsail jobs run` from cron every minute.
2. **Is a real sender configured?** The `console` and `file` backends don't deliver mail. Connect a sender under **Settings → Email**.
3. **Do the jobs fail?** Run `quillsail jobs list --status failed`. Fix the cause, then run `quillsail jobs retry-failed`.

`quillsail check --send-test you@example.org --now` sends a test message straight away, without the worker.

### Messages land in spam

Ask whoever runs your domain's email to set up SPF and DKIM for the sending address, and use an address on that domain. Avoid importing people who didn't ask for your newsletter. Many providers expect a mailing address in the footer; set it under **Settings → Newsletter**.

### Gmail or Outlook stopped sending

The connected account may have revoked access, or its password or the app's secret may have changed. Reconnect it under **Settings → Email**. Provider sign-in failures don't count against your subscribers.

### An issue seems stuck while sending

Make sure the worker is running; it resumes stalled sends automatically. The delivery report shows what's waiting, sent and failed.

## Design

### Custom CSS broke the dashboard

Open `/dashboard/settings/appearance?dashboard_style=default` under your site's address. That request uses the default dashboard styles, so you can fix the CSS and save. Nothing is deleted.

## Updates

### A server update failed

Failures before the update is committed restore the old version and data automatically. Check what happened with:

```sh
sudo quillsail update status
```

If the update was interrupted, for example by a power cut, run `sudo quillsail update --resume`. To go back to the previous version after a committed update, see the rollback warning in [server updates](server-updates.md#backup-and-recovery).

### "Another update check is running"

Only one desktop update check runs at a time. Wait for it to finish, then try again.

## Still stuck?

Search the [issues on GitHub](https://github.com/DoobaDigital/QuillSail/issues), or open a new one with your QuillSail version (`quillsail --version`), your operating system and how you installed it, what you expected, and what happened, with logs. Remove addresses, tokens and personal data first.
