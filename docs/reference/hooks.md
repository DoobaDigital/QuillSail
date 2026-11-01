# Extension hooks

Extensions are Python modules that create `extension = Extension("name")` and register hooks on it. [Extensions](../extensions.md) shows how to write and enable one. Handlers run in the web and worker processes with full access to the application, so install only extensions you trust.

## Events

Register a handler with `@extension.on("event.name")`. Handlers receive these keyword arguments.

| Event | Arguments | When |
| --- | --- | --- |
| `publication.launched` | old, new, actor | publication launch state changed |
| `app.ready` | app | the Flask app, once every extension has loaded |
| `user.registered` | user | someone created an account |
| `user.verified` | user | someone confirmed their email address |
| `user.deleted` | user | someone deleted their account (already anonymized) |
| `membership.requested` | membership | someone asked to join a group |
| `membership.changed` | membership, action | added, approved, rejected or removed |
| `subscriber.confirmed` | subscriber | a new subscriber confirmed their address |
| `subscriber.unsubscribed` | subscriber | someone unsubscribed |
| `article.created` | article | a new draft was started |
| `article.saved` | article, revision | an article's text was saved |
| `article.submitted` | article | a writer sent a piece to the editors |
| `article.status_changed` |  | article, old, new, actor, message |
| `article.published` | article | an article went live on the site |
| `article.commented` | article, event | someone added a comment |
| `issue.scheduled` | issue | an issue was scheduled |
| `issue.sending` | issue | an issue started sending |
| `issue.sent` | issue | every email for an issue has been sent |

## Filters

Register with `@extension.filter("filter.name")`. A filter receives the current value, plus any extra arguments, and returns the value to use.

| Filter | Arguments | What it changes |
| --- | --- | --- |
| `markdown.html` | html | rendered article HTML, after sanitizing |
| `mail.before_send` | email | an Email about to be sent; return None to stop it |
| `issue.recipients` | subscribers, issue | the list of subscribers an issue will go to |
| `nav.items` | items, user | list of (label, url) links in the site header |

## Template slots

Register with `@extension.slot("slot")` and return HTML to insert. Return markup from a template, or escape values yourself.

| Slot | Where it appears |
| --- | --- |
| `head` | Extra tags inside <head> on every page |
| `body_end` | Just before </body> on every page |
| `header_end` | End of the site header |
| `home_after_hero` | Home page, under the sign-up box |
| `article_before_body` | Article page, above the text |
| `article_after_body` | Article page, below the text |
| `issue_after` | Issue page, after the last item |
| `footer` | Inside the site footer |
| `dashboard_overview` | Dashboard home, under the summary cards |
| `account_profile` | Account settings, after the profile form |
| `email_footer` | Every email, above the footer |

## The `Extension` object

| Method | What it does |
| --- | --- |
| `add_blueprint(blueprint)` | Add a Flask blueprint with the extension's own pages. |
| `add_dashboard_link(label, endpoint, permission=None)` | Add a link to the dashboard menu, shown to people with the given permission. |
| `command(*args, **kwargs)` | Add a command-line command: `quillsail ext <name> ...`. |
| `filter(name)` | Decorator: let the function change a value before QuillSail uses it. |
| `job(kind)` | Register a background job handler (see copydesk.jobs). |
| `markdown(fn)` | Register `fn(md)` to customize the Markdown parser (add markdown-it plugins). |
| `on(event)` | Decorator: run the function when an event happens. |
| `option(key, default=None)` | A value from this extension's table in copydesk.toml. |
| `permission(key, label, description)` | Add a permission to the permission editor, listed under the extension's title. |
| `setting(key, default, label, **kwargs)` | Declare a setting editors can change under Settings → Extensions. |
| `setup(fn)` | Register `fn(app)` to run when the extension loads. |
| `slot(name)` | Decorator: insert the function's HTML into a template slot. |

---

*Generated from the QuillSail 1.15.0 source code by `scripts/build_reference_docs.py`.*
