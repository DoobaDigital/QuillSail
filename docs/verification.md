# Verification record

QuillSail is beta software. These are development checks, not an independent security audit. Private deployment addresses, access details and operations records are excluded from the public repository.

## 1.14.1 Beta — connector logos and local Gmail guidance

Locally bundled official Gmail, Outlook and Cloudflare product assets replace email-card initials and appear alongside existing connector labels. A shared Jinja macro marks the images decorative and preserves the buttons' accessible names. A white backing preserves provider colors in both themes. Browser checks confirmed all assets loaded locally, light/dark appearance, Cloudflare sign-in/API-token backup and no horizontal overflow at 390px. No permissions, OAuth scopes or schema changed in this UI patch.

Application tests: 569 passed, 3 skipped (11 external premailer warnings). Website tests: 183 passed, 1 skipped. Ruff and generated references passed. Wheel/sdist metadata and public boundaries passed; a clean wheel installation exercised migrations, setup, subpath routing and assets. Database, Docker and native desktop checks run in CI; server databases, Docker and cross-platform builds are unavailable locally.

Two Intel Mac release attempts passed signing, application checks and notarization acceptance but failed while fetching Apple's ticket with Error 68 / network error -1005. GitHub's runner maintainers identified an HTTP/3 transport regression. Manual Intel jobs now use their documented UDP-443 block to obtain the ticket over HTTPS/TCP. The workaround is limited to the disposable CI runner; all signing, notarization, staple, validation and publisher requirements remain in place. The complete native release is rebuilt from the merged workflow change before publication.

The next release attempt passed on Intel, Windows and Linux. The Apple Silicon job notarized and stapled the app, but its DMG submission produced no response for 45 minutes and the job failed; Intel's DMG was notarized normally during the same period. Notarization now uploads without blocking, limits each upload to 10 minutes and tries it three times, then polls the same submission with 2-minute status checks until a 30-minute deadline. Desktop jobs allow 75 minutes and log build progress unbuffered. New signing tests cover a stalled upload and status check, an upload that never arrives, a rejected submission with Apple's log, and the deadline. They fail on the previous code. Accepted notarization and stapling remain required. Application suite with these tests: 573 passed, 3 skipped; website suite 183 passed, 1 skipped; Ruff, references and public-file boundaries passed.

Separately, the maintained Gmail service was activated after operator-approved Google configuration and privacy publication. Live discovery and fresh domainless HTTP server/desktop PKCE preparation were checked using disposable local publications. Google's callback remained HTTPS and local return addresses used HTTP loopback, with independent verifiers and no per-publication client secret. Google production publishing does not establish sensitive-scope verification; unverified warnings, user caps and organization policies remain provider-controlled. No user consent, real mailbox token or live email was used in these checks.

## 1.14.0 Beta — shared Outlook sign-in

Shared Outlook discovery and the confidential website broker use synthetic Microsoft registrations and mocked grants. Regression coverage exercises fresh server/desktop PKCE, fixed HTTPS callbacks, browser binding, encrypted client snapshots and tokens, proof-bound refresh/rotation, sender replacement races, malformed metadata, authority injection, cross-provider/tenant proof rejection, minimal scope aliases and rejected inbox permissions. Custom registrations and SMTP remain supported. Gmail and Cloudflare confirmation salts and browser state remain compatible; Outlook uses independent state and proof keys. No schema change is needed.

Website suite: 183 passed, 1 skipped; Ruff and reference generation passed. Wheel/sdist boundaries, metadata and a clean package installation passed. Application suite: 569 passed, 3 skipped (11 external premailer deprecation warnings). Database, container and all native desktop checks run in pull-request CI; Docker and server databases are unavailable locally. Private Microsoft credentials are deployed separately, never committed. Live Microsoft authorization and delivery are not established by mocked tests; the registration's callback, account types, publisher status and each tenant's consent policy determine availability. No live email is sent during validation.

## 1.13.1 Beta — launcher fits without scrolling

The desktop launcher now sizes itself from its content's height at the window's actual width and the real title bar height, and grows when content is added. On macOS with a 1440×900 display (812 px usable), the real launcher opened at 708 px with no scrolling, down from a 772 px window holding 777 px of content. With a public address it grew to 734 px and stayed on screen. A new offscreen regression test fails on the previous code and passes now. No schema change is needed.

Download, release, issue, edit and desktop update links now use `DoobaDigital/QuillSail`. GitHub's API reports it as the repository's current name, and the old `Dooba-Digital-LLC` address redirects to it.

Local validation: application suite 548 passed, 3 skipped; website suite 154 passed, 1 skipped. Ruff, generated references, public-file boundary checks, wheel/sdist builds with `twine check --strict`, and a clean wheel installation (migrations, setup, subpath routing and assets) passed. The native builds, notarization, PostgreSQL/MariaDB and Docker checks run in GitHub Actions.

