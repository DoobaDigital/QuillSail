# Configuration

QuillSail reads the explicit `--config` path, then `COPYDESK_CONFIG`, then `./copydesk.toml`, then `/etc/copydesk/copydesk.toml`. Relative paths resolve beside the selected file. Environment values override TOML. Restart both web and worker processes after changes.

`quillsail init` writes a commented configuration. The packaged `src/copydesk/config_template.toml` is the complete starting reference.

| Section | Settings |
| --- | --- |
| site | `base_url`, `secret_key`, `data_dir`, `debug` |
| database | SQLAlchemy `url` |
| mail | `backend`, `host`, `port`, `security`, `username`, `password`, `timeout`, `from_email`, `rate_per_minute`, `file_dir` |
| uploads | `dir`, `max_size_mb`, `max_import_mb` |
| jobs | `run_in_web` (prefer a separate worker in production) |
| server | `proxy_hops` |
| extensions | `enabled`, optional `dir`, extension-specific option tables |
| themes | `dir` |
| logging | `level` |

Environment overrides: `COPYDESK_BASE_URL`, `COPYDESK_SECRET_KEY`, `COPYDESK_DATA_DIR`, `COPYDESK_DEBUG`, `COPYDESK_DATABASE_URL`, `COPYDESK_MAIL_BACKEND`, `COPYDESK_MAIL_HOST`, `COPYDESK_MAIL_PORT`, `COPYDESK_MAIL_SECURITY`, `COPYDESK_MAIL_USERNAME`, `COPYDESK_MAIL_PASSWORD`, `COPYDESK_MAIL_FROM_EMAIL`, `COPYDESK_MAIL_RATE_PER_MINUTE`, `COPYDESK_UPLOADS_DIR`, `COPYDESK_UPLOADS_MAX_SIZE_MB`, `COPYDESK_JOBS_RUN_IN_WEB`, `COPYDESK_PROXY_HOPS`, `COPYDESK_EXTENSIONS` (comma-separated names), and `COPYDESK_LOG_LEVEL`.

Use a stable random secret of at least 32 characters. Changing it invalidates sessions and signed email links. Keep `debug = false` on public servers. Publication settings such as name, description, timezone, registration rules, colors, theme, and newsletter subject format are edited in the dashboard and stored in the database.


Gmail and Outlook app registrations can be supplied under `[oauth]` or through the `COPYDESK_GOOGLE_CLIENT_ID`, `COPYDESK_GOOGLE_CLIENT_SECRET`, `COPYDESK_MICROSOFT_CLIENT_ID`, `COPYDESK_MICROSOFT_CLIENT_SECRET`, and `COPYDESK_MICROSOFT_TENANT` environment overrides. See [email connectors](email-connectors.md).

Fresh Gmail connections use the shared website broker by default. `COPYDESK_GOOGLE_METADATA_URL` or `oauth.google_metadata_url` overrides its HTTPS discovery URL; an empty value disables discovery. The confidential Google Web client secret stays on the broker and each publication encrypts its own tokens locally. Shared activation and the permitted account audience depend on Google's publishing and sensitive-scope verification status.

An administrator's saved email connection takes precedence over `[mail]` and is read by both web and worker processes without a restart. Disconnecting it resumes the server's `[mail]` configuration. Provider app credentials saved in the dashboard take precedence over their server defaults. Dashboard secrets are encrypted with a key derived from `site.secret_key`; preserve that key when restoring the database.

Named local publications are selected with `quillsail --instance NAME COMMAND`. The desktop app and `quillsail instance` commands share their private registry and keep each publication's files separate. Named instance commands ignore server environment overrides. See [multiple local publications](desktop.md#multiple-publications). Inside application code, database engines and sessions resolve through the active Flask application context; creating another application never rebinds an existing publication's database.

## Hosting and launch controls

The Domain and Launch dashboard pages are described in [Domains and launch](hosting.md). Server `site.base_url` remains the source of truth. Desktop can save its public address separately from its local dashboard listener. OAuth uses public client metadata under `[oauth]` and a separately deployed confirmation relay; provider credentials are encrypted in the database with the instance secret key. Preserve that key when backing up or moving a publication.
