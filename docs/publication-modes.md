# Blog and newsletter modes

A QuillSail publication is a **Newsletter**, a **Blog**, or a **Blog + newsletter**. Hosts choose during browser setup, with `quillsail init --mode blog` or `--mode hybrid`, or later under **Settings → General → Publication type**. The default is Newsletter.

Switching modes preserves existing posts, issues, subscriptions, groups and permissions.

## What changes between modes

| | Newsletter | Blog | Blog + newsletter |
| --- | --- | --- | --- |
| Homepage | The newsletter: latest issue and sign-up | Chronological posts | Chronological posts, with sign-up |
| Email subscriptions | Shown | Hidden | Shown |
| Newsletter issues | Yes | Existing issue pages stay available | Yes |
| Competitions | Included | Optional, off by default | Optional, off by default |

Blog modes use a chronological post homepage and an RSS link. Blog + newsletter also shows email subscriptions; Blog hides the newsletter calls to action. Existing issue and subscription URLs remain available, so changing presentation doesn't break previously shared links.

Readers can browse sections with published public posts, search from the main navigation, and follow newer and older public posts from each post's footer. The blog dashboard shows latest posts and your own private draft count, opens **Posts** on the published tab, and hides newsletter issues and subscribers in Blog mode. With submissions closed, empty review panels disappear; existing contributions that still need attention remain visible. Search in Blog mode covers posts; Blog + newsletter also searches issues.

To add competitions to either blog mode, enable **Settings → General → Enable competitions on blogs**. This adds competition pages and dashboard management. Turning it off preserves existing competitions, entries, votes and results, and makes their routes unavailable until re-enabled. Switching to Newsletter restores its normal competition feature.

Desktop-hosted public websites support reading, search, tags, feeds and email subscriptions. Sign-in, community writing, competitions and account management stay on the local desktop address; public navigation omits these unavailable actions. Use a [server installation](installation.md) for public accounts, submissions or competitions. Owners sign in through **Open dashboard** in the desktop app. A server-hosted blog keeps its normal sign-in and optional community submissions.

Use the **Writing** and **Accounts** settings to choose whether to accept community submissions or keep the blog for its existing authors.

## Publishing posts directly

Administrators and trusted accounts with the **Publish articles** permission can publish their own blog posts directly from the writing editor and edit them later. Ordinary writers still submit for editorial review. Publishing a post doesn't create an issue or send a newsletter to subscribers.

## Reusing a post in a newsletter

On a published post, choose **Newsletter options**. A host with the **Put issues together** permission can add the saved post to an existing draft issue or create a new draft, choosing a summary and link or the full article. This reuses the same post rather than copying it, and adding it to the same issue twice doesn't duplicate it. Review and send the issue using the normal [newsletter workflow](newsletter-issues.md). For this local newsletter feature, choose Blog + newsletter.

## Offering a post to another newsletter

A blog can offer its posts to a separately hosted QuillSail newsletter. Set **External newsletter website** in General settings to that newsletter's QuillSail base address, including any path, such as `https://newsletter.example.org`. From **Newsletter options**, **Continue to newsletter** opens its submission form carrying the public post's address, title, author credit and full article. Restricted posts and drafts can't use this handoff. Both sites need 1.11.0 or later for full-text transfer and creator blurbs. Older versions with blog-submission support (1.3.0 or later) still allow manually pasting the article. For other newsletter software, share the original post's address with its editors yourself.

The writer signs in to a confirmed account on the destination site, reviews the transferred article (at least 20 words), and can write a separate **Your newsletter blurb** of up to 5,000 characters. This is plain text: a short introduction or selected passage for the newsletter. Then they confirm they have permission and submit. Nothing is submitted or published automatically. The destination's normal submission permissions, sections and closing rules apply. A site that's closed to registration may require an invitation before the writer can submit.

The browser transfers the article without putting its text in server query logs. Keep the destination tab open while signing in; its temporary transfer expires after 30 minutes. JavaScript and browser session storage enable this handoff. If they aren't available, or the transfer expires, paste the article into the form. The receiving server never fetches the source address and doesn't accept sign-in authority from the blog. This is a submitted snapshot, not ongoing synchronization; linked images remain on the original site.

The receiving editors review the full article and the separate creator blurb. They can publish the article on the site, include it in an issue, or both. In the issue composer, choose **The full article**, **The creator's newsletter blurb and a link**, or **A summary and a “read more” link** with an optional editor-written custom summary. The creator's blurb is available only when one was submitted; the custom summary never overwrites it. Choices apply to the web issue and HTML/plain-text email. Source links and credit stay with the article and newsletter. The issue's **Publish accepted articles when this issue goes out** option controls whether its accepted articles also become standalone articles on the destination website.