## 1.13.0 Beta — shared Gmail registration

The website holds the confidential Google Web client secret; fresh publications discover public app metadata and prepare browser-bound PKCE authorization through an HTTPS confirmation relay. Code exchange and refresh use a restricted backend endpoint with token-bound renewal proofs. Tokens remain encrypted on each publication and email content is sent directly to Google. Custom Gmail/Outlook registrations and SMTP remain supported; no schema migration is required.

Regression coverage uses synthetic accounts and mocked Google APIs. It checks public metadata allowlists, secret omission, fixed token/callback endpoints, scope restrictions, proof binding and rotation, rate/body limits, browser-form rejection, CSRF and provider isolation, browser state and single-use flows, callback snapshots, local desktop callbacks, encrypted storage and renewal failures. No real email is sent. Provider activation is gated: at setup the existing Google application was in Testing, and public availability remains dependent on callback/domain configuration and Google's publishing and sensitive-scope review. Credentials alone do not establish public approval.

Local validation: application suite 547 passed, 3 skipped; website suite 154 passed, 1 skipped. Ruff and generated-reference checks passed. Wheel/sdist metadata and release boundaries passed, and a clean wheel installation exercised migrations, setup, subpath routing and assets. Website tests verify the disabled-by-default broker and operator-reviewed privacy page. PostgreSQL/MariaDB, Docker and all native desktop platforms are checked by CI; Docker and server databases are unavailable locally.

## 1.12.1 Beta — shared Cloudflare registration

Fresh publications use a shared HTTPS discovery document instead of requiring OAuth app setup. Regression coverage exercises desktop/server PKCE, browser state, client snapshots across hosted changes, encrypted per-instance credentials, explicit overrides and resetting to shared defaults, rejected metadata/secrets, bounded downloads, redirect rejection and temporary outages. Website coverage verifies the public allowlist, missing setup, HTTPS and environment configuration. No schema change is needed. Production activation also requires Cloudflare's verified domain and public client visibility; tests use synthetic registrations and mocked endpoints.

Local validation: application suite 529 passed, 3 skipped; website suite 133 passed, 1 skipped. Ruff, generated references, wheel/sdist metadata and release-boundary checks passed; a clean wheel installation exercised migrations, setup, subpath routing and assets. The native builds, PostgreSQL/MariaDB and Docker checks run in GitHub Actions. Docker and server databases are unavailable locally.

## 1.12.0 Beta — hosting and domains, 2026-10-30

Issue #5 adds optional domain connection, launching-soon mode, Cloudflare OAuth with an HTTPS confirmation relay, and an API-token backup. Release preparation follows the contributor-branch, pull-request, rebase, CI and rebase-and-merge workflow. Published desktop artifacts are built from the merged commit, independently of local development builds.

Local validation: application suite 512 passed, 3 skipped; website suite 128 passed, 1 skipped; five Node Worker tests passed. Ruff and generated-reference checks passed. Chrome previews at a 390px viewport showed no horizontal overflow on Domain, Launch or the launching-soon page, with labeled form fields. Wheel and source archive metadata and release-boundary checks passed; a clean wheel installation exercised migration, blog setup, subpath routing and assets. An ad-hoc-signed Apple Silicon build passed browser setup/restart, GUI lifecycle, updater, archive extraction and graphical-installer checks.

Hosting coverage includes upgrade compatibility, launch permission/CSRF checks and hooks, path-prefix behavior, local/public listener separation, authoritative DNS agreement, DNS-rebinding rejection, SPF preservation and lookup limits, DKIM parsing, conditional undo, encrypted credentials, mocked provisioning retries and conflicts, browser-bound PKCE, relay confirmation/CSRF, offline request limits, transactional replay, fail-open capability rejection, a fake tunnel's restart/shutdown, checksum rejection and opt-in sleep inhibition. Premailer emits dependency deprecation warnings under Python 3.13.

Live OAuth validation on a separate local publication: browser authorization with PKCE, the deployed HTTPS confirmation relay, encrypted access/refresh storage, automatic refresh, zone listing and publisher-verification TXT creation succeeded without a manually supplied API token. The OAuth picker’s tunnel permission identifier is `argotunnel.write`. After explicit approval, a public preview tunnel was provisioned through OAuth and verified online. Its HTTPS home and install-specific health endpoint returned 200; public dashboard, sign-in, setup and API endpoints returned 404. The local authenticated dashboard remained available. An initial local negative DNS cache cleared while the authoritative nameservers already held the new record. Cloudflare publisher verification remains asynchronous. The disposable publication was subsequently deleted by its owner; these results describe the completed test, not an ongoing hosted preview.

