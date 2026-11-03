# Extensions

Create `extensions/announcements.py` beside the instance configuration:

```python
import logging
from copydesk.hooks import Extension

extension = Extension("announcements", title="Announcements", version="0.1.0")

@extension.on("article.published")
def published(article):
    logging.getLogger(__name__).info("Published article %s", article.id)
```

Enable it in `copydesk.toml` and restart web and worker processes:

```toml
[extensions]
enabled = ["announcements"]
```

Discovery checks the local extension directory, bundled extensions, then installed Python modules. Each module exposes `extension = Extension(...)`. Python packages with `__init__.py` are also supported. Extensions execute trusted Python code with the application's access to configuration, data, and network.

Available extension APIs include `on(event)`, `filter(name)`, `slot(name)`, `markdown(fn)`, `setup(fn)`, `job(kind)`, `command(...)`, `permission(...)`, `setting(...)`, `add_blueprint(...)`, and `add_dashboard_link(...)`. See `src/copydesk/hooks.py` for signatures. Filters accept the current value and return its replacement. Event handlers should accept the keyword arguments emitted at their call sites.

Markdown plugins added with `markdown(fn)` apply to articles in every format that uses Markdown. The `markdown.html` filter runs after sanitizing for all of them. In articles that mix Markdown with typed HTML, classes other than the ones core Markdown produces are removed, so a plugin's custom classes only survive in plain Markdown. If a plugin adds syntax the visual editor doesn't know, those blocks stay as editable source, so they're never damaged. Importing a blog fires no article events.

Useful events include `app.ready`, `article.created`, `article.saved`, `article.submitted`, `article.status_changed`, `article.published`, `article.commented`, `membership.requested`, `membership.changed`, `subscriber.confirmed`, `subscriber.unsubscribed`, `issue.scheduled`, `issue.sending`, and `issue.sent`. Filters include `nav.items`, `issue.recipients`, and `mail.before_send`. Inspect the emitter before implementing an integration. Side effects can be retried; make handlers idempotent and queue slow work rather than blocking requests.

The bundled `webhooks` extension posts publication announcements. Configure endpoints under `[extensions.webhooks]`; its source documents supported formats and event payloads. Keep webhook URLs private, and review what publication metadata is sent before enabling an external integration.

Long-running custom job handlers should call `copydesk.jobs.renew_lease()` and commit progress more often than every 15 minutes. This renews their claim and worker heartbeat. Keep externally visible operations idempotent because a process can fail after performing a side effect but before committing its record. `article.commented` handlers receive an `event` object; internal notes must be restricted to authorized reviewers in any integration.

## Publication launch event

`publication.launched` receives `old`, `new` (`live` or `soon`) and `actor` for each launch-state transition. The bundled webhooks extension supports this event when explicitly listed in an endpoint’s `events`; existing default subscriptions are unchanged. See [Domains and launch](hosting.md).
