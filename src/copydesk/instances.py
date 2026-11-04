"""Named local publications shared by the desktop launcher and CLI.

The registry contains paths and display names only. Each publication owns its
configuration, database, credentials, uploads, queue, listener and OS lock.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from copydesk.config import ConfigError
from copydesk.desktop import (
    CONTROL_FILE,
    CONTROL_HEADER,
    FORMAT,
    AlreadyRunning,
    DesktopRuntime,
    InstanceLock,
    default_data_dir,
    write_private,
)

REGISTRY_FORMAT = "quillsail.instances.v1"
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,47}\Z")


def default_registry_dir() -> Path:
    return Path(os.environ["QUILLSAIL_INSTANCE_HOME"]).expanduser() if os.environ.get("QUILLSAIL_INSTANCE_HOME") else default_data_dir().with_name(default_data_dir().name + "-instances")


@dataclass(frozen=True)
class Instance:
    id: str
    name: str
    root: Path

    @property
    def config_path(self) -> Path:
        return self.root / "copydesk.toml"


def running_status(instance: Instance) -> dict:
    """Recognize this instance, rather than trusting a stale remembered port."""
    try:
        saved = json.loads((instance.root / "desktop.json").read_text(encoding="utf-8"))
        port = saved.get("port")
        if saved.get("format") != FORMAT or type(port) is not int or not 1 <= port <= 65535:
            return {}
        url = f"http://127.0.0.1:{port}"
        with requests.Session() as client:
            client.trust_env = False
            response = client.get(url + "/_desktop/status", timeout=.4, allow_redirects=False)
            if response.status_code == 200 and response.json().get("instance") == hashlib.sha256(str(instance.root).encode()).hexdigest():
                return {**response.json(), "url": url}
    except (OSError, ValueError, AttributeError, requests.RequestException):
        pass
    return {}


def running_url(instance: Instance) -> str:
    return running_status(instance).get("url", "")


def _ask_running(instance: Instance, url: str, action: str) -> requests.Response:
    token = (instance.root / CONTROL_FILE).read_text(encoding="utf-8")
    with requests.Session() as client:
        client.trust_env = False
        return client.post(f"{url}/_desktop/{action}", headers={CONTROL_HEADER: token}, timeout=10, allow_redirects=False)


def request_link(instance: Instance) -> str:
    """A new one-time dashboard link from whichever process is running this instance."""
    url = running_url(instance)
    if not url:
        raise ConfigError(f"{instance.id} isn't running. Start it with: quillsail instance run {instance.id}")
    try:
        response = _ask_running(instance, url, "link")
        if response.status_code == 200:
            return response.json()["url"]
    except (OSError, ValueError, KeyError, requests.RequestException):
        pass
    # Only the account that owns this publication can issue a link, so fall back to signing in.
    return url + "/dashboard/"


def request_stop(instance: Instance) -> bool:
    """Ask the process running this instance to stop. False means it wasn't running."""
    url = running_url(instance)
    if not url:
        return False
    try:
        response = _ask_running(instance, url, "stop")
        if response.status_code == 409:
            raise ConfigError(response.json()["error"])
    except (OSError, ValueError, KeyError, requests.RequestException) as exc:
        raise ConfigError(f"{instance.id} couldn't be asked to stop. Stop it where it was started.") from exc
    if response.status_code != 200:
        raise ConfigError(f"{instance.id} couldn't be asked to stop. Stop it where it was started.")
    return True


