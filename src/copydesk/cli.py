"""The `quillsail` command. `copydesk` is kept as an alias for existing installs.

    quillsail init            set up a new site (config file, database, first admin)
    quillsail serve           run a development server (with a background worker)
    quillsail worker          send email and do other background work
    quillsail jobs run        process waiting jobs once, then exit (for cron)
    quillsail upgrade         update the database after installing a new version
    quillsail update          update a desktop app or a registered server
    quillsail quit            quit the desktop app and stop its publications
    quillsail check           check the configuration, database and email
    quillsail user ...        create users, reset passwords, manage groups
    quillsail subscribers ... import and export the subscriber list
    quillsail export / import back up or move all data as JSON
    quillsail import-jekyll   bring in an existing Jekyll blog
    quillsail ext ...         commands added by extensions

Run any command with --help for details.
"""

from __future__ import annotations

import contextlib
import csv
import json
import os
import secrets
import signal
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path
from string import Template
from threading import Event

import click

from copydesk import __version__
from copydesk.config import ConfigError, load_config
from copydesk.update_commands import update

TEMPLATE = Path(__file__).parent / "config_template.toml"


class Context:
    def __init__(self, config_path: str | None, instance_id: str | None = None) -> None:
        self.config_path = config_path
        self.instance_id = instance_id
        self._app = None

    def close(self):
        if self._app is not None:
            from copydesk.db import db

            with self._app.app_context():
                db.session.remove()
                db.engine.dispose()

    def app(self):
        if self._app is None:
            from copydesk.app import create_app

            try:
                if self.instance_id:
                    from copydesk.instances import InstanceRegistry, running_url

                    instance = InstanceRegistry().get(self.instance_id)
                    config = load_config(instance.config_path, require_file=True, use_environment=False)
                    if url := running_url(instance):
                        config.base_url = url
                else:
                    config = load_config(self.config_path, require_file=not os.environ.get("COPYDESK_SECRET_KEY"))
            except ConfigError as exc:
                raise click.ClickException(str(exc)) from exc
            self._app = create_app(config)
            if self.instance_id:
                from copydesk.desktop import instance_cookie_name

                self._app.config["SESSION_COOKIE_NAME"] = instance_cookie_name(instance.root)
        return self._app


pass_context = click.make_pass_decorator(Context)


@click.group(help=__doc__.split("\n\n")[0])
@click.option("--config", "config_path", envvar="COPYDESK_CONFIG", type=click.Path(dir_okay=False),
              help="Path to copydesk.toml (default: ./copydesk.toml, then /etc/copydesk/copydesk.toml).")
@click.option("--instance", "instance_id", help="Use a named local instance (see `quillsail instance list`).")
@click.version_option(__version__, prog_name="QuillSail")
@click.pass_context
def main(ctx: click.Context, config_path: str | None, instance_id: str | None) -> None:
    if instance_id and config_path and ctx.get_parameter_source("config_path") == click.core.ParameterSource.COMMANDLINE:
        raise click.UsageError("Choose --instance or --config, rather than both.")
    if instance_id and ctx.invoked_subcommand in {"init", "update", "instance"}:
        raise click.UsageError("Use `quillsail instance create` for a new instance. Software updates are shared: run `quillsail update --desktop` without --instance.")
    ctx.obj = Context(None if instance_id else config_path, instance_id)
    ctx.call_on_close(ctx.obj.close)


# --------------------------------------------------------------------------- init


main.add_command(update)

@main.command()
@click.option("--dir", "directory", default=".", type=click.Path(file_okay=False), show_default=True,
              help="Where to create copydesk.toml and the data folder.")
