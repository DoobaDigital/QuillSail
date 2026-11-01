# Changelog

## 1.15.0 — Beta

- Make QuillSail's own style the default for new publications on the website, dashboard and newsletter emails, following the brand guidelines: ink on paper, hairline rules, square corners with no shadows, Amiri headings, a book serif for body text, Avenir-style labels and buttons, and the logo purple for primary buttons, keyboard focus, progress, selected text and form errors. Light is the default; dark mode softens white to 86% for text, 40% for rules and 14% for fills. Add it as the QuillSail starting style.
- Add a **Dashboard** designer under Settings → Appearance, so the dashboard can be customized like the publication: starting styles, typefaces, text size, colors, color mode, spacing, corners, sidebar logo display, dashboard-only CSS, a desktop/mobile preview, and its own design files. It starts in QuillSail's style; **Match the publication** is still available. Saving either design never changes the other. The dashboard always shows the publication's logos and icon.
- Put **Change the appearance of your dashboard and newsletter** (or blog) first in Getting started, with a **Don't want to** option that completes it without changing anything.
- Upgrading moves installations still on the untouched defaults to the QuillSail style. Installations whose look had been changed keep their design, and their dashboard keeps matching the publication (migration `0008`). Logos and homepage text are never changed.
- Fix navigation counts that were invisible on dashboards using a publication design, and stop Getting started status icons from shrinking beside long labels.
- Make the **Menu** buttons work on phones (#34). On the publication site, Menu now shows and hides the links. The dashboard drawer has a **Close menu** button where Menu was. Close menu, the dimmed area, Escape, Menu itself and tabbing out of the drawer all close it, reset `aria-expanded` and return focus. Without JavaScript, both pages still show the full navigation.

## 1.14.1 — Beta

- Add locally bundled Gmail, Outlook and Cloudflare logos to connector buttons, including Cloudflare reconnect and API-token backup. Replace email-card initials with provider marks and retain visible accessible labels.
- Preserve each provider's colors on a white backing in light and dark themes. Logo display makes no third-party image requests.
- Clarify that desktop Gmail connects through the hosted HTTPS callback and local HTTP loopback, with no public-domain prerequisite; shared-service availability is a separate maintainer setting.
- Route Intel Mac release ticket downloads over HTTPS/TCP to work around GitHub's HTTP/3 runner failure. Mac releases still require signing, notarization, stapling and validation.
- Retry stalled Apple notarization uploads and status checks on the same submission, with a 30-minute limit for each file, so one unanswered connection no longer uses up the whole Mac release job.

## 1.14.0 — Beta

- Add shared Outlook/Microsoft 365 sign-in for desktop and server publications. Keep the confidential Microsoft Web client secret on the website backend and discover only public app metadata, so users connect by signing in without registering an app.
- Use PKCE, a confirmed HTTPS callback, separate proof-bound token renewal and encrypted per-publication credentials. Send messages directly to Microsoft Graph with delegated Mail.Send and User.Read; reject inbox permissions and arbitrary authorities.
- Preserve custom Outlook apps, SMTP backup, existing Gmail/Cloudflare sign-ins and sender-switching protections. Activation depends on the maintained Microsoft callback, supported account types and organization consent rules.

## 1.13.1 — Beta

- Show everything in the desktop launcher without scrolling. The window now sizes itself to its content using the real title bar height, and grows when a public address, update progress or a longer message adds lines, as far as the screen allows.
- Put **Delete instance…** beside the instance selector, and **Open public site** beside **Open dashboard**. Hide the public address line until a publication has one.
- Point download, release, issue and update links at the renamed `DoobaDigital` GitHub organization. The old address still redirects.

## 1.13.0 — Beta

- Add shared Gmail sign-in for desktop and server publications. The website backend keeps the confidential Google client secret; publications discover public metadata and use a confirmed HTTPS callback with PKCE instead of asking each user to register an app.
- Exchange and renew Gmail authorization through the backend with token-bound refresh proofs. Store each publication's tokens encrypted locally, send messages directly to Google, reject inbox-reading scopes and keep SMTP and custom app registrations available.
- Gate activation on maintainer configuration and Google publishing/verification requirements. Testing-mode Google applications remain limited to their approved test users; shared credentials do not bypass that restriction.

## 1.12.1 — Beta

- Configure the shared Cloudflare OAuth application once on the website backend. Fresh desktop and server publications discover the public client ID, scopes and HTTPS relay automatically and show Sign in with Cloudflare without asking users to register an app.
- Keep PKCE verifiers, access tokens and refresh tokens on each instance. Bound and validate discovery responses, preserve in-flight client details, and retain custom-client overrides and the API-token backup.

## 1.12.0 — Beta

- Add optional public domains, separate desktop public listeners, launching-soon pages and administrator launch controls. Preserve existing live sites and keep desktop setup, sign-in, account, dashboard and API endpoints private.
- Add background authoritative DNS and HTTPS checks, encrypted Cloudflare API-token and public-client PKCE connections, resumable tunnels, per-instance launcher status, conditional DNS undo and safe disconnect.
- Make Cloudflare OAuth the primary connection path, with per-publication public-client setup, refresh grants and reconnect support. Keep API tokens as a backup. Add an HTTPS confirmation relay and narrowly scoped CSP rules for OAuth redirects; no client secret is distributed.
- Add manual email records, guarded SPF merging, DKIM conflict checks and preservation of existing DMARC policies. Add an opt-in Cloudflare offline launch snapshot and subscriber queue with transactional replay receipts and received-time opt-outs.
- Add portable migration 0007, mocked provider and DNS tests, fake tunnel-process checks and automated Node Worker tests. Domain Connect remains deferred.
- Keep offline fallback disabled unless Cloudflare confirms the required quota fail-open capability. OAuth clients and their HTTPS relay remain configurable public metadata; each operator registers their client before connecting.

## 1.11.2 — Beta

- Sign the Mac apps and disk images with a Developer ID and have Apple notarize them, so macOS opens downloads without a trip to Privacy & Security. Every binary is signed with the hardened runtime and a secure timestamp, and the updater archives carry the stapled ticket.
- Refuse to publish Mac builds that aren't notarized. Builds without a certificate, such as local and fork builds, stay ad-hoc signed.
- Say on the website and in the guides that the Mac apps are notarized and the Windows setup program isn't code-signed yet.

## 1.11.1 — Beta

- Offer drag-to-Applications DMGs for Apple Silicon and Intel Macs, a per-user Windows setup wizard, and a Debian/Ubuntu package with an application-menu entry.
- Prefer separately verified graphical installers on the website while preserving updater archives and terminal installer compatibility. Keep publication data separate from application installation and removal.
- Exercise native installation, launch, archive replacement, reinstallation and removal. Document installation steps and remaining platform signing/notarization limitations.

## 1.11.0 — Beta

- Transfer a published public blog article's full text to another QuillSail newsletter for review, preserving sign-in, permissions and explicit submission. Keep the receiving server from fetching arbitrary source URLs and retain manual pasting when browser transfer is unavailable.
- Let creators submit a separate newsletter blurb. Editors can choose the full article, the creator's blurb and a link, or their own custom summary in each issue's web and email versions. Preserve attribution and restricted-content safeguards.
- Resolve transferred article images and relative links against the original post. Document the issue, contributor branch, pull request, rebase, merge and requested-release workflow.

## 1.10.3 — Beta

- Refine the public website hero with a smaller headline, roomier spacing and a desktop app preview that fits laptop and desktop screens.
- Improve search metadata, social previews, canonical HTTPS addresses, structured data, documentation breadcrumbs and crawler directives. Keep documentation titles distinct and font caching consistent.
- Fix horizontal overflow on the mobile download page.
- Reduce duplicate CI runs, cache build dependencies, cancel obsolete pull-request desktop builds and start only the database needed by each integration job. Preserve native desktop lifecycle tests, package checks and macOS OpenSSL linkage checks.

## 1.10.2 — Beta

- Allow deleting Default publication and running instances owned by the launcher. After confirmation, finish background work and stop the selected instance before removing it. Keeping files remains the default.
- Show a Create or add an instance screen when the instance list is empty. Preserve the empty list across restarts, and support creating or registering a replacement publication.

## 1.10.1 — Beta

- Delete stopped named instances from the desktop launcher or `quillsail instance delete`. Keep publication files by default, or explicitly choose permanent deletion; protect running instances and the built-in Default publication.
- Store launcher logs in the instance registry folder so they remain available after deleting a publication and do not hold its files open on Windows.

## 1.10.0 — Beta

- Restyle the desktop launcher in black, white and the logo's purple, with serif headlines and body text and small-capital labels. Headlines use the bundled Amiri Bold typeface (SIL Open Font License). Design guidance for the launcher is in `assets/README.md`.
- Open the launcher in light mode by default. Choose **Dark**, or **Automatic** to follow the system appearance, under **Appearance**; the choice is remembered. The dark theme softens white text and rules to reduce glare.
- Size the launcher window to fit its content when the screen allows.
- Restyle first-time setup to match the launcher, with clearer Publication and Your account sections. Setup opened from the desktop follows the launcher's appearance; other installations show it in light mode.
- Keep publications running when the launcher window is closed. QuillSail stays in the menu bar or system tray until you quit it with the new **Quit QuillSail** button, ⌘Q, the menu bar icon, or the new `quillsail quit` command. Opening QuillSail again brings the open window forward.
- Keep text readable in launcher dialogs, such as **New instance**, when macOS uses a dark appearance.

## 1.9.2 — Beta

- Ship a trusted certificate bundle for desktop update checks and downloads, avoiding missing build-machine certificate paths while preserving HTTPS certificate and signed-release verification.
- Keep launcher controls readable when macOS uses a dark appearance.

## 1.9.1 — Beta

- Add named local instances shared by the desktop launcher and CLI. Create, register, select and run multiple publications with separate databases, files, queues, browser sessions and ports; stopping one leaves the others running. Closing or updating the launcher stops every instance it owns.
- Scope database bindings and sessions to each Flask application and context so concurrent publications cannot rebind one another's connections.

- Apply saved publication appearance to the dashboard: branding, fonts, colors, spacing, corners, template styles and custom CSS. Add a private dashboard preview with sample controls and preserve the saved default color mode.
- Add responsive top padding above the business outreach heading.
- Start newsletter subscription email fields blank for signed-in users, preserving only an address explicitly submitted during validation.
- Install a stable system-wide `quillsail` command during Linux server registration and bootstrap. Verify sudo's PATH, keep Python deployments linked through `current`, and provide `quillsail update install-command` for existing deployments.
- Allow a custom command path or explicit opt-out. Reject conflicting commands and unsafe PATH locations without overwriting files or modifying sudo policy.

## 1.9.0 — Beta

- Add complete `quillsail update` server transactions for registered versioned Python/systemd and Docker Compose installations: verify releases, prepare environments/images online, pause traffic and queued mail, back up the instance/native database, migrate, activate and validate web/worker health.
- Recover failed updates with matching code and data, resume interrupted transactions, and provide explicit rollback with a safety backup of current content. Retain protected recovery journals and backups.
- Add one-time deployment registration and a checksum-pinned bootstrap installer for older servers. Keep desktop updates available through the launcher and `quillsail update --app PATH`.
- Build and validate server wheel/source artifacts alongside all four desktop downloads, and authenticate server wheels through the same TUF release feed.

## 1.8.0 — Beta

- Check for and install desktop updates from the launcher or `quillsail update`. Choose stable or beta releases; updates require an explicit install action.
- Authenticate updates with The Update Framework, including pinned root keys, signed metadata, expiration, rollback checks and archive hashes. Release publishing signs the feed and a scheduled workflow renews its metadata.
- Stage updates outside publication data, wait for the old application to close, and replace the app using a separate native helper. Keep the previous application and restore it if replacement fails.
- Give desktop application icons a white rounded background.

## 1.7.1 — Beta

- Render the desktop launcher logo and window icon from the vector master, preserving their aspect ratio and sharp edges on Retina and other high-DPI displays.
- Generate desktop application icons from the vector artwork at full resolution.
- Close the desktop launcher cleanly after its local server and background work stop.
- Align the homepage hero left, centered or right. The default keeps newsletter homepages centered and blog homepages left-aligned.

## 1.7.0 — Beta

- Add an optional desktop launcher with automatic local server startup, browser setup, a background worker, start/stop controls, logs and a persistent publication folder. The CLI and server installations remain available.
- Authorize first-run browser setup using a short-lived, single-use local launch ticket. Preserve CSRF and normal account sign-in; isolate desktop configuration from server environment variables and block cross-origin/network access.
- Back up desktop data before schema upgrades. Add separate native builds for Apple Silicon Macs, Intel Macs, Windows x64 and Linux x64, with browser and GUI lifecycle checks. An explicit maintainer workflow can publish all four verified downloads together with checksums; ordinary builds do not publish a release.

## 1.6.0 — Beta

- Customize the homepage hero independently of the publication name: title text, a logo, or both, plus an optional subtitle and overline. Upload dedicated light/dark hero logos or reuse the publication logo, and adjust the logo width.
- Preview homepage changes privately before saving. Hero settings carry across design imports and remain in place when loading a style preset.

## 1.5.2 — Beta

- Add a `quillsail` command. Help text, documentation, the systemd worker unit and the container now use it. `copydesk` keeps working as an alias, so existing scripts, cron jobs and services need no changes.

## 1.5.1 — Beta

- Embed uploaded publication logos as related PNG image parts in outgoing email, so their display does not depend on an external image download. Preserve browser preview URLs and plain-text alternatives across SMTP, Gmail and Outlook.
- Build email logo URLs from the configured public origin when rendering behind a reverse proxy.

## 1.5.0 — Beta

- Add a publication design studio with Classic, Broadsheet, Brief, Reference and Canvas starting styles; fine controls for typography, color, masthead, reading width, spacing, story layout and email presentation.
- Upload publication, dark-background and email logos plus a publication icon. Preserve transparent palette PNGs when processing uploads.
- Preview unsaved website and newsletter designs on desktop and mobile without changing live settings, creating uploads or sending mail. Keep theme previews isolated from concurrent readers.
- Export and import portable design settings. Support custom website CSS, offline email CSS inlining and existing template theme overrides.
- Keep publication styles out of the administration interface and retain existing styling until an administrator saves a design.

## 1.4.2 — Beta

- Place the QuillSail logo after the full “Powered by QuillSail” credit in web and email footers.

## 1.4.1 — Beta

- Keep post-login return URLs inside the configured installation path, including already signed-in visits and links to nested dashboard pages. Preserve query strings and fragments, avoid duplicate prefixes, and reject unsafe return paths.
- Integrate the supplied purple QuillSail logo into setup, dashboard branding and icons, public credits, email footers, and the repository readme. Use a white rendering on dark web surfaces while preserving publication branding.

## 1.4.0 — Beta

- Rename product branding to **QuillSail** across the interface, email copy, command output, and documentation. Existing `copydesk` commands, configuration names, and integration identifiers remain compatible.
- Share expiring, revocable private draft previews without accounts. Links stay out of archives and feeds; restricted articles and group-only blocks are excluded.
- Offer an opt-in business outreach form with email confirmation, a private staff inbox, follow-up notes, and reviewed opportunity-to-article handoff.

## 1.3.0 — Beta

- Choose Newsletter, Blog, or Blog + newsletter during setup or in General settings.
- Publish blog posts directly with publisher permission, and reuse posts in draft newsletter issues.
- Offer public blog posts to another QuillSail publication through its editorial workflow, retaining source credit.

## 1.2.0 — Beta

- Host competitions with moderated text/project entries, assigned judges, reader voting, deadlines and published results.

## 1.1.0 — Beta

- Connect Gmail or Outlook through OAuth after one-time app registration.
- Manage encrypted SMTP settings or import a configuration file from the dashboard.

## 1.0.0 — Beta

- Initial newsletter CMS with editorial review, reader groups, subscriptions, issue composition, themes, extensions and background email delivery.

See [verification](docs/verification.md) for the tested scope and remaining limits. Deployment and release-automation files are being prepared for the initial public repository; no public package or container registry publication is implied by these entries.
