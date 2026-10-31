# Dashboard settings

Administrators change these under **Dashboard → Settings**, and they're stored in the database, so they take effect without a restart. Settings marked as uploads, such as logos, are changed on the Appearance page. Extensions can add their own settings, which appear under **Extensions**. Keys are what templates and extensions read, for example `setting('site.name')`.

## General

| Setting | Key | Default | Notes |
| --- | --- | --- | --- |
| Publication name | `site.name` | `My Newsletter` | Shown at the top of every page and in every email. |
| Publication type | `site.mode` | Newsletter (`newsletter`) | Blog puts posts first. Blog + newsletter also offers email subscriptions and newsletter issues. Switching preserves your posts, issues, subscribers and settings. Options: Newsletter, Blog, Blog + newsletter. |
| Tagline | `site.tagline` | Blank | One short line under the name, e.g. “News and ideas from our members.” |
| Description | `site.description` | Blank | A sentence or two about the publication. Used by search engines and link previews. |
| Published by | `site.organization` | Blank | The club, department or organization behind the publication. |
| Organization website | `site.organization_url` | Blank |  |
| Contact email | `site.contact_email` | Blank | Shown in the footer so readers can reach the editors. |
| Time zone | `site.timezone` | `America/New_York` | Dates are shown, and issues are scheduled, in this time zone. |
| Footer text | `site.footer` | Blank | Optional. Appears at the bottom of every page. |
| External newsletter website | `blog.newsletter_url` | Blank | Optional. The base URL of another QuillSail newsletter, such as https://acm.cse.sc.edu/newsletter. Public blog posts can be offered there for editorial review. Nothing is submitted automatically. |
| Accept business outreach | `business.enabled` | Off | Adds a For businesses form for workforce opportunities, projects, partnerships, and feedback. Contacts confirm their email before staff review requests in Business outreach. |

## Appearance

| Setting | Key | Default | Notes |
| --- | --- | --- | --- |
| Installed template theme | `appearance.theme` | `default` | Themes change the overall look. More can be installed in the themes folder. |
| Accent color | `appearance.accent_color` | `#1F5BD8` | Used for links and buttons. If it's too light or too dark to read, QuillSail adjusts it automatically. |
| Body typeface | `appearance.article_font` | Editorial serif (`serif`) | Options: Editorial serif, Modern sans serif, Humanist sans serif, Bookish slab serif, Monospace, Custom font stack. |
| Logo | `appearance.logo` | Blank | Upload on the Appearance page. Shown instead of the publication name in the header. |
| Show the number of subscribers | `appearance.show_subscriber_count` | Off | Adds “Join 1,234 readers” under the sign-up form once you have 25 or more. |
| Home page introduction | `appearance.home_intro` | Blank | Optional. A short welcome shown on the home page under the sign-up form. |
| Custom CSS | `appearance.custom_css` | Blank | Advanced. Added after the theme's styles on the website and dashboard. Use .dashboard for dashboard-specific rules. |
| Starting style | `appearance.style` | Classic (`classic`) | Options: Classic, Broadsheet, Brief, Reference, Canvas. |
| Logo for dark backgrounds | `appearance.logo_dark` | Blank |  |
| Email logo | `appearance.email_logo` | Blank |  |
| Publication icon | `appearance.favicon` | Blank |  |
| Homepage hero logo | `appearance.hero_logo` | Blank |  |
| Homepage hero logo for dark backgrounds | `appearance.hero_logo_dark` | Blank |  |
| Hero content | `appearance.hero_display` | Title text (`title`) | Options: Title text, Logo, Logo and title text. |
| Hero alignment | `appearance.hero_align` | Default (centered for newsletters, left for blogs) (`default`) | Lines up the overline, title or logo, and subtitle. Options: Default (centered for newsletters, left for blogs), Left, Centered, Right. |
| Hero title | `appearance.hero_title` | Blank | Homepage only. Leave blank to use the publication name. |
| Hero subtitle | `appearance.hero_subtitle` | Blank | Homepage only. Leave blank to use the publication tagline. |
| Hero overline | `appearance.hero_overline` | Blank | The small line above the title. Leave blank to use Published by from General settings. |
| Show hero subtitle | `appearance.hero_show_subtitle` | On |  |
| Show hero overline | `appearance.hero_show_overline` | On |  |
| Hero logo width (pixels) | `appearance.hero_logo_width` | `480` | From 120 to 1000. |
| Masthead shows | `appearance.brand_display` | Logo, or publication name if no logo is uploaded (`logo`) | Options: Logo, or publication name if no logo is uploaded, Logo and publication name, Publication name. |
| Heading typeface | `appearance.heading_font` | Follow body type (`inherit`) | Options: Follow body type, Editorial serif, Modern sans serif, Humanist sans serif, Bookish slab serif, Monospace, Custom font stack. |
| Custom body font stack | `appearance.custom_body_font` | Blank |  |
| Custom heading font stack | `appearance.custom_heading_font` | Blank |  |
| Page background | `appearance.background` | `#ffffff` |  |
| Paper / card background | `appearance.surface` | `#ffffff` |  |
| Body text | `appearance.text_color` | `#16181d` |  |
| Secondary text | `appearance.muted_color` | `#525866` |  |
| Rules and borders | `appearance.border_color` | `#e1e4e9` |  |
| Dark page background | `appearance.dark_background` | Blank |  |
| Dark paper / card background | `appearance.dark_surface` | Blank |  |
| Dark body text | `appearance.dark_text` | Blank |  |
| Website width (pixels) | `appearance.content_width` | `1152` | From 720 to 1600. |
| Reading width (pixels) | `appearance.reading_width` | `640` | From 420 to 1000. |
| Article text size (pixels) | `appearance.body_size` | `18` | From 14 to 26. |
| Line height (percent) | `appearance.line_height` | `170` | From 130 to 220. |
| Corner radius (pixels) | `appearance.corner_radius` | `10` | From 0 to 32. |
| Website logo height (pixels) | `appearance.logo_height` | `40` | From 20 to 120. |
| Email width (pixels) | `appearance.email_width` | `600` | From 480 to 800. |
| Email text size (pixels) | `appearance.email_size` | `16` | From 14 to 24. |
| Email content padding (pixels) | `appearance.email_padding` | `32` | From 12 to 56. |
| Masthead alignment | `appearance.masthead` | Left (`left`) | Options: Left, Centered. |
| Spacing | `appearance.density` | Comfortable (`comfortable`) | Options: Compact, Comfortable, Spacious. |
| Issue layout | `appearance.issue_layout` | Continuous reading (`stacked`) | Options: Continuous reading, Individual story cards, Two columns on wide screens. |
| Default color mode | `appearance.color_mode` | Follow the reader's device (`auto`) | Options: Follow the reader's device, Light, Dark. |
| Email presentation | `appearance.email_layout` | Classic (`classic`) | Options: Classic, Editorial, Compact digest, Reference, Story cards. |
| Custom email CSS | `appearance.email_css` | Blank | Applied to newsletter emails and inlined where supported. Email clients support a smaller set of CSS than browsers. |

