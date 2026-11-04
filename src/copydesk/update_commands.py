"""The shared desktop/server update interface; deployment policy lives outside Click."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click

from copydesk import __version__
from copydesk.updater import UpdateError


def profile_path(value=None):
    from copydesk.server_update import DEFAULT_PROFILE

    return Path(value or os.environ.get("COPYDESK_UPDATE_PROFILE", DEFAULT_PROFILE)).expanduser()


def server_controller(value=None):
    from copydesk.server_update import ServerProfile, ServerUpdater

    path = profile_path(value)
    if not path.exists():
        raise UpdateError("Run quillsail update setup once to register this server. Afterwards, quillsail update manages the entire deployment.")
    profile = ServerProfile.load(path)
    if profile.kind == "python":
        # All mutating entry points must survive changing the current symlink,
        # including recovery and manual rollback.
        prefix = Path(sys.prefix).absolute()
        resolved = prefix.resolve()
        if prefix != resolved and not os.environ.get("QUILLSAIL_UPDATE_REAL_RUNTIME"):
            environment = {**os.environ, "QUILLSAIL_UPDATE_REAL_RUNTIME": "1"}
            python = resolved / "bin/python"
            # -I: "-m" would otherwise import copydesk from the working directory.
            os.execve(python, [str(python), "-I", "-m", "copydesk", *sys.argv[1:]], environment)
    return ServerUpdater(profile)


def desktop_update(check_only, app, channel, yes):
    from copydesk.update_install import (
        application_lock,
        atomic_install,
        read_install,
        record_success,
    )
    from copydesk.updater import (
        UpdateClient,
        install_lock_path,
        installation_path,
        launch_installer,
    )

    installation = installation_path(app) if app is not None or getattr(sys, "frozen", False) else None
    installed = read_install(installation) if installation else None
    current = installed["version"] if installed else __version__
    client = UpdateClient()
    result = client.check(channel=channel, current=current, target=installed["target"] if installed else None)
    if not result.available:
        click.echo(f"QuillSail {current} is up to date on the {channel} channel.")
        return
    click.echo(f"QuillSail {result.version} is available (installed: {current}).")
    click.echo(result.release_url)
    if check_only:
        return
    if installation is None:
        raise UpdateError("Use --app with the desktop application folder, or run quillsail update setup for a server.")
    if getattr(sys, "frozen", False):
        # Terminal instances run from the same app files that this update replaces.
        from copydesk.instances import InstanceRegistry, running_url

        if running := [row.id for row in InstanceRegistry().list() if running_url(row)]:
            raise UpdateError(f"Stop these instances before updating: {', '.join(running)}. Use quillsail instance stop --all, or quit QuillSail.")
    if not yes:
        click.confirm("Download the verified update and replace the desktop app? Close all QuillSail windows first", abort=True)
    click.echo("Downloading and verifying the update…")
    if not getattr(sys, "frozen", False):
        with application_lock(install_lock_path(installation)):
            plan = client.prepare(result, installation, restart=False)
        details = json.loads(plan.read_text(encoding="utf-8"))
        installed = atomic_install(details)
        record_success(details, installed)
        click.echo(f"Installed QuillSail {result.version}. Open the desktop application to continue.")
    else:
        plan = client.prepare(result, installation, restart=False)
        launch_installer(plan)
        click.echo("Update prepared. The installer will replace the app after this command exits.")
        click.echo(f"Installation result: {plan.parent / 'result.json'}")


@click.group("update", invoke_without_command=True)
@click.option("--check", "check_only", is_flag=True, help="Check availability without changing the installation.")
@click.option("--app", type=click.Path(path_type=Path, exists=True, file_okay=False), help="Desktop application folder.")
@click.option("--desktop", is_flag=True, help="Check desktop releases rather than server packages.")
@click.option("--profile", type=click.Path(path_type=Path), help="Registered server update profile.")
@click.option("--resume", is_flag=True, help="Recover or finish an interrupted server update.")
@click.option("--channel", type=click.Choice(["stable", "beta"]), help="Override the registered update channel.")
@click.option("--yes", "-y", is_flag=True, help="Approve the update without an interactive confirmation.")
@click.pass_context
def update(ctx, check_only, app, desktop, profile, resume, channel, yes):
    """Update a desktop app or a registered Python/Compose server.

    Servers: run 'quillsail update setup' once, then 'quillsail update'. The
    command verifies the release, prepares it, backs up, migrates, activates,
    checks web/worker health and recovers failures. No mail test is sent.
    """
    if ctx.invoked_subcommand:
        return
    from copydesk.config import ConfigError
    from copydesk.update_install import InstallError
    from copydesk.updater import UpdateClient

    try:
        is_desktop = app is not None or desktop or getattr(sys, "frozen", False)
        if is_desktop:
            if profile or resume:
                raise click.UsageError("--profile and --resume apply to server installations.")
            from copydesk.updater import saved_channel

            desktop_update(check_only, app, channel or saved_channel(), yes)
            return
        if resume:
            if check_only:
                raise click.UsageError("Choose either --check or --resume.")
            state = server_controller(profile).execute(resume=True)
            click.echo("Recovery state: " + (state["stage"] if state else "no interrupted update"))
            return
        path = profile_path(profile)
        controller = server_controller(path) if path.exists() else None
        channel = channel or (controller.profile.values.get("channel", "beta") if controller else "beta")
        current = controller.deployment.version() if controller else __version__
        client = controller.client if controller else UpdateClient()
        release = client.check(channel=channel, target="server", current=current)
        if not release.available:
            click.echo(f"QuillSail {current} is up to date on the {channel} channel.")
            return
        click.echo(f"QuillSail {release.version} is available (installed: {current}).")
        click.echo(release.release_url)
        if check_only:
            return
        if controller is None:
            raise UpdateError("Run quillsail update setup once to register the server before installing updates.")
        if not yes:
            click.confirm("Install this verified server update? The site will briefly enter maintenance mode; a matching backup and recovery record will be saved", abort=True)
        controller.report = click.echo
        state = controller.execute(release)
        click.echo(f"Installed QuillSail {release.version}; web and worker checks passed.")
        click.echo(f"Recovery record: {state['transaction']}")
    except (UpdateError, InstallError, ConfigError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


@update.command("channel")
@click.argument("choice", required=False, type=click.Choice(["stable", "beta"]))
def update_channel(choice):
    """Show or choose the channel that desktop updates come from."""
    from copydesk.updater import save_channel, saved_channel

    try:
        if choice:
            save_channel(choice)
    except (UpdateError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Update channel: {choice or saved_channel()}")


@update.command("capabilities")
def capabilities():
    """Report the updater/maintenance contract without loading an instance."""
    click.echo(json.dumps({"version": __version__, "server_update_protocol": 1, "maintenance_gate": True,
                           "desktop_updates": True, "server_updates": ["python", "compose"], "system_command": True}))


@update.command("status")
@click.option("--profile", type=click.Path(path_type=Path))
def status(profile):
    """Show the installed server version and its latest transaction state."""
    try:
        controller = server_controller(profile)
        state = controller.state()
        click.echo(json.dumps({"version": controller.deployment.version(), "kind": controller.profile.kind,
                               "stage": state["stage"] if state else "idle",
                               "recovery_record": state["transaction"] if state else None}, indent=2))
    except (UpdateError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


@update.command("rollback")
@click.option("--profile", type=click.Path(path_type=Path))
@click.option("--yes", "-y", is_flag=True)
@click.option("--acknowledge-mail-replay", is_flag=True, help="Acknowledge that restored pending jobs may resend mail already delivered since the snapshot.")
def rollback(profile, yes, acknowledge_mail_replay):
    """Restore the last matching app/database backup, preserving current data first."""
    try:
        if not acknowledge_mail_replay:
            raise UpdateError("Restoring an older database may queue previously delivered mail again. Review its snapshot and delivery history first, then pass --acknowledge-mail-replay to authorize this recovery. Nothing was changed.")
        controller = server_controller(profile)
        if not yes:
            click.confirm("Restore the previous application AND its database snapshot? Content received since that update will first be saved in a separate recovery backup", abort=True)
        controller.report = click.echo
        state = controller.rollback()
        click.echo("Recovery complete: " + state["transaction"])
    except (UpdateError, OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


@update.command("bootstrap")
@click.option("--profile", type=click.Path(path_type=Path))
@click.option("--wheel", required=True, type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--sha256", "expected", required=True, help="Checksum obtained with the trusted first-install package.")
@click.option("--yes", "-y", is_flag=True)
def bootstrap(profile, wheel, expected, yes):
    """One-time/offline installation of an explicitly checksum-pinned server wheel.

    This is an operator-provided installer, not an unsigned network fallback.
    Normal future updates authenticate their release metadata with TUF.
    """
    import hashlib
    import re
    import shutil
    import zipfile
    from email.parser import BytesParser

    from packaging.version import Version

    from copydesk.server_update import sha256
    from copydesk.updater import Update

    try:
        if not re.fullmatch(r"[a-f0-9]{64}", expected) or wheel.is_symlink() or sha256(wheel) != expected:
            raise UpdateError("The local installer does not match the operator-provided SHA-256 checksum.")
        with zipfile.ZipFile(wheel) as archive:
            entries = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(entries) != 1:
                raise UpdateError("Choose a QuillSail Python wheel.")
            metadata = BytesParser().parsebytes(archive.read(entries[0]))
        version = metadata["Version"]
        if metadata["Name"] != "copydesk" or wheel.name != f"copydesk-{version}-py3-none-any.whl":
            raise UpdateError("The installer is not the expected portable QuillSail wheel.")
        controller = server_controller(profile)
        current = controller.deployment.version()
        if Version(version) <= Version(current):
            raise UpdateError("Bootstrap accepts newer versions only; use the recovery command for rollback.")
        if not yes:
            click.confirm(f"Install the checksum-pinned local QuillSail {version} package, back up this server, and activate it?", abort=True)

        class LocalInstaller:
            def download(self, update, destination):
                shutil.copyfile(wheel, destination)
                if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
                    raise UpdateError("The installer changed while it was being copied.")
                return destination

        controller.client = LocalInstaller()
        controller.report = click.echo
        update = Update(current, version, "server", "offline", wheel.name, wheel.stat().st_size, expected)
        state = controller.execute(update)
        click.echo(f"Server upgraded to QuillSail {version}. Recovery record: {state['transaction']}")
    except (UpdateError, OSError, ValueError, zipfile.BadZipFile) as exc:
        raise click.ClickException(str(exc)) from exc


@update.command("setup")
@click.option("--profile", type=click.Path(path_type=Path), default=None)
@click.option("--kind", type=click.Choice(["python", "compose"]), default="python", show_default=True)
@click.option("--install-root", type=click.Path(path_type=Path), default="/opt/copydesk", show_default=True)
@click.option("--instance-root", type=click.Path(path_type=Path))
@click.option("--backup-root", type=click.Path(path_type=Path), default="/var/backups/copydesk", show_default=True)
@click.option("--service-user", default="copydesk", show_default=True)
@click.option("--web-service", default="copydesk-web", show_default=True)
@click.option("--worker-service", default="copydesk-worker", show_default=True)
@click.option("--health-url")
@click.option("--compose-file", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--project", default="copydesk", show_default=True)
@click.option("--base-image", help="Pinned Python base image for Compose builds; setup resolves a supplied tag once.")
@click.option("--environment-file", "environment_files", multiple=True, type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.option("--backup-host", help="Host-reachable database address when container DNS differs.")
@click.option("--backup-port", type=int)
@click.option("--channel", type=click.Choice(["stable", "beta"]), default="beta", show_default=True)
@click.option("--command", "command_path", type=click.Path(path_type=Path), default="/usr/local/bin/quillsail", show_default=True, help="Stable server command; its directory must be on sudo's PATH.")
@click.option("--no-command", is_flag=True, help="Register without installing a system-wide command.")
@click.option("--yes", "-y", is_flag=True)
@click.pass_context
def setup(ctx, profile, kind, install_root, instance_root, backup_root, service_user, web_service,
          worker_service, health_url, compose_file, project, base_image, environment_files, backup_host, backup_port, channel, command_path, no_command, yes):
    """Register an existing deployment; preserve its configuration and services.

    Use the standard versioned Python/systemd layout, or register an existing
    Compose project. This command records settings without changing live code.
    """
    from copydesk.config import ENV_OVERRIDES, ConfigError, load_config
    from copydesk.server_command import command_target, plan, require_operator
    from copydesk.server_update import CommandRunner, ServerProfile, private_json, trusted_directory

    created_compose = None
    command_link = None
    try:
        require_operator()
        destination = profile_path(profile).absolute()
        trusted_directory(destination.parent)
        trusted_directory(install_root.absolute())
        if destination.exists():
            raise UpdateError("This profile already exists. Keep it for recovery; use a new profile path to register another deployment.")
        values = {"format": "quillsail.server-update.v1", "kind": kind, "install_root": str(install_root.absolute()),
                  "backup_root": str(backup_root.absolute()), "channel": channel,
                  "environment_files": [str(path.absolute()) for path in environment_files]}
        if backup_host:
            values.update(backup_host=backup_host, backup_port=backup_port)
        run = CommandRunner()
        if kind == "compose":
            if not compose_file:
                raise UpdateError("Provide --compose-file for the existing Compose project.")
            base = ["docker", "compose", "--project-name", project, "-f", str(compose_file.absolute())]
            for path in environment_files:
                base += ["--env-file", str(path.absolute())]
            normalized = json.loads(run([*base, "config", "--format", "json"]))
            container = run([*base, "ps", "-q", "web"]).strip()
            details = json.loads(run(["docker", "inspect", container]))[0]
            mount = next((item for item in details["Mounts"] if item["Destination"] == "/var/lib/copydesk"), None)
            if not mount:
                raise UpdateError("The Compose web service needs a persistent /var/lib/copydesk mount.")
            instance_root = instance_root or Path(mount["Source"])
            for name in ("web", "worker", "init"):
                service = normalized["services"][name]
                service.pop("build", None)
                service.pop("env_file", None)
                # The portable wheel supplies the container entry point and
                # worker validation, so avoid old image-specific script paths.
                if name == "worker":
                    service["healthcheck"] = {"disable": True}
            install_root.mkdir(parents=True, exist_ok=True)
            managed_compose = install_root / "managed-compose.json"
            if managed_compose.exists():
                raise UpdateError("A managed Compose configuration already exists in this installation root.")
            image = base_image or "python:3.13-slim"
            if "@sha256:" not in image:
                if not yes:
                    click.confirm(f"Resolve and pin the Python build image {image}?", abort=True)
                run(["docker", "pull", image])
                digests = json.loads(run(["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image]))
                image = digests[0]
            values.update(compose_file=str(managed_compose), compose_project=project, base_image=image,
                          container_root="/var/lib/copydesk", service_uid=10001, service_gid=10001)
        else:
            instance_root = instance_root or Path("/var/lib/copydesk")
            values.update(service_user=service_user, web_service=web_service, worker_service=worker_service)
        config_path = Path(ctx.obj.config_path) if ctx.obj.config_path else instance_root / "copydesk.toml"
        from dotenv import dotenv_values

        environment = {}
        for path in environment_files:
            environment.update(dotenv_values(path, interpolate=False))
        if kind == "compose":
            environment.update(normalized["services"]["web"].get("environment", {}))
        overrides = {}
        for key, value in environment.items():
            if key in ENV_OVERRIDES and value is not None:
                section, name = ENV_OVERRIDES[key]
                overrides.setdefault(section, {})[name] = value
        config = load_config(config_path, overrides=overrides, require_file=True, use_environment=False)
        values.update(instance_root=str(instance_root.absolute()), config=str(config_path.absolute()),
                      health_url=health_url or config.base_url.rstrip("/") + "/healthz")
        candidate = ServerProfile(destination, values)
        candidate.validate()
        if not no_command:
            command_link = plan(candidate, command_path)
            values.update(command_path=str(command_link.destination), command_target=str(command_link.target))
        if not yes:
            click.echo(json.dumps({key: values[key] for key in ("kind", "install_root", "instance_root", "backup_root", "health_url")}, indent=2))
            if command_link:
                click.echo(f"Server command: {command_link.destination} → {command_link.target}")
            click.confirm("Register this deployment for signed, backed-up updates?", abort=True)
        if kind == "compose":
            private_json(managed_compose, normalized)
            created_compose = managed_compose
        candidate.config()
        if command_link:
            command_link.install()
        private_json(destination, values)
        click.echo(f"Server registered: {destination}")
        future_command(command_link.destination if command_link else command_target(candidate), destination, on_path=bool(command_link))
    except (UpdateError, ConfigError, OSError, ValueError, KeyError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        if created_compose and not destination.exists():
            created_compose.unlink(missing_ok=True)
        if command_link and not destination.exists():
            command_link.undo()


def future_command(command, profile, *, on_path=False):
    import shlex

    from copydesk.server_update import DEFAULT_PROFILE

    arguments = ["sudo", Path(command).name if on_path else str(command), "update"]
    if Path(profile).resolve() != DEFAULT_PROFILE:
        arguments += ["--profile", str(profile)]
    click.echo("Future updates: " + shlex.join(arguments))


@update.command("install-command")
@click.option("--profile", type=click.Path(path_type=Path))
@click.option("--command", "command_path", type=click.Path(path_type=Path), help="Default: the registered command, or /usr/local/bin/quillsail.")
def install_command(profile, command_path):
    """Install or verify a stable command for an already registered server."""
    from copydesk.server_command import plan, require_operator
    from copydesk.server_update import ServerProfile, private_json

    command_link = None
    try:
        require_operator()
        registered = ServerProfile.load(profile_path(profile))
        command_link = plan(registered, command_path)
        command_link.install()
        private_json(registered.path, {**registered.values, "command_path": str(command_link.destination), "command_target": str(command_link.target)})
        click.echo(f"Server command ready: {command_link.destination}")
        future_command(command_link.destination, registered.path, on_path=True)
    except (UpdateError, OSError, ValueError) as exc:
        if command_link:
            command_link.undo()
        raise click.ClickException(str(exc)) from exc
