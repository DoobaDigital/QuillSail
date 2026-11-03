# Public API

The API lives under `/api/v1` (including any configured site prefix). Read routes return JSON and expose published public articles. A private publication also requires an authenticated reader with the publication's read permission. There are no editorial write endpoints or API keys in this release.

| Method and path | Response |
| --- | --- |
| `GET /api/v1/` | Publication details and endpoint URLs |
| `GET /api/v1/articles` | Paginated articles; optional `section` and `tag` slug filters |
| `GET /api/v1/articles/<slug>` | One public article, including HTML and its source text |
| `GET /api/v1/issues` | Paginated published issues |
| `GET /api/v1/issues/latest` | Latest issue, including its public items |
| `GET /api/v1/issues/<number>` | A published issue and its public items |
| `GET /api/v1/sections` | Section names, descriptions, and URLs |
| `POST /api/v1/subscribe` | Queue a subscription confirmation |

List responses use `page`, `pages`, `total`, and `per_page` metadata; request another page with `?page=2`. Public article bodies are sanitized when rendered as HTML. Audience-targeted items and unpublished articles are omitted from the public issue API. Missing content returns 404; inaccessible private publications return 403. Authenticated responses and pages containing subscriber credentials use `Cache-Control: private, no-store`.

A single article's `html` is always safe to show. `body_format` says how its source was written (`markdown`, `html` or `markdown_html`) and `source` holds that text. `markdown` is kept for existing clients and is `null` for articles written in HTML.

## Subscription endpoint

Send a JSON object or form fields containing `email`, optional `name`, and optional `groups`. JSON groups are a list of group slugs; form groups can repeat or use a comma-separated value. Only offered audience groups are accepted, and group selection is disabled when the publication turns off that option. Audience preferences grant no account permissions.

```json
{"email": "reader@example.edu", "name": "A Reader", "groups": ["alumni"]}
```

Success returns HTTP 202 and asks the reader to check their inbox. Existing active subscriptions receive an account-management reminder rather than having their preferences changed. Invalid input returns 400 and rate-limited requests return 429. The response does not reveal whether an address is already subscribed. A running worker is required to deliver messages.

Public read endpoints allow cross-origin reads. For embedded signup forms, set `newsletter.embed_origins` in dashboard Settings to the permitted website origins. An empty list allows any origin for signup; this is the default. Signup does not accept cookie-based authority through this API and always requires email confirmation.
