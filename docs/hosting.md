# Connect a domain and launch

Hosting is optional. Existing publications stay live after upgrading. The desktop dashboard always stays on your computer, even when readers use a public domain. For an always-running publication, use a [server installation](installation.md).

The desktop public website supports reading posts and issues, searching, browsing sections and tags, following feeds, and email subscriptions. Sign-in, accounts, writing and competitions are available only at the local desktop address, so public navigation omits them. Open the dashboard from the desktop app to sign in and publish. Use a server installation when readers need accounts, community submissions or competitions on your public domain.

## Choose how to host

Open **Domain** in the dashboard. Administrators can choose Cloudflare or another host. First-time browser setup offers the same choices, or **Not now, keep it on this computer**. Newly connected publications can start with a launching-soon page; existing installations do not change automatically.

A domain needs a running origin or a tunnel. Adding DNS records by itself does not make a computer reachable. A worker must be running for hosting checks and changes, just as for queued email.

## Cloudflare

Use a domain with active, full Cloudflare nameserver setup. Pending domains show their nameserver instructions. CNAME-only zones are not supported. The default subdomain is `news`; leave it blank to use the root domain. QuillSail stops if another DNS record already uses that name.

### API token backup

Create an API token in Cloudflare with **Zone Read**, **DNS Edit**, and **Cloudflare Tunnel Edit**, scoped to the account and domain you want to connect. Paste it into **Domain**. QuillSail verifies it in the background and encrypts it with your instance secret key. Do not put tokens in a command line, issue, screenshot or log.

After choosing a domain, a job creates a remotely managed tunnel, sets its origin and catch-all 404 route, and creates a proxied CNAME. Completed steps are saved so retrying does not create duplicate resources. Only DNS records recorded as managed by this installation are eligible for automatic undo.

On desktop, `cloudflared` is downloaded on demand from a pinned official release. Its SHA-256 digest is checked before extraction or execution. The token is passed through the process environment, and subprocess output is discarded. The launcher supervises one process per instance and stops it when that instance stops. The public listener binds only to loopback and rejects setup, sign-in, account, dashboard and API requests.

On a server, the tunnel origin defaults to `http://127.0.0.1:8000`. Set the public `site.base_url` in the configuration and restart the web and worker services. Run `quillsail --config /path/to/copydesk.toml tunnel run` under a process supervisor; [the example unit](../deploy/systemd/quillsail-tunnel.service) needs paths and the service account adjusted for your installation. Keep the origin private and configure trusted proxies as described in [configuration](configuration.md).

### Cloudflare OAuth

Cloudflare sign-in is the primary connection method. API tokens remain an optional backup under **Use an API token instead (backup)**. OAuth uses a public client with PKCE; no client secret is distributed.

Choose **Sign in with Cloudflare** on the Domain page, authorize your account, and choose a domain. Fresh desktop and server publications automatically discover the shared app's public client ID, approved scopes and HTTPS relay from `https://quillsail.blog/.well-known/quillsail/cloudflare.json`. Users do not register an OAuth app or enter app credentials. Discovery happens when sign-in starts, not when the app starts or the page opens. Temporary discovery failures offer a retry and leave the API-token backup available.

Each instance generates its own PKCE verifier and stores its own encrypted access and refresh tokens. The website publishes only public app metadata; it never receives those tokens or the verifier. Authorization callbacks use the original client details saved when sign-in began, even if the hosted registration changes. Existing connections refresh directly with Cloudflare without depending on discovery.

After connecting, **Reconnect with Cloudflare** renews authorization without deleting the tunnel or managed records. Reauthorization checks access to the existing account and zone before replacing saved credentials.

#### Maintainer setup, once for all users

Register the shared app with the HTTPS callback `https://quillsail.blog/oauth/cloudflare/callback`. Configure Authorization Code and Refresh Token grants with PKCE S256 and token authentication `none`. Verify the client URL domain, provide the required name and logo, and promote the client to **Public** in Cloudflare. Private clients permit authorization only by members of their parent account. Public promotion is permanent.

The approved base scopes are `dns.write zone.read argotunnel.write offline_access`. In Cloudflare's picker, Argo Tunnel (Legacy) Edit is displayed as Cloudflare Tunnel Write (`argotunnel.write`) on review. Keep Workers Scripts, Workers Routes and KV permissions optional until offline fallback is enabled.

