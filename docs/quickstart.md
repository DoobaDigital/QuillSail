# Quickstart

This walk-through takes about fifteen minutes. You'll install the desktop app, create a publication, take a piece of writing through review, and put together a test issue. Everything stays on your computer, so you can experiment freely.

## 1. Install QuillSail

On macOS or Linux, run this in a terminal:

```sh
curl -fsSL https://quillsail.blog/install.sh | bash
```

On Windows, run this in PowerShell:

```powershell
irm https://quillsail.blog/install.ps1 | iex
```

The installer downloads the app for your computer, checks it against QuillSail's signed release list, and adds a `quillsail` command. Prefer not to use a terminal? [Download the app](https://quillsail.blog/download) instead. [Terminal installer](install-script.md) explains each step it takes.

## 2. Create your publication

Open QuillSail from your Applications folder, Start menu or app menu, or run `quillsail`. The launcher starts a private publication and opens a short setup form in your browser:

1. **Publication name**: what readers will see, such as *The Tech Stack*. You can change it later.
2. **Publication type**: Newsletter, Blog, or Blog + newsletter. Pick Blog + newsletter to try everything.
3. **Your account**: your name, email address and a password of at least 10 characters. This first account is the administrator.

Choose **Create my account and finish**. You're signed in to the dashboard.

> [!NOTE]
> The desktop app's publication is private to your computer. That's ideal for trying things and preparing a launch. When readers need to reach it, run QuillSail on a server; see [server installation](installation.md).

## 3. Make it yours

From the dashboard, take a quick tour:

- **Settings → General**: set the tagline, the organization that publishes it, a contact email and your time zone.
- **Settings → Appearance**: keep QuillSail's own style or pick another starting style, upload a logo, and preview the website and email before saving. Open **Dashboard** on the same page to design the dashboard separately.
- **Pages**: edit the starter **About**, **Writing guidelines** and **Privacy** pages.
- **Groups and permissions**: look at the starter reader groups (Students, Staff and Alumni). Rename them or make your own.

## 4. Take a piece through review

This is what your writers will do, from both sides:

1. On the public site, choose **Write for us**, then start a new piece. Give it a title and a few paragraphs of Markdown, and choose **Submit for review**.
2. In the dashboard, open **Articles**. Your piece is waiting. Open it and choose **Start review**.
3. Leave a comment for the writer, or try **Request changes**, which asks you to explain what should change. Then choose **Accept**, and finally **Publish now**.
4. Open the public site. The piece is live, with its byline, in the archive and in the feed.

Each step was emailed to the people involved. On the desktop, email is saved as files instead of being sent; see step 6.

## 5. Put together an issue

1. In the dashboard, open **Issues** and create a new issue.
2. Add your published article, then add a heading and a text block.
3. Aim the text block at **Alumni** only. Under **Show the version for**, compare what alumni and everyone else will get.
4. Choose **Send a test** and enter your own address.

Don't send it to subscribers yet: you don't have any, and there's no real sender connected.

## 6. Connect email when you're ready

Until you connect a sender, the desktop app saves each message as an `.eml` file in your publication's data folder. Choose **Open data folder** in the launcher to find them; most mail apps can open these files.

When you're ready to deliver real mail, open **Settings → Email** and connect Gmail, Outlook, or an SMTP server. See [Gmail, Outlook and SMTP](email-connectors.md).

## Next steps

- Invite writers: choose who can create an account under **Settings → Accounts**, then share your site's **Write for us** page. See [set up your publication](publication-setup.md).
- Decide who can review, publish and send: see [groups and permissions](groups-and-permissions.md).
- Go live for readers: see [ways to install](install.md) and [server installation](installation.md).
