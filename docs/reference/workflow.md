# Editorial workflow

Every piece of writing has a status. It changes only through the actions below, which check permissions on the server. Drafts are private to their writers and co-authors. [Writing and review](../writing-and-review.md) walks through the process.

## Statuses

| Status | Key | What the writer sees | What editors see |
| --- | --- | --- | --- |
| Draft | `draft` | Only you (and any co-authors) can see this. Submit it when you're ready for an editor to read it. | The writer hasn't submitted this yet. |
| Submitted | `submitted` | We've got it. An editor will pick it up soon, and you'll get an email when they do. | Waiting for an editor to pick it up. |
| In review | `in_review` | An editor is reading your piece. You'll hear back by email. | An editor is reviewing it. |
| Changes requested | `changes_requested` | Your editor asked for some changes. Read their note below, edit your piece, then resubmit it. | Waiting for the writer to make changes. |
| Accepted | `accepted` | Accepted! It will appear on the site or in an upcoming issue. We'll email you when it's live. | Ready to publish or add to an issue. |
| Published | `published` | Your piece is live. | Live on the site. |
| Declined | `declined` | This piece won't be published. If your editor left a note, it's below. | Declined. |
| Withdrawn | `withdrawn` | You withdrew this piece. You can move it back to your drafts at any time. | The writer withdrew it. |

## Moves between statuses

Each move is recorded on the article's timeline, written to the activity log, emailed to the people involved and announced to extensions as `article.status_changed`. Writers can edit their piece while it's a draft or has changes requested.

| Action | From | To | Who can do it | Note to the writer |
| --- | --- | --- | --- | --- |
| Submit for review | Draft | Submitted | The writer | — |
| Resubmit | Changes requested | Submitted | The writer | Optional |
| Withdraw | Submitted, In review, Changes requested, Accepted | Withdrawn | The writer | — |
| Move back to drafts | Withdrawn, Declined | Draft | The writer | — |
| Start review | Submitted | In review | An editor with *Review submissions* | — |
| Request changes | Submitted, In review, Accepted | Changes requested | An editor with *Review submissions* | Required |
| Accept | Submitted, In review, Changes requested | Accepted | An editor with *Review submissions* | Optional |
| Decline | Submitted, In review, Changes requested, Accepted | Declined | An editor with *Review submissions* | Optional |
| Publish now | Draft, Submitted, In review, Accepted | Published | An editor with *Publish articles* | — |
| Unpublish | Published | Accepted | An editor with *Publish articles* | — |
| Reopen review | Declined, Withdrawn | In review | An editor with *Review submissions* | — |

---

*Generated from the QuillSail 1.14.1 source code by `scripts/build_reference_docs.py`.*
