# Importing a blog

If your blog is on Jekyll, you can bring it into QuillSail with its posts, dates, tags, images and old addresses. You see exactly what will happen first, and nothing changes until you confirm.

## What you need

The site's **source folder**, the one with `_config.yml` and `_posts`. The built `_site` folder won't work, because it no longer has your Markdown. A GitHub **Download ZIP** is fine.

## From the dashboard

You need the **Import a blog** permission. Administrators have it.

1. Go to **Dashboard → Import a blog** and upload a zip of the source folder.
2. Check the report. It lists every post, what it will become, its old and new addresses, and anything that needs your attention.
3. Choose **Import**. You can tick **Bring everything in as drafts** to review and publish each post yourself.

The import runs in the background, so the worker must be running. You can leave the page, and the report stays available for a week. The largest upload is set by `[uploads] max_import_mb`, 200 MB by default. If you run behind nginx, raise its `client_max_body_size` to match.

## From the command line

```sh
quillsail import-jekyll ./my-blog --dry-run     # report only, changes nothing
quillsail import-jekyll ./my-blog               # asks before importing
quillsail import-jekyll ./my-blog.zip --yes --as-drafts --author sam
```

`--author` names the account that owns the import. Without it, that's the first administrator.

## How posts come across

| In Jekyll | In QuillSail | Notes |
| --- | --- | --- |
| `title` | Title | Up to 200 characters. Without one, it's made from the file name. |
| File name | Web address | `2026-09-23-my-post.md` becomes `/articles/my-post/`. A `slug` overrides it. |
| `date` | Published date | Your original date is kept. Without one, the date in the file name is used. A date with no offset uses `timezone` from `_config.yml`. |
| `description` or `excerpt` | Excerpt | Up to 400 characters. |
| `categories` | Section and tags | The first category becomes the section, created if needed. The rest become tags. |
| `tags` | Tags | A list or a space-separated string. A post can have 12. |
| `image` | Cover image | A path, or `path` and `alt`. |
| `pin` | Featured | From the Chirpy theme. |
| `author` or `authors` | Authors | Matched to accounts by username, name or email, using `_data/authors.yml` if you have it. Otherwise the post is credited to the account running the import. Accounts are never created for you. |
| `last_modified_at` | Last updated | |
| `published: false`, `_drafts/`, future dates | Draft | QuillSail doesn't schedule posts. |

Defaults from `_config.yml` apply, as they do in Jekyll.

A post with no HTML in it becomes ordinary **Markdown** and opens in the visual editor. A post that mixes in HTML becomes **Markdown with HTML** and opens as text. A `.html` post becomes **HTML**. See [writing and review](writing-and-review.md#html) for what HTML can do here.

## What gets converted

QuillSail never runs Jekyll, Liquid or plugins. It recognizes common patterns in the text and leaves code blocks exactly as written.

| Converted | To |
| --- | --- |
| `{% post_url %}` and `{% link %}` | The post's new address |
| `{% highlight %}` | A fenced code block |
| `{% raw %}` | Its contents, as plain text |
| `{{ site.baseurl }}`, `{{ site.url }}`, `relative_url`, `absolute_url` | A path on your site |
| `{{ site.title }}` and `{{ page.title }}` | The title |
| `{% comment %}`, `{::comment}`, `<!-- comments -->` | Removed |
| `{: .prompt-tip }` and the other Chirpy prompts | A `tip`, `note` or `warning` box. `info` becomes `note`, and `danger` becomes `warning`. |
| `{: .class }`, `{:target="_blank"}` and other attribute lists, `{:toc}` | Removed |

The report flags these for you to fix after importing:

- `{% include %}`, `{% if %}`, `{% for %}` and other Liquid, which would show as text;
- math, which QuillSail doesn't render;
- HTML that will be removed, such as `<script>` and embeds other than YouTube and Vimeo;
- images that weren't found, and SVG images, which can't be uploaded.

Images go through the same checks as any upload, so they're re-saved and lose camera metadata. An image used by several posts is stored once.

## Old addresses

Each post keeps a record of its old address, worked out from `permalink` in `_config.yml`, the post's own `permalink`, and any `redirect_from` list. A request for an old address gets a permanent redirect to the new one, with or without a trailing slash or `.html`. Existing pages always win over a redirect, and drafts never redirect.

**Redirects only work if QuillSail answers on your old domain.** Point the domain at QuillSail once you're happy with the import. GitHub Pages can't send redirects, so a blog moving away from `github.io` needs [`jekyll-redirect-from`](https://github.com/jekyll/jekyll-redirect-from) on the old site instead.

Feed readers identify posts by address, so they may show recent posts as new after you move.

## Doing it again

Importing is safe to repeat. A post whose old address has already been imported is skipped, so nothing is duplicated, and edits you've made here aren't overwritten. If one post fails, the others still import, and running the import again finishes the rest.

Importing sends no email and fires no webhooks, because your readers have already seen these posts. To tell subscribers about one, add it to an issue. The activity log and each post's timeline record the import.

## Safety

An uploaded zip is rejected whole if it has unsafe paths or symbolic links, is password protected or damaged, unpacks to more than five times the upload limit, or has more than 20,000 files. Folders a site doesn't need, such as `.git`, `_site` and `node_modules`, aren't unpacked. Uploads are removed once they've been imported, or after a week.
