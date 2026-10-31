# Permissions and groups

Permissions belong to groups, and people collect them by joining groups. Everyone, including visitors who aren't signed in, gets the **Everyone** group's permissions. People with a confirmed account also get **Members**. Someone can grant or assign only the permissions they hold themselves. See [groups and permissions](../groups-and-permissions.md) for how to use them.

## Permissions

A person's permissions are the combined permissions of every group they belong to. Administrators always hold every permission.

### Reading

| Permission | Key | What it allows |
| --- | --- | --- |
| Read the publication | `read` | See published articles, issues and pages that are open to everyone. |
| Read members-only articles | `read_members` | See articles that editors have limited to signed-in members. |

### Writing

| Permission | Key | What it allows |
| --- | --- | --- |
| Write and submit | `submit` | Write drafts and send them to the editors for review. |

### Editing

| Permission | Key | What it allows |
| --- | --- | --- |
| Review submissions | `review` | See the submission queue, leave feedback, request changes, accept or decline. |
| Edit any article | `edit_any` | Change the text of any article, not only their own. |
| Publish articles | `publish` | Publish articles on the website, or take them down again. |

### Newsletter

| Permission | Key | What it allows |
| --- | --- | --- |
| Put issues together | `manage_issues` | Create newsletter issues and choose what goes in them. |
| Send issues | `send_issues` | Send issues to subscribers, or schedule them to go out later. |
| Manage subscribers | `manage_subscribers` | See, add, import, export and remove newsletter subscribers. |

### People

| Permission | Key | What it allows |
| --- | --- | --- |
| Manage members | `manage_users` | Edit accounts, approve requests to join groups, and block people. |
| Manage groups and permissions | `manage_groups` | Create groups and decide what each one is allowed to do. |
| Manage business outreach | `manage_business` | Read private business inquiries, record follow-up, and approve opportunities for editorial use. |

### Site

| Permission | Key | What it allows |
| --- | --- | --- |
| Manage pages and sections | `manage_pages` | Edit pages such as About, and the list of sections. |
| Change site settings | `manage_settings` | Change the publication's name, look, email and sign-up settings. |
| See the activity log | `view_log` | See who did what on the site, and when. |

### Competitions

| Permission | Key | What it allows |
| --- | --- | --- |
| Host competitions | `manage_competitions` | Create competitions, moderate entries, appoint judges and publish results. |

## Groups on a new site

New sites start with these groups. Rename, change or remove the reader groups under **Dashboard → Groups**. System groups can't be deleted.

| Group | Slug | Kind | Joining | Permissions at the start |
| --- | --- | --- | --- | --- |
| Everyone | `everyone` | Implicit | — | Read the publication |
| Members | `members` | Implicit | — | Read members-only articles, Write and submit |
| Editors | `editors` | System | — | Review submissions, Edit any article, Publish articles, Put issues together, Send issues, Manage subscribers, Manage pages and sections, See the activity log |
| Administrators | `admins` | System | — | Every permission |
| Students | `students` | Reader group | Approval | None |
| Staff | `staff` | Reader group | Approval | None |
| Alumni | `alumni` | Reader group | Approval | None |

---

*Generated from the QuillSail 1.15.0 source code by `scripts/build_reference_docs.py`.*