@click.option("--site-name", help="The publication's name.")
@click.option("--mode", type=click.Choice(["newsletter", "blog", "hybrid"]), default="newsletter", show_default=True, help="Run as a newsletter, a blog, or a blog with a newsletter.")
@click.option("--base-url", help="The public address, e.g. https://news.example.edu")
@click.option("--database-url", help="Leave out to use SQLite in the data folder.")
@click.option("--admin-email")
@click.option("--admin-name")
@click.option("--admin-password", help="Better to type it when asked, so it doesn't end up in your shell history.")
@click.option("--from-email", help="The address emails come from.")
@click.option("--behind-proxy", is_flag=True, help="QuillSail will run behind nginx, Apache or another proxy.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Don't ask questions; use the options and defaults.")
@click.option("--force", is_flag=True, help="Overwrite an existing copydesk.toml.")
def init(directory, site_name, mode, base_url, database_url, admin_email, admin_name, admin_password,
         from_email, behind_proxy, assume_yes, force):
    """Set up a new site: write copydesk.toml, create the database and the first administrator."""
    from copydesk.auth import password_problem
    from copydesk.utils import is_valid_email, normalize_email

    root = Path(directory).resolve()
    config_file = root / "copydesk.toml"
    if config_file.exists() and not force:
        raise click.ClickException(
            f"{config_file} already exists. To update the database after an upgrade, run `quillsail upgrade`. "
            "To start over, use --force."
        )

    def ask(value, prompt, default=None, **kwargs):
        if value or assume_yes:
            return value if value is not None else default
        return click.prompt(prompt, default=default, **kwargs)

    click.secho("\nLet's set up QuillSail.\n", bold=True)
    site_name = ask(site_name, "What's your publication called?", default="My Newsletter")
    base_url = ask(base_url, "Its public address", default="http://localhost:5000").rstrip("/")
    from_email = ask(from_email, "Send emails from", default=f"newsletter@{base_url.split('://')[-1].split('/')[0].split(':')[0]}")

    click.secho("\nNow the first administrator account.", bold=True)
    admin_name = ask(admin_name, "Your name")
    admin_email = normalize_email(ask(admin_email, "Your email address"))
    if not admin_name or not is_valid_email(admin_email):
        raise click.ClickException("An administrator name and a valid email address are required.")
    if not admin_password:
        if assume_yes:
            raise click.ClickException("Pass --admin-password, or leave out --yes to type it.")
        while True:
            admin_password = click.prompt("Choose a password", hide_input=True, confirmation_prompt=True)
            problem = password_problem(admin_password, admin_email)
            if not problem:
                break
            click.secho(problem, fg="red")
    problem = password_problem(admin_password, admin_email)
    if problem:
        raise click.ClickException(problem)

    root.mkdir(parents=True, exist_ok=True)
    (root / "data" / "uploads").mkdir(parents=True, exist_ok=True)
    (root / "extensions").mkdir(exist_ok=True)
    (root / "themes").mkdir(exist_ok=True)
    text = Template(TEMPLATE.read_text(encoding="utf-8")).substitute(
        base_url=base_url,
        secret_key=secrets.token_hex(32),
        database_url=database_url or "sqlite:///data/copydesk.db",
        mail_backend="console",
        from_email=from_email,
        proxy_hops=1 if behind_proxy else 0,
    )
    config_file.write_text(text, encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(config_file, 0o600)
    click.echo(f"\nWrote {config_file}")

    from copydesk import migrate, seed
    from copydesk.app import create_app
    from copydesk.db import db
    from copydesk.views.setup import create_admin

    app = create_app(load_config(config_file))
    with app.app_context():
        migrate.upgrade(db.engine)
        seed.seed(site_name)
        from copydesk import settings

        settings.set_value("site.name", site_name)
        settings.set_value("site.mode", mode)
        create_admin(email=admin_email, name=admin_name, password=admin_password)
        db.session.commit()
    click.echo("Created the database and your administrator account.")
    click.secho("\nDone! Next steps:", bold=True, fg="green")
    click.echo(f"  1. Start it:        quillsail serve   (then open {base_url})")
    click.echo("  2. Set up email:    open Settings -> Email to connect Gmail, Outlook, or an SMTP server.")
    click.echo("  3. Go live:         see docs/installation.md for running it on a server.")


# --------------------------------------------------------------------------- running


@main.command()
@click.option("--data-dir", type=click.Path(file_okay=False, path_type=Path), help="Use a separate desktop publication folder.")
@pass_context
def desktop(ctx, data_dir):
    """Open the desktop launcher and start a local publication in your browser."""
    from copydesk.desktop_ui import run

    try:
        if data_dir and ctx.instance_id:
            raise click.UsageError("Choose --data-dir or --instance, rather than both.")
        run(data_dir=data_dir, instance_id=ctx.instance_id)
    except (ConfigError, OSError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("quit")
def quit_command():
    """Quit the desktop app and stop the publications it started."""
    from copydesk.instances import default_registry_dir
    from copydesk.launcher import send_command, wait_until_closed

    folder = default_registry_dir()
    if send_command(folder, "quit") != "ok":
        raise click.ClickException("QuillSail isn't open.")
    click.echo("Finishing background work and stopping publications…")
    if not wait_until_closed(folder, timeout=120):
        raise click.ClickException("QuillSail is still stopping. Check its window, then try again.")
    click.echo("QuillSail has quit. Your content is saved.")


@main.group("instance")
def instance_commands():
    """Create, list, delete and run independent local publications."""


@instance_commands.command("list")
@click.option("--json", "as_json", is_flag=True, help="Print names, paths and running addresses as JSON.")
def instance_list(as_json):
    from copydesk.instances import InstanceRegistry, running_url

    try:
        rows = [{"id": row.id, "name": row.name, "directory": str(row.root), "url": running_url(row)}
                for row in InstanceRegistry().list()]
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(json.dumps(rows, indent=2))
    else:
        for row in rows:
            click.echo(f"{row['id']} · {row['name']} · {row['url'] or 'Stopped'}\n  {row['directory']}")


@instance_commands.command("create")
@click.argument("name")
@click.option("--data-dir", type=click.Path(file_okay=False, path_type=Path), help="Use an empty folder instead of the managed data folder.")
def instance_create(name, data_dir):
    """Create a private publication. Complete its account setup in the browser."""
    from copydesk.instances import InstanceRegistry

    try:
        item = InstanceRegistry().add(name, data_dir)
    except (ConfigError, OSError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Created {item.id}: {item.root}\nStart and set it up: quillsail instance run {item.id}")


@instance_commands.command("add")
@click.argument("name")
@click.argument("data_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def instance_add(name, data_dir):
    """Register an existing desktop publication without changing its data."""
    from copydesk.instances import InstanceRegistry

    try:
        item = InstanceRegistry().add(name, data_dir, existing=True)
    except (ConfigError, OSError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Registered {item.id}: {item.root}")


@instance_commands.command("delete")
@click.argument("name")
@click.option("--delete-data", is_flag=True, help="Permanently delete the publication folder and all its contents.")
@click.option("--yes", is_flag=True, help="Skip the confirmation prompt.")
def instance_delete(name, delete_data, yes):
    """Remove a stopped instance, including default. Keep files unless --delete-data is used."""
    from copydesk.instances import InstanceRegistry

    try:
        registry = InstanceRegistry()
        item = registry.get(name)
        action = "Permanently delete all publication files in" if delete_data else "Remove from the instance list, keeping files in"
        if not yes:
            click.confirm(f"{action} {item.root}?", abort=True)
        registry.delete(name, delete_data=delete_data)
    except (ConfigError, OSError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Deleted instance {item.id}. " + ("Publication files permanently deleted." if delete_data else f"Files kept in {item.root}."))


@instance_commands.command("run")
@click.argument("names", nargs=-1, required=True)
@click.option("--no-browser", is_flag=True, help="Print local setup/dashboard links without opening a browser.")
@click.option("--no-worker", is_flag=True, help="Run websites without processing background jobs.")
def instance_run(names, no_browser, no_worker):
    """Run one or more instances until Ctrl+C; each gets an available local port."""
    from copydesk.desktop import DesktopRuntime
    from copydesk.instances import InstanceRegistry, running_url

    runtimes = []
    stopped = Event()
    previous = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda *_args: stopped.set())
    try:
        registry = InstanceRegistry()
        selected = [registry.get(name) for name in dict.fromkeys(names)]
        for item in selected:
            url = running_url(item)
            if url:
                click.echo(f"{item.id} is already running: {url}/dashboard/")
                continue
            runtime = DesktopRuntime(item.root)
            runtimes.append(runtime)
            runtime.start(with_worker=not no_worker)
            launch = runtime.launch_url()
            click.echo(f"{item.id}: {runtime.url}\nOpen setup/dashboard: {launch}")
            if not no_browser:
                webbrowser.open(launch)
        if runtimes:
            click.echo("Press Ctrl+C to stop these instances. Their content stays saved.")
            while not stopped.wait(.5):
                pass
    except KeyboardInterrupt:
        pass
    except (ConfigError, OSError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        for runtime in reversed(runtimes):
            runtime.stop()
        signal.signal(signal.SIGTERM, previous)


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=5000, show_default=True, type=int)
@click.option("--no-worker", is_flag=True, help="Don't run the background worker in this process.")
@click.option("--no-reload", is_flag=True, help="Don't restart when code changes.")
@pass_context
def serve(ctx: Context, host, port, no_worker, no_reload):
    """Run a development server. For production, use gunicorn (see docs/installation.md)."""
    app = ctx.app()
    reloading = not no_reload
    if not no_worker and (not reloading or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        from copydesk.jobs import start_background_worker

        start_background_worker(app)
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        click.secho(f"QuillSail {__version__} running at http://{host}:{port}", fg="green")
        if app.extensions["copydesk"].config.base_url != f"http://{host}:{port}":
            click.echo(f"(Links in emails use base_url: {app.extensions['copydesk'].config.base_url})")
    app.run(host=host, port=port, debug=app.debug, use_reloader=reloading)


@main.command()
@click.option("--poll", default=2.0, show_default=True, help="Seconds to wait between checks when idle.")
@pass_context
def worker(ctx: Context, poll):
    """Send email and do other background work. Keep this running (systemd, Docker or supervisor)."""
    from copydesk.jobs import Worker

    instance = Worker(ctx.app(), poll_interval=poll)
    instance.install_signal_handlers()
    click.echo("Worker started. Press Ctrl+C to stop.")
    instance.run()


@main.group()
def jobs():
    """Background jobs: run, list and retry."""


@jobs.command("run")
@click.option("--max-jobs", type=int, help="Stop after this many jobs.")
@click.option("--max-time", "max_seconds", type=float, default=55, show_default=True,
              help="Stop after this many seconds (fits a once-a-minute cron job).")
@pass_context
def jobs_run(ctx: Context, max_jobs, max_seconds):
    """Process waiting jobs, then exit. Good for cron: * * * * * quillsail jobs run"""
    from copydesk.jobs import run_pending

    with ctx.app().app_context():
        count = run_pending(max_jobs=max_jobs, max_seconds=max_seconds)
    click.echo(f"Ran {count} job{'s' if count != 1 else ''}.")


@jobs.command("list")
@click.option("--status", type=click.Choice(["queued", "running", "failed", "done"]), default="queued")
@pass_context
def jobs_list(ctx: Context, status):
    """Show jobs with a given status."""
    from sqlalchemy import select

    from copydesk.db import db
    from copydesk.models import Job

    with ctx.app().app_context():
        rows = db.session.scalars(select(Job).where(Job.status == status).order_by(Job.run_at).limit(200)).all()
        if not rows:
            click.echo(f"No {status} jobs.")
        for job in rows:
            error = (job.last_error or "").strip().splitlines()[-1:] or [""]
            click.echo(f"#{job.id:<6} {job.kind:<16} tries {job.attempts}/{job.max_attempts}  {job.run_at:%Y-%m-%d %H:%M}  {error[0][:80]}")


@jobs.command("retry-failed")
@pass_context
def jobs_retry(ctx: Context):
    """Queue every failed job to run again."""
    from sqlalchemy import update

    from copydesk.db import db
    from copydesk.models import Job
    from copydesk.utils import utcnow

    with ctx.app().app_context():
        result = db.session.execute(
            update(Job).where(Job.status == "failed").values(status="queued", attempts=0, run_at=utcnow(), finished_at=None)
        )
        db.session.commit()
    click.echo(f"Re-queued {result.rowcount} job(s).")


# --------------------------------------------------------------------------- maintenance


@main.command()
@pass_context
def upgrade(ctx: Context):
    """Create or update the database tables. Run after every QuillSail upgrade."""
    from copydesk import migrate, seed
    from copydesk.db import db

    app = ctx.app()
    with app.app_context():
        before = migrate.current_revision(db.engine)
        migrate.upgrade(db.engine)
        seed.seed()
        after = migrate.current_revision(db.engine)
    if before == after:
        click.echo(f"The database is up to date (revision {after}).")
    else:
        click.echo(f"Database updated: {before or 'empty'} -> {after}.")


@main.command()
@click.option("--smtp", is_flag=True, help="Also connect and sign in to the mail server.")
@click.option("--send-test", metavar="EMAIL", help="Send a test email to this address (needs a running worker or --now).")
@click.option("--now", is_flag=True, help="With --send-test, send immediately instead of queueing.")
@pass_context
def check(ctx: Context, smtp, send_test, now):
    """Check the configuration, database, folders and email settings."""
    from copydesk import migrate
    from copydesk.db import db
    from copydesk.email_connections import effective_mail_config
    from copydesk.mail import Email, Mailer, MailError, check_connection

    app = ctx.app()
    config = app.extensions["copydesk"].config
    problems = 0

    def report(ok: bool, message: str, fix: str = "") -> None:
        nonlocal problems
        click.echo(("  " + click.style("ok", fg="green") if ok else "  " + click.style("!!", fg="red")) + f"  {message}")
        if not ok:
            problems += 1
            if fix:
                click.echo(f"      {fix}")

    click.secho(f"QuillSail {__version__}", bold=True)
    click.echo(f"  Config file: {config.path or '(environment variables only)'}")
    click.echo(f"  Site address: {config.base_url}")
    with app.app_context():
        try:
            pending = migrate.needs_upgrade(db.engine)
            report(not pending, f"Database ({db.engine.dialect.name}) is reachable"
                   + (" and up to date" if not pending else " but needs updating"),
                   "Run `quillsail upgrade`.")
        except Exception as exc:  # noqa: BLE001
            report(False, f"Can't reach the database: {exc}", "Check [database] url in copydesk.toml.")
        for label, path in (("Uploads folder", config.uploads_dir), ("Data folder", config.data_dir)):
            path.mkdir(parents=True, exist_ok=True)
            report(os.access(path, os.W_OK), f"{label} is writable ({path})", "Fix the folder's permissions.")
        report(config.base_url.startswith("https://") or config.debug,
               "Site address uses HTTPS", "Use https:// in base_url for a public site.")
        active_mail = effective_mail_config()
        report(active_mail.backend in {"smtp", "gmail", "outlook"}, f"Email backend is {active_mail.backend}",
               "Set [mail] backend = \"smtp\" to send real email.")
        from copydesk import settings

        for kind, status in settings.get("hosting.email_checks", {}).items():
            report(status == "Found", f"{kind} DNS: {status}")
        if smtp:
            problem = check_connection()
            report(problem is None, "Connected to the mail server" if problem is None else problem)
        if send_test:
            from copydesk import notify, settings

            email = Email(to=send_test, subject=f"Test email from {settings.get('site.name')}",
                          text="If you can read this, QuillSail can send email.", from_name=settings.get("site.name"))
            if now:
                try:
                    with Mailer() as mailer:
                        mailer.send(email)
                    report(True, f"Sent a test email to {send_test}")
                except MailError as exc:
                    report(False, f"Couldn't send the test email: {exc}")
            else:
                notify.queue(email)
                db.session.commit()
                report(True, f"Queued a test email to {send_test} (a worker will send it)")
    if problems:
        click.secho(f"\n{problems} thing(s) to look at.", fg="yellow")
        sys.exit(1)
    click.secho("\nEverything looks good.", fg="green")


@main.command()
@click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
@pass_context
def demo(ctx: Context, yes):
    """Fill an EMPTY test site with sample writers, articles and an issue."""
    from copydesk import demo as demo_content

    if not yes:
        click.confirm("Add made-up sample content? Only do this on a test site.", abort=True)
    with ctx.app().app_context():
        try:
            result = demo_content.run()
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc
    click.echo(f"Added {result['people']} sample people and {result['articles']} articles. "
               "Sample accounts use the password demo-password-123.")


# --------------------------------------------------------------------------- users


@main.group()
def user():
    """Manage accounts from the command line."""


@user.command("create")
@click.option("--email", required=True)
@click.option("--name", required=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--group", "group_slugs", multiple=True, help="Group to add them to (repeatable), e.g. --group editors")
@click.option("--admin", is_flag=True, help="Make them an administrator.")
@pass_context
def user_create(ctx: Context, email, name, password, group_slugs, admin):
    """Create a confirmed account."""
    from sqlalchemy import select

    from copydesk.auth import hash_password, password_problem, suggest_username
    from copydesk.db import db
    from copydesk.models import Group, GroupMembership, User
    from copydesk.utils import normalize_email, utcnow

    email = normalize_email(email)
    problem = password_problem(password, email)
    if problem:
        raise click.ClickException(problem)
    with ctx.app().app_context():
        if db.session.scalar(select(User.id).where(User.email == email)):
            raise click.ClickException("There's already an account with that email.")
        account = User(email=email, display_name=name, username=suggest_username(name, email),
                       password_hash=hash_password(password), email_verified_at=utcnow())
        db.session.add(account)
        db.session.flush()
        slugs = set(group_slugs) | ({"admins", "editors"} if admin else set())
        for slug in slugs:
            group = db.session.scalar(select(Group).where(Group.slug == slug))
            if group is None:
                raise click.ClickException(f"No group called {slug!r}.")
            db.session.add(GroupMembership(user=account, group=group, status="active", source="admin"))
        db.session.commit()
        click.echo(f"Created {account.username} ({email}){' in ' + ', '.join(sorted(slugs)) if slugs else ''}.")


@user.command("set-password")
@click.argument("email")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@pass_context
def user_set_password(ctx: Context, email, password):
    """Set someone's password (and sign them out everywhere)."""
    from sqlalchemy import select

    from copydesk.auth import hash_password, password_problem
    from copydesk.db import db
    from copydesk.models import User
    from copydesk.utils import normalize_email

    problem = password_problem(password, email)
    if problem:
        raise click.ClickException(problem)
    with ctx.app().app_context():
        account = db.session.scalar(select(User).where(User.email == normalize_email(email)))
        if account is None:
            raise click.ClickException("No account with that email.")
        account.password_hash = hash_password(password)
        account.auth_version += 1
        db.session.commit()
    click.echo("Password changed.")


@user.command("add-group")
@click.argument("email")
@click.argument("group_slug")
@pass_context
def user_add_group(ctx: Context, email, group_slug):
    """Put someone in a group, e.g.: quillsail user add-group ada@example.edu editors"""
    from sqlalchemy import select

    from copydesk import groups
    from copydesk.db import db
    from copydesk.models import Group, User
    from copydesk.utils import normalize_email

    with ctx.app().app_context():
        account = db.session.scalar(select(User).where(User.email == normalize_email(email)))
        group = db.session.scalar(select(Group).where(Group.slug == group_slug))
        if account is None or group is None:
            raise click.ClickException("No such account or group.")
        groups.add(account, group, actor=None)
        db.session.commit()
    click.echo(f"Added {email} to {group_slug}.")


@user.command("list")
@pass_context
def user_list(ctx: Context):
    """List accounts and their groups."""
    from sqlalchemy import select

    from copydesk.db import db
    from copydesk.models import User

    with ctx.app().app_context():
        for account in db.session.scalars(select(User).where(User.deleted_at.is_(None)).order_by(User.id)).all():
            groups_text = ", ".join(m.group.slug for m in account.active_memberships)
            flags = "" if account.is_active else " [blocked]"
            flags += "" if account.is_verified else " [unconfirmed]"
            click.echo(f"{account.id:>5}  {account.email:<36} {account.display_name:<24} {groups_text}{flags}")


# --------------------------------------------------------------------------- subscribers


@main.group()
def subscribers():
    """Import and export the subscriber list."""


@subscribers.command("import")
@click.argument("csv_file", type=click.File("r", encoding="utf-8-sig"))
@click.option("--confirmed", is_flag=True,
              help="Subscribe everyone straight away. Only if they already agreed to get this newsletter.")
@pass_context
def subscribers_import(ctx: Context, csv_file, confirmed):
    """Import a CSV with an "email" column (and optional "name" and "groups")."""
    from copydesk.db import db
    from copydesk.views.dashboard.subscribers import import_csv

    app = ctx.app()
    with app.test_request_context():
        result = import_csv(csv_file.read(), confirmed=confirmed)
        if result["error"]:
            raise click.ClickException(result["error"])
        db.session.commit()
    click.echo(f"Added {result['added']}, skipped {result['existing']} already subscribed, {result['invalid']} invalid.")
    for problem in result["problems"]:
        click.echo(f"  {problem}")


@subscribers.command("export")
@click.option("--status", default="active", show_default=True,
              type=click.Choice(["active", "pending", "unsubscribed", "bounced", "all"]))
@click.option("--output", "-o", type=click.File("w", encoding="utf-8"), default="-")
@pass_context
def subscribers_export(ctx: Context, status, output):
    """Write subscribers as CSV."""
    from sqlalchemy import select

    from copydesk.db import db
    from copydesk.models import Subscriber

    with ctx.app().app_context():
        stmt = select(Subscriber).order_by(Subscriber.created_at)
        if status != "all":
            stmt = stmt.where(Subscriber.status == status)
        writer = csv.writer(output)
        writer.writerow(["email", "name", "status", "groups", "subscribed_at", "confirmed_at", "source"])
        for sub in db.session.scalars(stmt).all():
            writer.writerow([sub.email, sub.name, sub.status, ", ".join(g.slug for g in sub.groups),
                             sub.created_at.isoformat(), sub.confirmed_at.isoformat() if sub.confirmed_at else "",
                             sub.source])


# --------------------------------------------------------------------------- backup


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Can't save {type(value).__name__} as JSON")


@main.command("export")
@click.argument("output", type=click.File("w", encoding="utf-8"))
@pass_context
def export_data(ctx: Context, output):
    """Save every table as JSON (a database-independent backup)."""
    from sqlalchemy import select

    from copydesk import migrate
    from copydesk.db import Base, db

    with ctx.app().app_context():
        data = {"copydesk": __version__, "revision": migrate.current_revision(db.engine), "tables": {}}
        for table in Base.metadata.sorted_tables:
            rows = db.session.execute(select(table)).mappings().all()
            data["tables"][table.name] = [dict(row) for row in rows]
        json.dump(data, output, default=_json_default, ensure_ascii=False)
    total = sum(len(rows) for rows in data["tables"].values())
    click.echo(f"Exported {total} rows from {len(data['tables'])} tables. Remember to back up the uploads folder too.",
               err=True)


@main.command("import")
@click.argument("source", type=click.File("r", encoding="utf-8"))
@click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
@pass_context
def import_data(ctx: Context, source, yes):
    """Load a JSON export into an EMPTY database (e.g. to move from SQLite to PostgreSQL)."""
    from sqlalchemy import Date, DateTime, func, insert, select

    from copydesk import migrate
    from copydesk.db import Base, db
    from copydesk.models import User

    data = json.load(source)
    app = ctx.app()
    with app.app_context():
        migrate.upgrade(db.engine)
        if db.session.scalar(select(func.count()).select_from(User)):
            raise click.ClickException("The database already has accounts. Import only into an empty database.")
        # Migration 0007 initializes an installation identity in an otherwise
        # empty database. This metadata alone must not block a real restore.
        if any(db.session.scalar(select(func.count()).select_from(table).where(
            table.c.key != "system.instance_id") if table.name == "settings" else
            select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables):
            raise click.ClickException("The database already contains data. Import only into an empty database.")
        if not yes:
            click.confirm(f"Import data exported from QuillSail {data.get('copydesk')}?", abort=True)
        for table in Base.metadata.sorted_tables:
            rows = data.get("tables", {}).get(table.name, [])
            if not rows:
                continue
            db.session.execute(table.delete())
            datetime_columns = [c.name for c in table.columns if isinstance(c.type, DateTime)]
            date_columns = [c.name for c in table.columns if isinstance(c.type, Date)]
            for row in rows:
                for name in datetime_columns:
                    if row.get(name):
                        row[name] = datetime.fromisoformat(row[name])
                for name in date_columns:
                    if row.get(name):
                        row[name] = date.fromisoformat(row[name])
            db.session.execute(insert(table), rows)
        from copydesk.domains import instance_id

        instance_id()
        db.session.commit()
        if db.engine.dialect.name == "postgresql":
            from sqlalchemy import text

            for table in Base.metadata.sorted_tables:
                identity = table.autoincrement_column
                if identity is not None and identity.name == "id":
                    db.session.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table.name}), 1))"
                    ))
            db.session.commit()
    click.echo("Import complete. Copy the uploads folder across too.")


@main.command("import-jekyll")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, help="Report what would happen, and change nothing.")
@click.option("--as-drafts", is_flag=True, help="Bring every post in as a draft instead of publishing it.")
@click.option("--author", "author_name", help="Username or email of the account that owns the import. Default: the first administrator.")
@click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
@pass_context
def import_jekyll(ctx: Context, source, dry_run, as_drafts, author_name, yes):
    """Bring in a Jekyll blog from its source folder or a zip of it.

    Liquid and plugins are never run. Importing fires no webhooks and sends no email, and
    it's safe to repeat: posts that were already imported are skipped. Old post addresses
    redirect to the new ones, once this site answers on the old domain.
    """
    import tempfile

    from sqlalchemy import select

    from copydesk import jekyll_import, migrate
    from copydesk.db import db
    from copydesk.models import ADMINS, Group, GroupMembership, User

    app = ctx.app()
    with app.test_request_context(), tempfile.TemporaryDirectory() as temporary:
        migrate.upgrade(db.engine)
        folder = source
        try:
            if source.is_file():
                folder = Path(temporary) / "site"
                limit = app.extensions["copydesk"].config.max_import_mb * 1024 * 1024 * jekyll_import.MAX_ZIP_EXPANSION
                jekyll_import.extract_zip(source, folder, max_unpacked=limit)
            plan = jekyll_import.plan_import(folder)
        except jekyll_import.ImportError_ as exc:
            raise click.ClickException(str(exc)) from exc

        counts = plan.counts()
        click.echo(f"{plan.site_title or 'This site'}: {counts['posts']} posts found.")
        click.echo(f"  {counts['published']} to publish, {counts['drafts']} as drafts, "
                   f"{counts['already_imported']} already imported, {counts['images']} images to upload.")
        for post in plan.posts:
            state = "already imported" if post.already_imported else ("draft" if as_drafts else post.status)
            click.echo(f"\n{post.title}  [{state}]")
            click.echo(f"  {post.source} -> {post.new_path}")
            for path in post.old_paths:
                click.echo(f"  redirects from {path}")
            for note in post.notes:
                click.echo(f"  ! {note}")
        for item in plan.skipped:
            click.echo(f"\nSkipped {item['file']}: {item['reason']}")
        if plan.new_sections:
            click.echo(f"\nNew sections: {', '.join(plan.new_sections)}")
        if plan.unmatched_authors:
            click.echo(f"\nNo account found for: {', '.join(plan.unmatched_authors)}. "
                       "Their posts will be credited to the account running the import.")
        click.echo(f"\n{counts['needs_review']} posts need a look after importing (marked with !).")
        if dry_run:
            click.echo("This was a dry run. Nothing was changed.")
            return
        if not counts["new"]:
            click.echo("There's nothing new to import.")
            return

        if author_name:
            lowered = author_name.strip().lower()
            actor = db.session.scalar(select(User).where(
                (User.username == author_name) | (User.email == lowered), User.deleted_at.is_(None)
            ))
            if actor is None:
                raise click.ClickException(f"There's no account called {author_name}.")
        else:
            actor = db.session.scalar(
                select(User)
                .join(GroupMembership, GroupMembership.user_id == User.id)
                .join(Group, GroupMembership.group_id == Group.id)
                .where(Group.slug == ADMINS, User.deleted_at.is_(None)).order_by(User.id).limit(1)
            )
            if actor is None:
                raise click.ClickException("There's no administrator yet. Name an account with --author.")
        if not yes:
            click.confirm(f"Import {counts['new']} posts as {actor.display_name}?", abort=True)
        result = jekyll_import.run_import(plan, actor, as_drafts=as_drafts)
        from copydesk import audit

        audit.record(
            "article.imported_site", None, actor=db.session.get(User, actor.id), label=plan.site_title or "a Jekyll site",
            details={"imported": len(result.imported), "skipped": result.skipped, "failed": len(result.failed)},
        )
        db.session.commit()
    click.echo(f"Imported {len(result.imported)} posts and {result.images} images. Skipped {result.skipped}.")
    for failure in result.failed:
        click.echo(f"  Couldn't import {failure['file']}: {failure['reason']}", err=True)
    if result.failed:
        raise SystemExit(1)


# --------------------------------------------------------------------------- extensions


class ExtensionCommands(click.Group):
    """Commands that extensions add, found by loading the app."""

    def _commands(self, ctx: click.Context) -> dict:
        context = ctx.find_object(Context)
        if context is None:
            return {}
        try:
            app = context.app()
        except click.ClickException:
            return {}
        commands = {}
        for name, extension in app.extensions["copydesk"].extensions.items():
            for command in extension.commands:
                commands[f"{name}:{command.name}"] = command
        return commands

    def list_commands(self, ctx):
        return sorted(self._commands(ctx))

    def get_command(self, ctx, name):
        command = self._commands(ctx).get(name)
        if command is None:
            return None
        app = ctx.find_object(Context).app()
        callback = command.callback

        def run_in_app(*args, **kwargs):
            with app.app_context():
                return callback(*args, **kwargs)

        return click.Command(command.name, params=command.params, callback=run_in_app, help=command.help)


@main.group(cls=ExtensionCommands)
def ext():
    """Commands added by extensions, named extension:command."""


@main.group()
def tunnel():
    """Run a connected Cloudflare tunnel on a server."""


@tunnel.command('run')
@pass_context
def tunnel_run(ctx):
    """Run the tunnel with encrypted credentials and automatic restart."""
    import signal

    from copydesk import cloudflare
    from copydesk.db import db
    from copydesk.tunnel import Tunnel, binary

    app = ctx.app()
    with app.app_context():
        row, data = cloudflare.connection()
        if row.status in {'disconnecting', 'authorization_required'} or not data.get('tunnel_token'):
            raise click.ClickException('Finish connecting a domain in the dashboard first.')
        from copydesk.desktop import InstanceLock
        from copydesk.models import HostingConnection

        lock = InstanceLock(app.extensions['copydesk'].config.data_dir / 'tunnel.lock')
        lock.acquire()
        process = None
        try:
            process = Tunnel(binary(app.extensions['copydesk'].config.data_dir), data['tunnel_token'])
            signal.signal(signal.SIGTERM, lambda *_: process.stop_event.set())
            signal.signal(signal.SIGINT, lambda *_: process.stop_event.set())
            process.start()
            while process.thread.is_alive() and not process.stop_event.wait(2):
                db.session.rollback()
                db_row = db.session.get(HostingConnection, 1, populate_existing=True)
                if db_row is None or db_row.status in {'disconnecting', 'authorization_required'}:
                    break
        finally:
            if process:
                process.stop()
            lock.release()



if __name__ == "__main__":  # pragma: no cover
    main()