Set `QUILLSAIL_CLOUDFLARE_CLIENT_ID` once in the website backend's private environment file and retain its existing `QUILLSAIL_OAUTH_RELAY_SECRET`. The website derives the registered callback from its canonical HTTPS site address. `QUILLSAIL_CLOUDFLARE_SCOPES` and `QUILLSAIL_CLOUDFLARE_EDGE_SCOPES` override the approved base and optional scopes. No client secret, API token, user access token or refresh token belongs in this public registration. See [website configuration](../website/README.md#configuration).

#### Custom clients and forks

The collapsed **Advanced: use your own Cloudflare OAuth app** section overrides discovery for this publication. Save the registered public client ID and HTTPS callback, or leave both fields blank to return to shared sign-in. Existing custom registrations remain supported. Operators can also set:

```toml
[oauth]
cloudflare_client_id = "YOUR_REGISTERED_PUBLIC_CLIENT_ID"
cloudflare_scopes = "YOUR_APPROVED_BASE_SCOPES"
cloudflare_edge_scopes = "YOUR_APPROVED_OPTIONAL_OFFLINE_SCOPES"
cloudflare_relay_url = "https://YOUR_RELAY_HOST/oauth/cloudflare/callback"
# Alternatively, discover your own shared app instead of configuring each publication:
# cloudflare_metadata_url = "https://YOUR_WEBSITE/.well-known/quillsail/cloudflare.json"
```

Environment equivalents are `COPYDESK_CLOUDFLARE_CLIENT_ID`, `COPYDESK_CLOUDFLARE_SCOPES`, `COPYDESK_CLOUDFLARE_EDGE_SCOPES`, `COPYDESK_CLOUDFLARE_RELAY_URL` and `COPYDESK_CLOUDFLARE_METADATA_URL`. Set the metadata URL to an empty string to disable discovery. `CLOUDFLARE_CLIENT_ID` remains an alias of the prefixed client-ID variable, with the prefixed value taking precedence. Desktop publications use the shared default automatically and ignore server environment overrides; custom public values belong in their own configuration or advanced form. A repository `.env` is not automatically imported into publications. `CLOUDFLARE_DNS_TXT_RECORD` is publisher-verification information, not an application credential.

The relay is part of the separate [website app](../website/README.md). Configure `QUILLSAIL_OAUTH_RELAY_SECRET` with a random persistent secret of at least 32 characters, deploy with HTTPS, and register its exact callback URL. It is disabled without that configuration. Its confirmation form shows the publication callback address and requires a click. It never exchanges codes, receives PKCE verifiers, or stores access tokens. Both servers and desktop use this fixed relay callback, avoiding an assumption that Cloudflare permits arbitrary loopback redirect ports. The publication validates browser state, account identity, expiry and single use before exchanging the code itself.

Use path-only access logs at the relay, reverse proxy and publication: authorization codes and subscriber tokens must not enter access logs. The website container uses a query-free access-log format. The relay responses are non-cacheable and use `Referrer-Policy: no-referrer`.