PostgreSQL/MariaDB, Docker smoke tests, all four native desktop builds, Developer ID notarization and signed-feed publication are checked by the GitHub workflows before merge/publication as applicable; Docker and server databases are unavailable locally. The current published Cloudflare route schema does not expose the requested quota fail-open property; offline fallback activation therefore requires explicit API confirmation and otherwise removes the candidate route. Full token-template permission prefill also awaits confirmation of Cloudflare's tunnel permission key; the API-token path currently documents manual permission selection. Domain Connect remains deferred as designed.

## Application validation

| Version | SQLite | PostgreSQL | Scope |
| --- | --- | --- | --- |
| 1.11.2 | Application suite passed locally | PostgreSQL and MariaDB passed PR CI | Mac Developer ID signing and notarization: a manual Desktop bundles run on the release branch signed every binary with the hardened runtime and a secure timestamp, and Apple notarized the app and DMG for Apple Silicon and Intel. Stapled tickets validated; the installed DMG app, updater replacement, and setup/restart and GUI checks passed under the hardened runtime with no entitlements. Signing unit tests (Mach-O detection, inside-out order, ticket-service retries) and the publish guard against un-notarized Mac builds passed. Website, Windows and Linux builds passed |
| 1.11.1 | Application suite passed locally | PostgreSQL and MariaDB passed PR CI | Graphical installers: native Apple Silicon DMG verified locally; all four native builds passed PR #15, including install, launch, archive replacement and removal. Website, Python 3.11–3.14, packaging and container CI passed. Release-version checks and publication are tracked in #16 |
| 1.11.0 | 431 passed, 3 skipped | Not rerun locally | Full browser transfer across separate local publications, sign-in restoration, creator blurbs, three per-issue text choices, attribution, CSRF and permissions, restricted-body protection, relative images/links and schema upgrade preservation. Six browser-script cases passed in Node; the handoff and composer were checked in Chrome, including a 390px layout. Website: 115 passed, 1 skipped. Ruff, generated references, wheel/sdist metadata, release boundaries and clean wheel installation passed. Database, Docker and native desktop builds are checked by GitHub Actions |
| 1.10.3 | 421 passed, 3 skipped | Not rerun locally | Public website hero layouts, canonical metadata, structured data, breadcrumbs, indexing rules and mobile download overflow. Website: 115 passed, 1 skipped; public crawl checked 43 canonical pages. CI workflows passed actionlint; package metadata, clean wheel installation and server-update recovery checks passed locally. Database, container and native platform checks remain covered by GitHub Actions |
| 1.10.2 | 421 passed, 3 skipped | Not rerun locally | Deleting Default publication, stopping owned runtimes and workers before deletion, cancellation and stop-failure preservation, persistent empty instance lists, and creating, registering, refreshing or checking for updates from an empty launcher. Real launcher checked at narrow width with disposable data. Website checks: 82 passed, 1 skipped |
| 1.10.1 | 409 passed, 3 skipped | Not rerun locally | Desktop and CLI deletion of stopped named instances, explicit permanent file deletion, confirmation, running-instance locks, missing or replaced folder checks, and launcher controls. Website checks: 82 passed, 1 skipped; contributor design proposals are excluded from published documentation |
| 1.10.0 | 401 passed, 3 skipped | Not rerun locally | Desktop launcher restyle with light, dark and automatic appearance, readable dialogs, the bundled Amiri Bold heading font, first-time setup that follows the launcher's appearance, background running after the window closes, and quitting from the button, menus, tray and `quillsail quit`. Launcher and setup rendered on macOS (Qt and headless Chrome, including dark mode, form errors and a 390px viewport); close-to-background and quit checked on the native macOS platform |
| 1.9.1 (unreleased) | 373 passed, 3 skipped | Not rerun locally | Stable Linux server command installation, sudo PATH checks, conflict protection, bootstrap ordering, registration rollback, and command continuity across real disposable updates and recovery |
| 1.9.0 | 357 passed, 3 skipped | Not rerun locally | Managed server updates: release preparation, maintenance gate, instance/database snapshots, migration, web/worker validation, failure recovery, resume, manual rollback and retry, privileged-release and working-directory protections. Local server update smoke test passed on macOS; Compose updates and PostgreSQL/MariaDB backup restoration run in CI |
| 1.5.0 | 234 passed, 2 skipped | Not rerun | Publication design presets, permission/CSRF checks, isolated unsaved previews, logo variants/transparency/aspect ratio, design import/export boundaries, offline CSS inlining and existing workflows |
| 1.3.0 | 153 passed, 2 skipped | 154 passed, 1 skipped | Blog/newsletter modes, direct publishing permissions, same-site post reuse, attributed external submissions, no remote source fetching, editorial review, subscriptions, competitions, backup/restore |
| 1.2.0 | 134 passed, 2 skipped | 135 passed, 1 skipped | Competition hosting, moderation, assigned judges, concurrent reader voting, deadlines, ties and immutable results |
| 1.1.0 | 122 passed, 2 skipped | 123 passed, 1 skipped | Encrypted sender settings, OAuth state/PKCE, mocked provider APIs, refresh and switching |

