# Writing and review

Members write. Editors review. Every piece moves through a clear set of statuses, and both sides can see where it stands. This page follows a piece from first draft to publication.

## Writing a piece

Anyone with a confirmed account and the **Write and submit** permission can write. On the public site, choose **Write for us**, then start a new piece.

You can write three ways, and switch between them with the buttons above the toolbar:

- **Visual** looks like the finished piece, with buttons for formatting. You don't need to know Markdown. Your piece is saved as Markdown.
- **Markdown** lets you type the formatting yourself.
- **HTML** lets you type safe HTML.

**Preview** shows the piece exactly as the site will render it. Without JavaScript you get the text area and a **Format** list, and everything else still works.

A piece has:

- a **title** (up to 200 characters) and an optional **subtitle** (up to 300);
- the **body**;
- a **section** and **tags**, if your publication uses them;
- up to five **co-authors**, by username or email address, who must have confirmed accounts;
- an optional **cover image**, which needs a short description for people who can't see it;
- an optional **note to the editors**.

Save as often as you like. Drafts are private: only you and your co-authors can see them, even if you're also an editor. If your browser closes before you save, it offers your changes back the next time you open the piece.

Choose **Download as Markdown** beside the editor to get the saved version as a `.md` file. A piece written in HTML downloads as `.html`.

### The visual editor

The toolbar covers headings, bold, italic, strikethrough, links, code, bulleted, numbered and task lists, quotes, code blocks with a language, tables, highlighted boxes, footnotes, dividing lines and images. When your cursor is in a table, code block, box or task list, extra controls for it appear under the toolbar. Typing Markdown shortcuts such as `## ` or `- ` also works.

Keyboard shortcuts use Ctrl, or Command on a Mac:

| Keys | What they do |
| --- | --- |
| Ctrl+B, Ctrl+I, Ctrl+Shift+X, Ctrl+E | Bold, italic, strikethrough, code |
| Ctrl+K | Add or edit a link |
| Ctrl+Alt+1 to 6, Ctrl+Alt+0 | Heading 1 to 6, normal paragraph |
| Ctrl+Shift+7, 8, 9 | Numbered, bulleted and task list |
| Ctrl+Shift+B, Ctrl+Alt+C | Quote, code block |
| Ctrl+Z, Ctrl+Y | Undo, redo |
| Shift+Enter | A new line in the same paragraph |
| Tab, Shift+Tab | Move between table cells, or indent a list item |
| Escape or Alt+F10 | Move from your text to the toolbar, where arrow keys move between buttons. Escape goes back. |

**Pasting.** Formatted text from another page or document keeps its headings, emphasis, links, lists and tables. Scripts, styles, forms and embedded images are left out. Pasted Markdown becomes formatted text, and pasting a web address over selected text makes a link. Pasted or dropped images upload just as they do from the image button.

**What stays the same.** Opening a piece and saving it never changes it. Only the blocks you edit are rewritten, and undoing an edit brings back exactly what you wrote.

**What the visual editor can't show.** Some Markdown has no visual form, such as `^[inline footnotes]`, link definitions, and syntax added by an extension. Those parts appear in a labelled box as editable Markdown, and they're saved exactly as you type them. Nothing is ever removed.

There's one limit in Markdown itself: emphasis can't start on punctuation straight after a letter, as in `word*"quote"*`. If you format text that way, the asterisks show. Add a space before it.

### Switching formats

Going from Markdown to HTML rewrites your piece as the HTML the site would render, so it looks the same. If you switch straight back without changing anything, you get your exact original text.

Going from HTML to Markdown can lose formatting Markdown doesn't have. QuillSail lists what will change and asks first. Your text always stays. Nothing is saved until you save, and every version stays in **History**.

Pieces in HTML open in the HTML view, not the visual editor. To edit one visually, choose **Visual** and confirm the switch to Markdown.

### Markdown

QuillSail supports the usual Markdown, plus:

- tables, footnotes, task lists and ~~strikethrough~~;
- links that are typed as plain web addresses;
- code blocks with syntax highlighting, fenced with three backticks and a language name;
- callouts, in three kinds: `note`, `tip` and `warning`.

```text
::: tip An optional title
Callouts make a highlighted box.
:::
```

Raw HTML isn't rendered in Markdown, so `<b>` shows as text. Use the **HTML** format for that. Every piece is sanitized before it's shown, so it can't add scripts or styles to your site. Extensions can add more Markdown features.

### HTML

Because anyone with a writer account can submit a piece, HTML mode allows safe HTML only.