Cloudflare references: [register a client](https://developers.cloudflare.com/fundamentals/oauth/create-an-oauth-client/), [OAuth endpoints](https://developers.cloudflare.com/fundamentals/oauth/integrate-with-cloudflare/).

## Another host and manual DNS

On a server, the Domain page shows the configured public address. Change `site.base_url` or `COPYDESK_BASE_URL`, then restart QuillSail. Path-prefixed server installations remain supported.

On desktop, save an HTTPS public address on the Domain page. This opens a separate loopback listener and keeps local administration on its original address. Point a trusted local reverse proxy to the displayed public port. Forward the public `Host` header and the visitor address in the final `X-Forwarded-For` hop. The Cloudflare connector instead uses `CF-Connecting-IP`. Never expose either loopback listener directly to a network or trust these headers on an unprotected port.

Enter the expected A, AAAA or CNAME record supplied by your host, then choose **Check again**. Checks run in the queue and query each authoritative nameserver, reporting Found, Missing, Different or Unknown. Timeouts and disagreeing nameservers are not treated as empty DNS. The HTTPS check verifies this publication's installation identifier at `/healthz`, without following redirects or permitting private-address DNS rebinding.

## Launching soon

Open **Launch** to edit the heading, Markdown message, optional date and sign-up preference. Choose **Back to launching soon** to hide publication content from readers, or **Go live** to publish normally. Both transitions are audited and fire the `publication.launched` extension event. The checklist reports HTTPS, sender and email-DNS checks; it does not prevent an administrator from launching while an optional check remains unresolved.

Readers can still confirm, manage or cancel subscriptions while launching soon. Article, issue and other content routes redirect home; feeds and the sitemap return 404. Verified dashboard users can preview the full publication and see a launch banner. The sign-up form is hidden until a real sender is connected: file and console mail cannot deliver confirmation emails. Launching soon does not replace article visibility permissions.

## Email DNS

Choose the sending provider and paste its public DKIM records, one per line:

```text
selector._domainkey.example.com CNAME selector.mail-provider.example
selector._domainkey.example.com TXT "v=DKIM1; p=PUBLIC_KEY_FROM_PROVIDER"
```

These are alternative examples. Use the actual records from the provider; never upload a private DKIM key. **Show manual email records** works with any host. Automatic writes require the sending domain to be within the connected Cloudflare zone. For personal Gmail.com, Outlook.com and similar addresses, the email provider manages DNS.

QuillSail merges an SPF include into the existing policy while preserving its whitespace and `all` qualifier. It refuses multiple SPF records, `redirect=`, recursive includes or policies whose lookup budget cannot be safely verified. MX/PTR policies and macros require manual review. A long TXT value remains one logical record; the provider handles DNS character-string splitting. Existing DKIM conflicts are never replaced. A missing DMARC record starts with monitoring-only `p=none`; an existing policy is preserved.

The DNS journal stores an SPF record's exact previous value. **Undo** restores it only when the provider record still matches the value QuillSail wrote. External changes stop undo rather than being overwritten. Email settings, the Launch checklist and `quillsail check` display the most recently saved statuses; queue another check after making external DNS changes.

## While the desktop computer sleeps

The Cloudflare offline fallback is optional and desktop-only. The separate **Keep this computer awake while this publication is public** preference requests idle-sleep inhibition through caffeinate on macOS, Windows execution state, or systemd-inhibit on Linux. It defaults off and is released when the publication stops or loses its public address; power settings and battery restrictions still apply. Enable it on the Domain page. An OAuth connection asks for the additional optional scopes at this point; an API token needs Workers Scripts Edit, Workers Routes Edit and Workers KV Storage Edit added by its owner.

A module Worker passes online requests through. If the origin becomes unreachable, it serves a saved launching-soon page at `/`, accepts sign-ups and token-authorized unsubscribe requests, and shows an offline message elsewhere. It does not copy drafts, dashboards, profiles, articles or account pages. The snapshot's CSS is inlined locally without remote stylesheet fetching.

The Worker limits request size and uses Cloudflare's per-visitor rate-limit binding. Requests are acknowledged only after KV storage succeeds. Sign-ups remain double opt-in; the confirmation email arrives after the computer reconnects. Unsubscribe tokens are checked during replay, and the received time is preserved. A database receipt makes repeated replay harmless, including when a KV deletion needs retrying. Newsletter batches replay the queue before contacting the mail server.

Cloudflare's [KV limits](https://developers.cloudflare.com/kv/platform/limits/) and [rate-limit accuracy](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/) apply. The route requests fail-open behavior at the Worker request limit and is enabled only if Cloudflare confirms that setting; that cannot keep an unreachable origin online. KV quota exhaustion returns an explicit failure, not a false success. A saved warning reports unsubscribe requests that waited more than three days. Keep the computer connected regularly and monitor the queue; this fallback does not provide an uptime or email-compliance guarantee.

Disabling the fallback removes its route, waits for queued writes to settle, drains the subscriber queue, then removes its owned Worker and namespace. Disconnecting hosting does the same before removing managed DNS and the tunnel. Failures retain the credentials and progress needed to retry. If an API token expires or loses permissions, use **Renew Cloudflare API access** to verify a replacement for the same account and domain before resuming. It may take several minutes to finish. Unrelated DNS records and externally modified managed records are never deleted automatically.

## Deferred integrations

Domain Connect remains demand-driven. No registrar templates or signing service are shipped. OAuth activation and a real-provider smoke check remain deployment tasks after the public client and relay are configured. Development tests use mocked Cloudflare APIs, fake DNS, a local fake tunnel process, synthetic subscribers and Node Worker tests; they do not change a live domain or send real email.