## Accounts

| Setting | Key | Default | Notes |
| --- | --- | --- | --- |
| Who can create an account | `accounts.registration` | Anyone (`open`) | Options: Anyone, Only people with an email address at the domains below, Nobody (administrators add people). |
| Allowed email domains | `accounts.allowed_domains` | Blank | One per line. Subdomains are included, so example.edu also allows mail.example.edu. |
| Ask new members which groups they belong to | `accounts.ask_audience` | On | Shows your reader groups (Students, Staff, Alumni…) on the sign-up form. |
| Members must agree to | `accounts.terms_page` | Blank | Optional. Pick a page, such as a code of conduct, that people must agree to when they sign up. |

## Writing

| Setting | Key | Default | Notes |
| --- | --- | --- | --- |
| Accept submissions | `submissions.enabled` | On | When off, the Write page explains that submissions are closed. |
| Write page introduction | `submissions.intro` | A starter message |  |
| Message when submissions are closed | `submissions.closed_message` | `We're not taking new submissions right now. Check back soon!` |  |
| Writing guidelines page | `submissions.guidelines_page` | `guidelines` | Linked from the editor so writers can check the rules as they go. |
| Writers must pick a section | `submissions.require_section` | Off |  |
| Word limit | `submissions.max_words` | `0` | 0 means no limit. Writers see a warning when they go over. |

## Newsletter

| Setting | Key | Default | Notes |
| --- | --- | --- | --- |
| Sign-up heading | `newsletter.signup_heading` | `Get every issue by email` |  |
| Sign-up text | `newsletter.signup_text` | `Free, and you can unsubscribe in one click.` |  |
| Ask subscribers which groups they belong to | `newsletter.ask_audience` | On | Lets you send issues, or parts of issues, to particular groups. |
| Reply-to address | `newsletter.reply_to` | Blank | Where replies to the newsletter go. Leave blank to use the contact email. |
| Default subject line | `newsletter.subject_format` | `{site} #{number}: {title}` | Used when an issue has no subject of its own. {site}, {number} and {title} are filled in. |
| Articles in emails show | `newsletter.default_display` | A summary and a link to read more (`summary`) | Options: A summary and a link to read more, The full text. |
| Send a welcome email | `newsletter.welcome_enabled` | On | Sent once, right after someone confirms their subscription. |
| Welcome email subject | `newsletter.welcome_subject` | `Welcome to {site}` |  |
| Welcome email message | `newsletter.welcome_body` | A starter message |  |
| Email footer | `newsletter.footer` | Blank | Added to the bottom of every issue, above the unsubscribe link. |
| Mailing address | `newsletter.postal_address` | Blank | Many email providers and anti-spam laws expect a physical mailing address in newsletters. |
| Websites allowed to embed the sign-up form | `newsletter.embed_origins` | Blank | One per line. Lets another site (such as your club's main website) send sign-ups here. |

---

*Generated from the QuillSail 1.14.1 source code by `scripts/build_reference_docs.py`.*