def wait_until_stopped(instance: Instance, timeout: float = 120) -> bool:
    """The publication's OS lock is released once its worker and website have finished."""
    lock = InstanceLock(instance.root / "desktop.lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.acquire()
        except AlreadyRunning:
            if time.monotonic() >= deadline:
                return False
            time.sleep(.25)
        else:
            lock.release()
            return True


class InstanceRegistry:
    def __init__(self, directory: Path | None = None, *, default_root: Path | None = None):
        self.root = (directory or default_registry_dir()).expanduser().resolve()
        self.path = self.root / "instances.json"
        self.default = Instance("default", "Default publication", (default_root or default_data_dir()).expanduser().resolve())

    def list(self) -> list[Instance]:
        if not self.path.exists():
            return [self.default]
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if document["format"] != REGISTRY_FORMAT:
                raise ValueError
            rows = [Instance(row["id"], row["name"], Path(row["directory"]).expanduser().resolve()) for row in document["instances"]]
            if any(not IDENTIFIER.fullmatch(row.id) or not isinstance(row.name, str) or not row.name.strip() for row in rows):
                raise ValueError
            if len({row.id for row in rows}) != len(rows) or len({row.root for row in rows}) != len(rows):
                raise ValueError
            return rows
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ConfigError("The instance registry could not be read. Preserve instances.json and your publication folders before repairing it.") from exc

    def get(self, identifier: str) -> Instance:
        for instance in self.list():
            if instance.id == identifier:
                return instance
        raise ConfigError(f"No instance named {identifier!r}. Run `quillsail instance list`.")

    def delete(self, identifier: str, *, delete_data=False, runtime: DesktopRuntime | None = None) -> Instance:
        """Stop an owned runtime and unregister it, optionally erasing its folder.

        Other processes must stop their own runtimes before deletion. An explicitly
        saved empty registry keeps the legacy default from reappearing on startup.
        """
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        registry_lock = InstanceLock(self.root / "registry.lock")
        registry_lock.acquire()
        publication_lock = None
        try:
            item = self.get(identifier)
            rows = self.list()
            if delete_data and (self.root.is_relative_to(item.root) or any(
                row.id != item.id and (row.root.is_relative_to(item.root) or item.root.is_relative_to(row.root))
                for row in rows
            )):
                raise ConfigError("This folder overlaps the registry or another publication; keep its files instead.")
            if runtime is not None:
                if runtime.root != item.root:
                    raise ConfigError("The running publication does not match the instance being deleted.")
                runtime.stop()
            if item.root.exists():
                publication_lock = InstanceLock(item.root / "desktop.lock")
                publication_lock.acquire()
                if delete_data:
                    try:
                        marker = json.loads((item.root / "desktop.json").read_text(encoding="utf-8"))
                        if marker.get("format") != FORMAT or not item.config_path.is_file():
                            raise ValueError
                    except (OSError, ValueError, AttributeError) as exc:
                        raise ConfigError("This folder is not a complete desktop publication; keep its files instead.") from exc
                    # Keep the lock open while removing private data, including on Windows.
                    for child in item.root.iterdir():
                        if child.name == "desktop.lock":
                            continue
                        if child.is_dir() and not child.is_symlink():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
            write_private(self.path, json.dumps({"format": REGISTRY_FORMAT, "instances": [
                {"id": row.id, "name": row.name, "directory": str(row.root)}
                for row in rows if row.id != item.id
            ]}, indent=2) + "\n")
            if publication_lock:
                publication_lock.release()
            if delete_data and item.root.exists():
                (item.root / "desktop.lock").unlink(missing_ok=True)
                item.root.rmdir()
            return item
        finally:
            if publication_lock:
                publication_lock.release()
            registry_lock.release()

    def add(self, name: str, directory: Path | None = None, *, existing=False) -> Instance:
        name = name.strip()
        identifier = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not 1 <= len(name) <= 80 or any(ord(c) < 32 for c in name) or not IDENTIFIER.fullmatch(identifier):
            raise ConfigError("Use a name of 1–80 characters that contains letters or numbers; its identifier must fit in 48 characters.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = InstanceLock(self.root / "registry.lock")
        lock.acquire()
        try:
            rows = self.list()
            folder = (directory or self.root / "publications" / identifier).expanduser().resolve()
            if any(row.id == identifier for row in rows):
                raise ConfigError("That instance name is already in use. Choose another name.")
            if any(row.root == folder or row.root.is_relative_to(folder) or folder.is_relative_to(row.root) for row in rows):
                raise ConfigError("Choose a separate data folder outside other registered instances.")
            instance = Instance(identifier, name, folder)
            if existing:
                try:
                    marker = json.loads((folder / "desktop.json").read_text(encoding="utf-8"))
                    if marker.get("format") != FORMAT or not instance.config_path.is_file():
                        raise ValueError
                except (OSError, ValueError) as exc:
                    raise ConfigError("Choose an existing QuillSail desktop publication folder containing desktop.json and copydesk.toml.") from exc
            else:
                DesktopRuntime(folder).initialize()
            rows.append(instance)
            write_private(self.path, json.dumps({"format": REGISTRY_FORMAT, "instances": [
                {"id": row.id, "name": row.name, "directory": str(row.root)} for row in rows
            ]}, indent=2) + "\n")
            if os.name != "nt":
                self.root.chmod(0o700)
            return instance
        finally:
            lock.release()
