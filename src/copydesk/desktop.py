"""Local desktop lifecycle; no GUI imports or operator environment overrides.

Each runtime owns one private instance, one loopback HTTP server and one worker.
Only a short-lived, single-use launch ticket authorizes the browser setup form.
It never logs a user in or creates an administrator by itself.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import shutil
import socket
import sqlite3
import sys
import tarfile
import tempfile
import threading
import time
import tomllib
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from string import Template
from urllib.parse import urlencode, urlsplit

from flask import abort, redirect, request, session, url_for
from flask.sessions import SecureCookieSessionInterface
from sqlalchemy import select
from werkzeug.serving import WSGIRequestHandler, make_server
from werkzeug.wrappers import Response

from copydesk import __version__, migrate
from copydesk.app import create_app
from copydesk.config import ConfigError, load_config
from copydesk.db import db, make_engine
from copydesk.jobs import Worker
from copydesk.models import User
from copydesk.security import csrf_exempt

FORMAT = "quillsail.desktop.v1"
LOG_NAME = "quillsail.log"
# Holds the secret that lets this account's other terminals ask a running
# instance for a new link or to stop. Other accounts can reach the port, not this file.
CONTROL_FILE = "control.token"
CONTROL_HEADER = "X-QuillSail-Control"
TICKET_SECONDS = 90


def instance_cookie_name(directory: Path) -> str:
    return "quillsail_desktop_" + hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:12]


def default_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/QuillSail"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "QuillSail"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "quillsail"


def write_private(path: Path, content: str) -> None:
    """Replace a local state file atomically, without briefly exposing secrets."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class SharedLogHandler(RotatingFileHandler):
    """The window and terminals share one log, so no process keeps it open between lines.

    A handle held open would keep writing to the old file after another process
    rotates the log, and on Windows it would stop that rotation from working at all.
    """

    def _open(self):
        return self._builtin_open(self.baseFilename, self.mode, encoding=self.encoding, errors=self.errors,
                                  opener=lambda path, flags: os.open(path, flags, 0o600))

    def emit(self, record):
        super().emit(record)
        if self.stream:
            self.stream.close()
            self.stream = None