The SQLite-only skip needs a disposable server database. The shared SMTP skip is an inapplicable TLS/authentication test on the plain loopback transport. A prior 1.0.0 validation also exercised MariaDB, Python 3.11–3.14, actual SMTP/TLS, and database backup/restore. Newer behavior was not independently rerun against MariaDB or every Python runtime; CI is configured to cover those combinations. The 1.5.0 check used Python 3.13 and SQLite, plus a clean wheel installation and browser checks of the editor, website/email previews and a narrow viewport. Received-email appearance in actual Gmail, Outlook and other clients still needs per-installation testing; browser email previews cannot establish client compatibility.

A private Linux reference installation was checked behind a reverse proxy with Gunicorn and a separate worker. Checks covered HTTPS/subpath routing, assets, secure cookies, CSRF, private drafts and revision history, issue composition/previews, competition draft isolation, host settings, and migration upgrades. Existing SMTP authenticated and a previously requested test message was confirmed in its recipient's inbox. These observations do not establish deliverability for other installations.

The Google authorization flow reached the provider's real sign-in page after app configuration. Account consent, token exchange and actual Gmail delivery remain unverified. Microsoft app registration is deferred. Automated Gmail/Outlook send and refresh tests mock provider HTTP responses; they are not live provider-delivery tests.

[Machine-readable application results](verification-results.json) retain test counts and sanitized deployment checks.

## Reproduce

```sh
python -m pip install -e '.[dev,integration]'
pytest
ruff check src tests scripts deploy
python -m build
python -m twine check --strict dist/*
python scripts/check_public_files.py
python scripts/check_public_files.py --archive dist/*.whl
python scripts/check_public_files.py --archive dist/*.tar.gz
python scripts/package_smoke.py dist/*.whl
python scripts/server_update_smoke.py dist/*.whl
```

The server update smoke test installs two synthetic versions of the built wheel into disposable virtual environments, runs real Gunicorn and worker processes, and exercises an update, a manual rollback and recovery from a failed health check. It replaces only systemd and trusts the interpreter that runs it, because development and CI interpreters live in shared tool caches that a production updater refuses.

The default suite uses disposable SQLite databases and synthetic accounts. Real loopback SMTP/TLS tests need the integration dependencies. To use a database server, also install the relevant driver and set `COPYDESK_TEST_DATABASE_URL` with a role permitted to create and drop test databases. Fixtures create randomly named `copydesk_test_*` databases and remove only those databases. Use a dedicated test server.

```sh
pip install -e '.[dev,integration,postgres]'
COPYDESK_TEST_DATABASE_URL='postgresql+psycopg://test_user:TEST_PASSWORD@127.0.0.1:5432/postgres' pytest
```

With Docker available, build an isolated image and run the container checks:

```sh
docker build -t copydesk:ci .
bash scripts/container_smoke.sh
```

The smoke script uses a separate Compose project and temporary volume, checks startup, web/worker health, non-root execution, path prefixes and persistence, then removes its own test resources. Never point it at an existing publication.

## Public repository preparation

Local preparation on October 26, 2026 passed **156 tests, 2 skipped** on Python 3.13/SQLite, including first-run bootstrap, private configuration permissions, stable secrets and refusal to start with an unmigrated database. The container entrypoint was additionally exercised outside Docker with real Gunicorn and worker processes, HTTP subpath routing, browser administrator setup, blog rendering and both health checks. A clean virtual environment installed the built wheel and passed migrations, setup, static-asset and subpath checks. Wheel/sdist metadata and public-file boundary checks passed. Staged files were also compared against known local deployment credentials and provider registration values without exposing those values.

The repository includes Python/database CI, package validation and a Docker smoke job. Release automation validates the version tag, attaches the wheel/sdist and publishes a versioned GitHub Container Registry image when a maintainer publishes a GitHub release. These workflows have not been dispatched to GitHub as part of local preparation. Docker is not installed in the preparation environment, so an actual image build/container run remains to be verified by CI or a Docker-equipped host.

## Limits

Long-term operations, a full capacity benchmark, Oracle MySQL, other database/runtime combinations, externally delivered webhooks, and provider-specific account policies remain outside the verified scope. Restore and inbox checks should be repeated for each deployment. No independent security audit has been performed.
