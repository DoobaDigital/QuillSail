# Security

This page explains how QuillSail protects a publication and its readers, and what you need to do when you run it. To report a vulnerability, follow the [security policy](../SECURITY.md); never post details in a public issue.

QuillSail is beta software. It has a large automated test suite, including adversarial permission tests, and an internal [review](review.md), but it hasn't had an independent security audit.

## Accounts and sign-in

- Passwords are stored as salted hashes using Werkzeug's password hashing. They must be at least 10 characters; very common passwords are refused.
- Repeated failed sign-ins from one place are paused for 15 minutes. Rate limits are stored in the database, so they hold across every web process.
- Session cookies are `HttpOnly` and `SameSite=Lax`, and `Secure` when the site uses HTTPS. **Remember me** keeps a session for up to 30 days.
- Changing a password, or an administrator setting one with `quillsail user set-password`, signs the account out everywhere else.
- Accounts get only the **Everyone** permissions until their email address is confirmed.
- Blocking an account signs it out immediately.

## Links sent by email

Confirmation and reset links are signed with the instance's secret key and expire:

| Link | Lasts |
| --- | --- |
| Reset a password | 2 hours |
| Confirm a new email address | 2 days |
| Confirm an account | 3 days |
| Confirm a business inquiry | 3 days |
| Confirm a newsletter subscription | 7 days |
| Accept an invitation | 7 days |

Email-change links work once, and only for the address they were sent about. Newsletter preference links are long random tokens that work like passwords for that subscription, so subscribers should keep them private. Pages that show them are never cached.

## Permissions

Every page and action checks permissions on the server. People can grant only the permissions they hold themselves, and only administrators can make someone an administrator; see [groups and permissions](groups-and-permissions.md#nobody-can-give-themselves-more-power).

Some content is private by design:

- Drafts are visible only to their writers and co-authors, even to administrators.
- Internal editorial notes are visible only to people who can review submissions.
- The text of members-only and group-only articles is never used for public summaries, search results, feeds or public issue pages.
- Private issue previews exclude restricted articles and group-only items, and are never listed or indexed.

## The website

- **Forms**: every form that changes something carries a CSRF token, checked on the server. The few endpoints that skip it, such as the public sign-up API and one-click unsubscribe, don't rely on cookies.
- **Content Security Policy**: pages allow scripts and styles only from the site itself, or inline code carrying a fresh random value for each request. Templates and extensions use the `csp_nonce()` helper for any inline code.
- **Headers**: responses include `X-Content-Type-Options: nosniff`, a referrer policy and a permissions policy. Pages can't be framed by other sites. Pages for signed-in people, and pages that show private tokens, are marked `private, no-store`.
- **Markdown**: raw HTML in Markdown is never rendered, and all rendered HTML is sanitized again before it's shown.
- **Typed HTML**: pieces written in HTML, or imported as Markdown with HTML, go through a stricter sanitizer. It removes scripts, styles, forms, event attributes and `style=`, keeps only the classes Markdown itself produces, makes checkboxes inert, and allows frames only for YouTube and Vimeo, sandboxed. The Content Security Policy lists only those two hosts in `frame-src`.
- **Visual editor**: pasted content is reduced to what the editor's document model can hold, and what's saved is Markdown, which goes through the same rendering as everything else.
- **Blog imports**: Jekyll, Liquid and plugins are never run, and YAML is read with a safe loader. Zip files with unsafe paths, symbolic links or too much content are rejected whole, and images are re-encoded like any upload.
- **Uploads**: every image is decoded and re-saved, which strips metadata such as GPS location, and very large or long animated images are refused. Uploaded files are public once someone knows their address.

## Secrets

- `copydesk.toml` contains the secret key and may contain database and mail passwords. `quillsail init` writes it readable only by its owner; keep it that way.
- Email passwords, OAuth client secrets and OAuth tokens saved in the dashboard are encrypted with a key derived from the instance's secret key. Back up the secret key with the database: without it, saved email connections can't be decrypted and must be reconnected.
- Changing the secret key signs everyone out and invalidates every link already emailed.
- Gmail and Outlook connections use OAuth with PKCE. The sign-in state works once, expires after ten minutes, and is tied to the browser and administrator who started it. Tokens and codes never appear in pages or the activity log.

## Email

Sign-ups are double opt-in. Newsletters include an unsubscribe link and a one-click unsubscribe header that mail apps understand. QuillSail adds no tracking pixels and doesn't rewrite links to track clicks.

## Updates

Desktop and server updates are verified with [The Update Framework](desktop-updates.md) against keys shipped with the app. Metadata must be signed, current and newer than what the app has seen, and each download must match its signed size and SHA-256 checksum. There's no unsigned fallback.

The website's [terminal installer](install-script.md) only offers downloads listed in that signed feed, and checks each file before installing it.

## The desktop app

The desktop app listens only on `127.0.0.1` and refuses requests from other computers or with an unexpected host name. Its first-time setup page is unlocked by a short-lived, single-use ticket from the launcher; the ticket never signs anyone in by itself. Server environment variables are ignored, so a local command can't point at a production database by accident.

## Extensions and themes

Extensions are Python code, and template themes are server-side templates. Both run with full access to the application, its data and the network. Install only extensions and themes you've reviewed and trust, and review updates to them too.

## Running a server safely

- [ ] Serve the site only over HTTPS, with `base_url` set to its exact `https://` address.
- [ ] Set `[server] proxy_hops` to the number of trusted proxies in front of QuillSail, and no more.
- [ ] Keep `debug = false`.
- [ ] Run web and worker processes as a dedicated, unprivileged account, and keep the instance folder private to it.
- [ ] Keep the database reachable only from the application.
- [ ] Protect backups and exports: they contain personal data, password hashes and tokens.
- [ ] Apply updates promptly with `sudo quillsail update`, and keep the operating system and Python current.
- [ ] Use a dedicated sending account or domain, with SPF and DKIM set up.