- **Allowed:** text, headings, lists, tables, links, images, quotes, code, `<details>`, `<mark>`, `<kbd>`, `<figure>`, `<video>` and `<audio>`.
- **Embeds:** `<iframe>` works for YouTube and Vimeo. Other embeds are removed.
- **Removed:** `<script>`, `<style>`, `<form>`, event attributes such as `onclick`, and `style=` attributes.
- **Classes:** only the ones Markdown itself produces, such as `callout callout-tip`. A piece can't use the site's own classes to imitate its buttons or alerts.

In newsletters, video, audio and embeds become links, and collapsed sections are shown open, because most email apps can't play or fold them.

Posts imported from a blog can also be **Markdown with HTML**, which mixes both. See [importing a blog](importing-a-blog.md).

### Images

Upload images from the editor. QuillSail opens and re-saves every image to check it really is an image, applies the camera's rotation, shrinks very large photos, and removes the metadata cameras add, which can include the location where a photo was taken. The size limit is set by `[uploads] max_size_mb` in the server configuration, 10 MB by default.

Uploaded images are public once their address is known, even if the piece isn't. Don't upload anything confidential.

### Revision history

Each save that changes the text or its format keeps a revision. Restoring a revision restores its format too. Open **History** to see every revision with its author and word count, compare any revision with the one before, and restore an earlier version.

## Submitting

When the piece is ready, choose **Submit for review**. If your publication asks for it, choose a section first. If there's a word limit, the editor warns you when you're over it.

Once a piece is submitted, it's with the editors and you can't edit it until they ask for changes. You can still:

- follow its **timeline**, which shows each status change and comment;
- **comment** to talk with your editor;
- **withdraw** it, which stops the editors working on it. Later, **Move back to drafts** to keep working.

A draft that was never submitted can be deleted. After submission, withdraw it instead.

## Reviewing

Editors with **Review submissions** find new pieces under **Dashboard → Articles**. Open one to read it, see its timeline and act on it:

| Action | What happens |
| --- | --- |
| **Start review** | The piece moves to *In review*, so other editors know someone has it. |
| **Request changes** | The piece goes back to the writer to edit. You must say what to change. |
| **Accept** | The piece is ready to publish or to add to an issue. A note to the writer is optional. |
| **Decline** | The piece won't be published. A kind, specific note helps the writer. |
| **Publish now** | The piece goes live on the site. |
| **Unpublish** | The piece comes off the site and returns to *Accepted*. |
| **Reopen review** | A declined or withdrawn piece goes back to *In review*. |

The [editorial workflow reference](reference/workflow.md) lists every status and which actions apply to each.

A few rules keep things fair and safe:

- Editors can't publish someone else's draft before the writer submits it.
- Editors with **Edit any article** can fix a piece's text once it's submitted. Their edits are saved as revisions, with a short summary, and recorded in the activity log.
- You can **assign** a piece to a particular editor, who's then shown as responsible for it.

### Comments and internal notes

Comments on a piece's timeline go to its writer and the editors. An editor can instead post an **internal note**, which only people who can review submissions see. Use internal notes for editorial discussion the writer shouldn't read.

### Notifications

QuillSail emails people when something they care about happens:

- writers, when an editor comments, requests changes, accepts or publishes their piece;
- editors, when a piece is submitted or resubmitted;
- people who manage members, when someone asks to join an approval group.

Each person can turn these off under **Account → Notifications**. Every change is also recorded in the **activity log**.

## Publishing settings

Editors with **Publish articles** set each article's publishing settings in the dashboard:

- **Web address**: the slug in the article's URL.
- **Who can read it**: everyone, signed-in members, or members of particular reader groups.
- **Excerpt**: up to 400 characters, used in lists, feeds and newsletter summaries.
- **Featured**: highlight the article on the homepage.
- **Section**.

### Who can read a published article

| Visibility | Readers |
| --- | --- |
| Everyone | Anyone allowed to read the publication |
| Signed-in members | People with **Read members-only articles**, plus editors who can review |
| Particular groups | Confirmed members of the chosen reader groups, plus editors who can review |

Restricted articles never become public summaries. In newsletters and on public lists they appear only with a summary an editor wrote on purpose: the excerpt, the subtitle or an issue summary. Check those before publishing.

## Publishing directly

In Blog and Blog + newsletter modes, people with **Publish articles** can publish their own posts straight from the editor and edit them afterwards, without a review. Everyone else still submits for review. Publishing a post doesn't send it to subscribers; add it to an issue for that. See [blog and newsletter modes](publication-modes.md).

## Deleting articles

To delete an article from the dashboard, first unpublish or decline it. Deleting can't be undone.
