# Competitions

Run writing or project competitions with moderated entries, appointed judges, reader voting, deadlines and published results.

Newsletter publications include competitions. For Blog or Blog + newsletter, first turn on **Settings → General → Enable competitions on blogs**. It is off by default. Turning it off hides the feature and blocks competition routes without deleting existing work. Public competitions need a server installation: the desktop public listener supports reading and subscriptions, while competition management stays on the local address.

## Create a competition

Administrators can host competitions from **Dashboard → Competitions → New competition**. A group can also receive the **Host competitions** permission.

Set the brief, eligibility rules, criteria and prizes, then choose how winners are decided:

- **Judges only**,
- **Reader voting only**, or
- **Judges and reader voting**.

Administrators can judge automatically. Appoint other judges from confirmed, active members. Assigned judges use the public entry pages and don't get access to the rest of the dashboard.

## The phases

A competition moves through these phases:

```text
Draft → Accepting entries → Judging and voting → Closed → Results published
```

Deadlines for submissions and for judging and voting are optional and use the publication's time zone. The server enforces deadlines without needing a background job. Leave them blank to move between phases by hand. Opening a competition locks its setup, and only drafts can be deleted.

## Entries

Entrants submit a title, Markdown text and an optional project or repository link. Each confirmed account can enter once per competition.

Organizers approve or reject entries, with private feedback. While submissions are open, participants can revise or withdraw their entry; a revision returns it to pending approval. Approved entries and their authors' display names become public when judging starts, and submitted work is frozen from then on.

## Judging and voting

Judges score approved entries from 0 to 100 against the stated criteria, and can revise their scores until judging closes. Their notes stay private to them.

Confirmed readers have one vote per competition and can change or remove it until voting closes. Nobody can vote for or judge their own entry. Rejected and withdrawn entries don't take part. Until results are published, scores and vote counts are visible only to organizers.

## Results

Close judging and voting, then publish the results. When judges are involved, every approved entry needs at least one score first.

- **Judges' Choice** ranks entries by average score, rounded to two decimal places.
- **Readers' Choice** ranks entries by votes received.

When a competition uses both, they're separate awards, with no combined weighted score. Tied entries share a rank, and entries with no reader votes don't get a Readers' Choice rank.

Published results are frozen, even if a judge or voter later deletes their account.

## Privacy

Account exports include a person's entries, ballots and private judge notes. Deleting an account removes their ballots, private judge notes and unpublished entries; published competition work stays, with anonymized credit.