def open_log(logfile: Path) -> RotatingFileHandler:
    """Log to the private file that the desktop app and `instance logs` both show."""
    # Create with private permissions before logging opens the file.
    descriptor = os.open(logfile, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.close(descriptor)
    os.chmod(logfile, 0o600)
    handler = SharedLogHandler(logfile, maxBytes=1_000_000, backupCount=2, encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    return handler


class AlreadyRunning(RuntimeError):
    pass


class InstanceLock:
    """An OS lock is released on crashes; a stale file never blocks a restart."""

    def __init__(self, path: Path):
        self.path, self.handle = path, None

    def acquire(self):
        self.handle = self.path.open("a+b")
        os.chmod(self.path, 0o600)
        if self.path.stat().st_size == 0:
            self.handle.write(b"\0")
        self.handle.flush()
        self.handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise AlreadyRunning("QuillSail is already running for this publication. Use its existing launcher window.") from exc

    def release(self):
        if self.handle:
            self.handle.close()
            self.handle = None


class QuietHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        # Launch tickets and private draft/subscriber URLs must not enter logs.
        pass


class LocalRequests:
    """Reject other network clients, DNS rebinding and cross-origin requests."""

    def __init__(self, app, origin: str):
        self.app, self.origin = app, origin
        self.host = urlsplit(origin).netloc

    def __call__(self, environ, start_response):
        if environ.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"} or environ.get("HTTP_HOST") != self.host:
            return Response("This publication is available only on this computer.", status=403)(environ, start_response)
        if environ.get("HTTP_ORIGIN") not in {None, self.origin}:
            return Response("Open QuillSail from its desktop launcher.", status=403)(environ, start_response)
        return self.app(environ, start_response)


class ListenerSessions(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        return request.environ.get("quillsail.listener") == "public"


class PublicRequests:
    """A dedicated loopback origin for a locally authenticated tunnel/reverse proxy.

    Never wrap the local listener in this middleware: visitor headers are trusted
    only on this separate port. Remote peers and unexpected hosts fail closed.
    """
    def __init__(self, app, origin, provider="manual"):
        self.app, self.host, self.provider = app, urlsplit(origin).netloc, provider

    def __call__(self, environ, start_response):
        if environ.get("REMOTE_ADDR") not in {"127.0.0.1", "::1"} or environ.get("HTTP_HOST", "").lower() != self.host:
            return Response("Not found", status=404)(environ, start_response)
        raw = environ.get("HTTP_CF_CONNECTING_IP", "") if self.provider == "cloudflare" else environ.get("HTTP_X_FORWARDED_FOR", "").split(",")[-1].strip()
        try:
            visitor = str(ipaddress.ip_address(raw))
        except ValueError:
            return Response("Visitor address required", status=400)(environ, start_response)
        environ.update({"REMOTE_ADDR": visitor, "wsgi.url_scheme": "https", "SERVER_PORT": "443", "quillsail.listener": "public"})
        return self.app(environ, start_response)


class DesktopRuntime:
    def __init__(self, directory: Path | None = None):
        self.root = (directory or default_data_dir()).expanduser().resolve()
        self.config_path = self.root / "copydesk.toml"
        self.state_path = self.root / "desktop.json"
        self.lock = InstanceLock(self.root / "desktop.lock")
        self.app = self.server = self.worker = None
        self.http_thread = self.worker_thread = None
        self.url = ""
        self.public_server = self.public_thread = None
        self.public_url = ""
        self.tunnel = None
        self.hosting_status = ""
        self.awake = None
        self._listener_lock = threading.RLock()
        self._proof = secrets.token_urlsafe(32)
        self._tickets: dict[str, float] = {}
        self._ticket_lock = threading.Lock()
        # The launcher sets this to light, dark or auto; browser setup follows it.
        self.appearance = "light"
        # A terminal stops when asked. The launcher window has its own Stop button.
        self.accepts_stop = False
        self.stop_requested = threading.Event()
        self._control = secrets.token_urlsafe(32)

    def initialize(self):
        """Prepare a stopped publication without starting HTTP or sending jobs."""
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock.acquire()
        try:
            self._initialize()
        finally:
            self.lock.release()

    def _initialize(self):
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if state.get("format") != FORMAT or not self.config_path.is_file():
                raise ConfigError("This folder is not a complete QuillSail desktop publication.")
        else:
            if any(path.name not in {"desktop.lock", "quillsail.log", "quillsail.log.1", "quillsail.log.2"} for path in self.root.iterdir()):
                raise ConfigError("This folder already contains other files. Choose an empty folder for the desktop publication.")
            template = (Path(__file__).parent / "config_template.toml").read_text(encoding="utf-8")
            write_private(self.config_path, Template(template).substitute(
                base_url="http://127.0.0.1:5080", secret_key=secrets.token_hex(32),
                database_url="sqlite:///data/copydesk.db", mail_backend="file",
                from_email="newsletter@localhost", proxy_hops="0"))
            state = {"format": FORMAT, "port": 5080}
            write_private(self.state_path, json.dumps(state) + "\n")
        config = load_config(self.config_path, require_file=True, use_environment=False)
        engine = make_engine(config.database_url)
        try:
            if engine.dialect.name != "sqlite" or not Path(engine.url.database or "").resolve().is_relative_to(self.root):
                raise ConfigError("Desktop publications use a SQLite database inside their own data folder.")
            database = Path(engine.url.database)
            for path in (config.data_dir, config.uploads_dir, config.themes_dir, config.extensions_dir, config.mail.file_dir):
                if not path.resolve().is_relative_to(self.root):
                    raise ConfigError("Desktop publication files must stay inside their own data folder.")
                path.mkdir(parents=True, exist_ok=True, mode=0o700)
            database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if migrate.needs_upgrade(engine):
                if database.exists() and migrate.current_revision(engine) is not None:
                    self._backup(database, config)
                migrate.upgrade(engine)
            os.chmod(database, 0o600)
        finally:
            engine.dispose()
        # The desktop never inherits a proxy, debug server or web worker setting.
        config.proxy_hops, config.debug, config.run_jobs_in_web = 0, False, False
        return config, state

    def _backup(self, database, config):
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = self.root / "backups" / f"{stamp}-before-{__version__}"
        backup.mkdir(parents=True, mode=0o700)
        with sqlite3.connect(database) as source, sqlite3.connect(backup / "copydesk.db") as destination:
            source.backup(destination)
        shutil.copyfile(self.config_path, backup / "copydesk.toml")
        with tarfile.open(backup / "files.tar.gz", "w:gz") as archive:
            for name, path in (("uploads", config.uploads_dir), ("themes", config.themes_dir),
                               ("extensions", config.extensions_dir), ("mail", config.mail.file_dir)):
                archive.add(path, arcname=name)
        for path in backup.iterdir():
            os.chmod(path, 0o600)

    def start(self, *, with_worker=True, port=None):
        if self.server is not None:
            raise RuntimeError("This publication is already running.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock.acquire()
        try:
            config, saved = self._initialize()
            self.app = create_app(config)
            self.app.config["SESSION_COOKIE_NAME"] = instance_cookie_name(self.root)
            self.app.extensions["copydesk_desktop"] = self
            self.app.add_url_rule("/_desktop/open", "setup.desktop_open", self._open)
            self.app.add_url_rule("/_desktop/status", "setup.desktop_status", self._status)
            self.app.add_url_rule("/_desktop/link", "setup.desktop_link", csrf_exempt(lambda: self._control_link()), methods=["POST"])
            self.app.add_url_rule("/_desktop/stop", "setup.desktop_stop", csrf_exempt(lambda: self._control_stop()), methods=["POST"])
            listen_port = saved.get("port", 5080) if port is None else port
            if not isinstance(listen_port, int) or not 0 <= listen_port <= 65535:
                listen_port = 0
            if listen_port and port is None:
                with socket.socket() as probe:
                    try:
                        probe.bind(("127.0.0.1", listen_port))
                    except OSError:
                        listen_port = 0
            try:
                self.server = make_server("127.0.0.1", listen_port, self.app, threaded=True, request_handler=QuietHandler)
            except (OSError, SystemExit) as exc:
                if port is not None:
                    raise ConfigError(f"Port {port} is already in use. Choose another with --port.") from exc
                self.server = make_server("127.0.0.1", 0, self.app, threaded=True, request_handler=QuietHandler)
            self.url = f"http://127.0.0.1:{self.server.server_port}"
            self.app.config["SERVER_NAME"] = config.server_name
            self.app.session_interface = ListenerSessions()
            self._wsgi = self.app.wsgi_app
            self.app.wsgi_app = LocalRequests(self._wsgi, self.url)
            self.app.before_request_funcs[None].insert(0, self._public_guard)
            if urlsplit(config.base_url).hostname in {"127.0.0.1", "localhost", "::1"}:
                config.base_url = self.url
                self.app.config["SERVER_NAME"] = config.server_name
            else:
                self._start_public(config.base_url, saved.get("public_port", 0))
            write_private(self.state_path, json.dumps({"format": FORMAT, "port": self.server.server_port, "public_port": self.public_server.server_port if self.public_server else 0, "version": __version__}) + "\n")
            self.stop_requested.clear()
            write_private(self.root / CONTROL_FILE, self._control)
            self.http_thread = threading.Thread(target=self.server.serve_forever, name="quillsail-local-web", daemon=True)
            self.http_thread.start()
            if with_worker:
                self.worker = Worker(self.app)
                self.worker_thread = threading.Thread(target=self.worker.run, name="quillsail-local-worker", daemon=True)
                self.worker_thread.start()
                self.ensure_tunnel(download=False)
            self.apply_keep_awake()
        except BaseException:
            self.stop()
            raise
        return self.url

    def apply_keep_awake(self):
        from copydesk import settings
        from copydesk.tunnel import AwakeGuard

        with self.app.app_context():
            enabled = bool(self.public_url and settings.get("hosting.keep_awake"))
        if enabled and self.awake is None:
            self.awake = AwakeGuard()
            self.awake.start()
        elif not enabled and self.awake:
            self.awake.stop()
            self.awake = None

    def ensure_tunnel(self, *, download=True):
        from copydesk import cloudflare
        from copydesk.models import HostingConnection
        from copydesk.tunnel import Tunnel, binary

        if self.tunnel:
            return
        with self.app.app_context():
            if db.session.get(HostingConnection, 1) is None:
                return
            row, data = cloudflare.connection()
            self.hosting_status = "Authorization required" if row.status == "authorization_required" else ""
            if row.status in {"disconnecting", "authorization_required"} or not data.get("tunnel_token"):
                return
            if not download:
                # Downloads and remote configuration updates belong in a job.
                from copydesk import jobs

                jobs.enqueue("domain.provision")
                db.session.commit()
                return
            self.tunnel = Tunnel(binary(self.root), data["tunnel_token"])
            self.tunnel.start()

    def stop_tunnel(self):
        if self.tunnel:
            self.tunnel.stop()
            self.tunnel = None

    def _public_guard(self):
        if request.environ.get("quillsail.listener") != "public":
            return None
        from copydesk.launch import PUBLIC_ENDPOINTS

        if request.endpoint not in PUBLIC_ENDPOINTS | {
            "public.articles", "public.article", "public.issues", "public.issue",
            "public.section", "public.page", "public.feed", "public.sitemap",
            "public.search", "public.person",
        }:
            abort(404)
        return None

    def _start_public(self, url, port=0):
        if not isinstance(port, int) or not 0 <= port <= 65535:
            port = 0
        provider = "manual"
        with self.app.app_context():
            from copydesk import settings

            provider = settings.get("hosting.provider", "manual")
        app = PublicRequests(self._wsgi, url, provider)
        try:
            self.public_server = make_server("127.0.0.1", port, app, threaded=True, request_handler=QuietHandler)
        except (OSError, SystemExit):
            self.public_server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler)
        self.public_url = url
        self.public_thread = threading.Thread(target=self.public_server.serve_forever, name="quillsail-public-web", daemon=True)
        self.public_thread.start()

    def set_public_url(self, value):
        from copydesk.domains import public_url

        value = public_url(value) if value else ""
        with self._listener_lock:
            content = self.config_path.read_text(encoding="utf-8")
            section = re.search(r'(?ms)^\[site\][ \t]*(?:#[^\n]*)?\n(.*?)(?=^\[|\Z)', content)
            if section is None:
                raise ConfigError("The desktop configuration has no site section.")
            body, count = re.subn(r'(?m)^(base_url\s*=\s*).*$', lambda match: match[1] + json.dumps(value or self.url), section[1], count=1)
            if count != 1:
                raise ConfigError("The desktop configuration has no public address setting.")
            content = content[:section.start(1)] + body + content[section.end(1):]
            if tomllib.loads(content)['site']['base_url'] != (value or self.url):
                raise ConfigError("The public address could not be saved in the site configuration.")
            port = self.public_server.server_port if self.public_server else 0
            if self.public_server:
                self.public_server.shutdown()
                self.public_thread.join()
                self.public_server.server_close()
                self.public_server = self.public_thread = None
            write_private(self.config_path, content)
            self.app.extensions["copydesk"].config.base_url = value or self.url
            self.app.config["SERVER_NAME"] = urlsplit(value or self.url).netloc
            self.public_url = value
            if value:
                self._start_public(value, port)
            write_private(self.state_path, json.dumps({"format": FORMAT, "port": self.server.server_port,
                "public_port": self.public_server.server_port if self.public_server else 0, "version": __version__}) + "\n")
            self.apply_keep_awake()

    def launch_url(self) -> str:
        if self.server is None:
            raise RuntimeError("Start QuillSail first.")
        ticket = secrets.token_urlsafe(32)
        with self._ticket_lock:
            now = time.monotonic()
            self._tickets = {key: expiry for key, expiry in self._tickets.items() if expiry > now}
            self._tickets[ticket] = now + TICKET_SECONDS
        return self.url + "/_desktop/open?" + urlencode({"ticket": ticket})

    def _open(self):
        ticket = request.args.get("ticket", "")
        with self._ticket_lock:
            expiry = self._tickets.pop(ticket, 0)
        if expiry <= time.monotonic():
            abort(403)
        with self.app.app_context():
            has_users = db.session.scalar(select(User.id).limit(1)) is not None
        if not has_users:
            session["_desktop_setup"] = self._proof
        response = redirect(url_for("dash.overview") if has_users else url_for("setup.index"))
        response.headers.update({"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"})
        return response

    def setup_authorized(self):
        return hmac.compare_digest(str(session.get("_desktop_setup", "")), self._proof)

    def _status(self):
        return {"instance": hashlib.sha256(str(self.root).encode()).hexdigest(), "version": __version__,
                "public_url": self.public_url, "public_status": self.hosting_status or (self.tunnel.status if self.tunnel else "Offline")}

    def _require_control(self):
        if not hmac.compare_digest(request.headers.get(CONTROL_HEADER, "").encode(), self._control.encode()):
            abort(403)

    def _control_link(self):
        self._require_control()
        return {"url": self.launch_url()}

    def _control_stop(self):
        self._require_control()
        if not self.accepts_stop:
            return {"error": "This publication is running in the QuillSail window. Choose Stop there, or run: quillsail quit"}, 409
        self.stop_requested.set()
        return {"stopping": True}

    def stop(self):
        try:
            if self.worker:
                self.worker.stop.set()
            if self.worker_thread:
                self.worker_thread.join()
            self.stop_tunnel()
            if self.awake:
                self.awake.stop()
                self.awake = None
            if self.public_server:
                self.public_server.shutdown()
                self.public_thread.join()
                self.public_server.server_close()
                self.public_server = self.public_thread = None
            if self.server:
                if self.http_thread and self.http_thread.is_alive():
                    self.server.shutdown()
                    self.http_thread.join()
                self.server.server_close()
                (self.root / CONTROL_FILE).unlink(missing_ok=True)
            if self.app:
                with self.app.app_context():
                    db.session.remove()
                    db.engine.dispose()
        finally:
            self.server = self.worker = self.app = None
            self.http_thread = self.worker_thread = None
            self._proof = secrets.token_urlsafe(32)
            self._control = secrets.token_urlsafe(32)
            self._tickets.clear()
            self.lock.release()


def smoke_test():
    """Exercise the frozen application's migrations, browser setup and restart."""
    import re

    import requests
    from cryptography.fernet import Fernet

    cipher = Fernet(Fernet.generate_key())
    assert cipher.decrypt(cipher.encrypt(b"local-packaging-check")) == b"local-packaging-check"
    with tempfile.TemporaryDirectory(prefix="quillsail-desktop-smoke-") as directory:
        runtime = DesktopRuntime(Path(directory))
        try:
            runtime.start(with_worker=False)
            with requests.Session() as browser:
                browser.trust_env = False
                setup = browser.get(runtime.launch_url(), timeout=15)
                assert setup.status_code == 200 and 'name="code"' not in setup.text
                csrf = re.search(r'name="csrf_token" value="([^"]+)"', setup.text)[1]
                dashboard = browser.post(runtime.url + "/setup/", data={"csrf_token": csrf, "site_name": "Local smoke publication",
                    "site_mode": "hybrid", "display_name": "Local Owner", "email": "owner@example.test",
                    "password": "synthetic-local-smoke-password-123"}, timeout=15)
                assert dashboard.status_code == 200 and dashboard.url == runtime.url + "/dashboard/"
                assert browser.get(runtime.url + "/static/css/copydesk.css", timeout=15).status_code == 200
                secret = load_config(runtime.config_path, use_environment=False).secret_key
                runtime.stop()
                runtime.start(with_worker=False)
                assert load_config(runtime.config_path, use_environment=False).secret_key == secret
                assert browser.get(runtime.launch_url(), timeout=15).url == runtime.url + "/dashboard/"
                assert browser.get(runtime.url + "/healthz", timeout=15).json()["database"] == "ok"
        finally:
            runtime.stop()
    print(json.dumps({"desktop_smoke": "passed", "setup_and_dashboard": True, "restart_preserves_data": True, "crypto_roundtrip": True, "sent_emails": 0}))
