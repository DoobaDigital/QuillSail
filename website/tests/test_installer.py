"""Run install.sh for real against a local copy of the site, with synthetic app bundles.

The Linux layout runs everywhere: on macOS a stand-in `uname` reports Linux. The
macOS layout needs macOS's ditto and codesign. install.ps1 is checked only when
PowerShell is installed.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from conftest import release_fixture
from quillsail_site import create_app
from quillsail_site.config import Config

VERSION = "2.3.4"
INSTALLER = Path(__file__).resolve().parents[1] / "quillsail_site/install/install.sh"
on_macos = pytest.mark.skipif(sys.platform != "darwin", reason="needs macOS ditto and codesign")


def marker(target: str, version: str = VERSION) -> str:
    return json.dumps({"format": "quillsail.install.v1", "version": version, "target": target, "updater_protocol": 1})


def linux_bundle(version: str = VERSION) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        def add(name, content: bytes, mode=0o644):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(content), mode
            archive.addfile(info, io.BytesIO(content))
        add("QuillSail/QuillSail", b"#!/bin/sh\necho \"QuillSail test $*\"\n", 0o755)
        add("QuillSail/quillsail-install.json", marker("linux-x86_64", version).encode())
        add("QuillSail/_internal/copydesk/static/brand/quillsail.svg", b"<svg/>")
    return output.getvalue()


def mac_bundle(tmp_path: Path, target: str, version: str = VERSION) -> bytes:
    """A tiny, ad-hoc signed app zipped with ditto, like scripts/build_desktop.py does."""
    work = tmp_path / f"{target}-{version}"
    app = work / "QuillSail.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    (app / "Contents/Resources").mkdir()
    shutil.copy("/usr/bin/true", app / "Contents/MacOS/QuillSail")
    (app / "Contents/Resources/quillsail-install.json").write_text(marker(target, version))
    (app / "Contents/Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict>'
        "<key>CFBundleExecutable</key><string>QuillSail</string>"
        "<key>CFBundleIdentifier</key><string>org.quillsail.test</string>"
        "<key>CFBundlePackageType</key><string>APPL</string></dict></plist>")
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True, capture_output=True)
    archive = work / "bundle.zip"
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)], check=True)
    return archive.read_bytes()


class LocalSite:
    """The website on a loopback port, also serving the synthetic downloads."""

    def __init__(self, tmp_path: Path, docs, archives: dict[str, bytes], *, tamper: bool = False):
        self.files: dict[str, bytes] = {}
        self.server = make_server("127.0.0.1", 0, self)
        base = f"http://127.0.0.1:{self.server.server_port}"
        fixture = release_fixture(VERSION, url_base=f"{base}/files", archives=archives)
        for target, data in archives.items():
            self.files[fixture["channels"]["beta"]["builds"][target]["archive"]] = data
            if tamper:
                fixture["channels"]["beta"]["builds"][target]["sha256"] = hashlib.sha256(b"other").hexdigest()
        path = tmp_path / "releases.json"
        path.write_text(json.dumps(fixture))
        config = Config.from_env({"QUILLSAIL_SITE_URL": base, "QUILLSAIL_DOCS_URL": f"{base}/docs",
                                  "QUILLSAIL_UPDATES_URL": ""}, releases_fixture=path, warm_releases=False)
        self.app = create_app(config, docs=docs)
        self.url = base
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path.startswith("/files/") and path[7:] in self.files:
            body = self.files[path[7:]]
            start_response("200 OK", [("Content-Type", "application/octet-stream"), ("Content-Length", str(len(body)))])
            return [body]
        return self.app(environ, start_response)

    def close(self):
        self.server.shutdown()


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


def run_installer(site: LocalSite, home: Path, *args: str, linux_on_mac=False, shell="/bin/bash"):
    script = home.parent / "install.sh"
    script.write_bytes(site.app.apps["site"].test_client().get("/install.sh").data)
    env = {"HOME": str(home), "PATH": os.environ["PATH"], "SHELL": shell, "TMPDIR": str(home.parent),
           "LANG": "C"}
    if linux_on_mac:
        fake = home.parent / "fake-bin"
        fake.mkdir(exist_ok=True)
        (fake / "uname").write_text('#!/bin/sh\ncase "$1" in -s) echo Linux ;; -m) echo x86_64 ;; *) echo Linux ;; esac\n')
        (fake / "uname").chmod(0o755)
        env["PATH"] = f"{fake}:{env['PATH']}"
    return subprocess.run(["bash", str(script), *args], env=env, capture_output=True, text=True, timeout=120)


def simulate_linux() -> bool:
    if sys.platform.startswith("linux"):
        return False
    if sys.platform == "darwin":
        return True
    pytest.skip("install.sh runs on macOS and Linux")


def test_installer_parses_and_explains_itself(tmp_path, docs):
    assert subprocess.run(["bash", "-n", str(INSTALLER)]).returncode == 0
    site = LocalSite(tmp_path, docs, {})
    try:
        result = run_installer(site, tmp_path, "--help")
        assert result.returncode == 0 and "--uninstall" in result.stdout
        result = run_installer(site, tmp_path, "--channel", "nightly")
        assert result.returncode == 1 and "beta or stable" in result.stderr
    finally:
        site.close()


def test_linux_install_update_and_uninstall(tmp_path, docs, home):
    linux_on_mac = simulate_linux()
    site = LocalSite(tmp_path, docs, {"linux-x86_64": linux_bundle()})
    apps, bin_dir = home / "apps", home / "bin"
    data = home / ".local/share/quillsail"
    data.mkdir(parents=True)
    (data / "copydesk.toml").write_text("# a publication that must survive")
    try:
        result = run_installer(site, home, "--dir", str(apps), "--bin-dir", str(bin_dir), "--no-modify-path",
                               linux_on_mac=linux_on_mac)
        assert result.returncode == 0, result.stderr
        assert f"QuillSail {VERSION} is installed." in result.stdout
        installed = apps / "QuillSail"
        assert json.loads((installed / "quillsail-install.json").read_text())["version"] == VERSION
        command = bin_dir / "quillsail"
        assert command.stat().st_mode & stat.S_IXUSR
        text = command.read_text()
        assert "Installed by the QuillSail installer." in text and str(installed / "QuillSail") in text
        version = subprocess.run([str(command), "--version"], capture_output=True, text=True)
        assert "QuillSail test cli --version" in version.stdout
        # Commands must reach the terminal. They used to run hidden in the background.
        listing = subprocess.run([str(command), "instance", "list"], capture_output=True, text=True)
        assert listing.stdout == "QuillSail test cli instance list\n"
        assert subprocess.run([str(command)], capture_output=True, text=True).stdout == "QuillSail test cli\n"
        assert "quillsail instance" in result.stdout
        entry = home / ".local/share/applications/quillsail.desktop"
        assert f'Exec="{installed / "QuillSail"}"' in entry.read_text()
        assert (home / ".local/share/icons/hicolor/scalable/apps/quillsail.svg").exists()
        assert not list(apps.glob(".quillsail-install-*"))

        again = run_installer(site, home, "--dir", str(apps), "--bin-dir", str(bin_dir), "--no-modify-path",
                              linux_on_mac=linux_on_mac)
        assert again.returncode == 0 and "is already installed" in again.stdout

        removed = run_installer(site, home, "--uninstall", "--dir", str(apps), "--bin-dir", str(bin_dir),
                                linux_on_mac=linux_on_mac)
        assert removed.returncode == 0, removed.stderr
        assert not installed.exists() and not command.exists() and not entry.exists()
        assert (data / "copydesk.toml").exists()
    finally:
        site.close()


def test_running_the_installer_again_replaces_a_command_that_hid_its_output(tmp_path, docs, home):
    linux_on_mac = simulate_linux()
    site = LocalSite(tmp_path, docs, {"linux-x86_64": linux_bundle()})
    apps, bin_dir = home / "apps", home / "bin"
    bin_dir.mkdir()
    (bin_dir / "quillsail").write_text("#!/bin/sh\n# Installed by the QuillSail installer. Opens the QuillSail desktop app.\nnohup true &\n")
    try:
        result = run_installer(site, home, "--dir", str(apps), "--bin-dir", str(bin_dir), "--no-modify-path",
                               linux_on_mac=linux_on_mac)
        assert result.returncode == 0, result.stderr
        command = (bin_dir / "quillsail").read_text()
        assert "nohup" not in command and 'cli "$@"' in command
    finally:
        site.close()


def test_a_download_that_doesnt_match_the_signed_checksum_installs_nothing(tmp_path, docs, home):
    linux_on_mac = simulate_linux()
    site = LocalSite(tmp_path, docs, {"linux-x86_64": linux_bundle()}, tamper=True)
    apps = home / "apps"
    try:
        result = run_installer(site, home, "--dir", str(apps), "--bin-dir", str(home / "bin"), "--no-modify-path",
                               linux_on_mac=linux_on_mac)
        assert result.returncode == 1
        assert "checksum doesn't match the signed release" in result.stderr
        assert not (apps / "QuillSail").exists() and not (home / "bin/quillsail").exists()
    finally:
        site.close()


def test_archives_with_paths_outside_the_app_are_refused(tmp_path, docs, home):
    linux_on_mac = simulate_linux()
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name in ("QuillSail/quillsail-install.json", "QuillSail/../../escaped"):
            info = tarfile.TarInfo(name)
            content = marker("linux-x86_64").encode()
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    site = LocalSite(tmp_path, docs, {"linux-x86_64": output.getvalue()})
    try:
        result = run_installer(site, home, "--dir", str(home / "apps"), "--bin-dir", str(home / "bin"),
                               "--no-modify-path", linux_on_mac=linux_on_mac)
        assert result.returncode == 1 and "unexpected path" in result.stderr
        assert not (home / "escaped").exists() and not (tmp_path / "escaped").exists()
    finally:
        site.close()


def test_existing_files_that_arent_ours_are_left_alone(tmp_path, docs, home):
    linux_on_mac = simulate_linux()
    site = LocalSite(tmp_path, docs, {"linux-x86_64": linux_bundle()})
    apps, bin_dir = home / "apps", home / "bin"
    bin_dir.mkdir()
    (bin_dir / "quillsail").write_text("#!/bin/sh\necho the Python package's command\n")
    try:
        result = run_installer(site, home, "--dir", str(apps), "--bin-dir", str(bin_dir), "--no-modify-path",
                               linux_on_mac=linux_on_mac)
        assert result.returncode == 0, result.stderr
        assert "Python package's command" in (bin_dir / "quillsail").read_text()
        assert "wasn't made by this installer" in result.stderr

        other = home / "elsewhere"
        (other / "QuillSail").mkdir(parents=True)
        result = run_installer(site, home, "--dir", str(other), "--bin-dir", str(bin_dir), "--no-modify-path",
                               linux_on_mac=linux_on_mac)
        assert result.returncode == 1 and "isn't a QuillSail installation" in result.stderr
    finally:
        site.close()


def test_the_command_folder_is_added_to_the_shell_profile_once(tmp_path, docs, home):
    linux_on_mac = simulate_linux()
    site = LocalSite(tmp_path, docs, {"linux-x86_64": linux_bundle()})
    try:
        for _ in range(2):
            result = run_installer(site, home, "--dir", str(home / "apps"), linux_on_mac=linux_on_mac, shell="/bin/zsh")
            assert result.returncode == 0, result.stderr
        profile = (home / ".zshrc").read_text()
        assert profile.count('export PATH="$HOME/.local/bin:$PATH"') == 1
        assert "# Added by the QuillSail installer" in profile
    finally:
        site.close()


@on_macos
def test_macos_install_verifies_the_signature_and_replaces_older_versions(tmp_path, docs, home):
    apps, bin_dir = home / "Applications", home / "bin"
    site = LocalSite(tmp_path, docs, {target: mac_bundle(tmp_path, target) for target in ("macos-arm64", "macos-x86_64")})
    # An earlier version is already installed.
    earlier = apps / "QuillSail.app/Contents/Resources"
    earlier.mkdir(parents=True)
    (earlier / "quillsail-install.json").write_text(marker("macos-arm64", "2.3.3"))
    try:
        result = run_installer(site, home, "--dir", str(apps), "--bin-dir", str(bin_dir), "--no-modify-path")
        assert result.returncode == 0, result.stderr
        resources = apps / "QuillSail.app/Contents/Resources/quillsail-install.json"
        assert json.loads(resources.read_text())["version"] == VERSION
        subprocess.run(["codesign", "--verify", "--deep", "--strict", str(apps / "QuillSail.app")], check=True)
        command = (bin_dir / "quillsail").read_text()
        assert str(apps / "QuillSail.app/Contents/MacOS/QuillSail") in command and 'cli "$@"' in command
        assert not list(apps.glob(".quillsail-install-*"))
    finally:
        site.close()


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="needs PowerShell")
def test_powershell_installer_parses(site):
    script = site.get("/install.ps1").get_data(as_text=True)
    check = ("$errors = $null; [System.Management.Automation.Language.Parser]::ParseInput("
             "[Console]::In.ReadToEnd(), [ref]$null, [ref]$errors) | Out-Null; "
             "if ($errors) { $errors | ForEach-Object { $_.Message }; exit 1 }")
    result = subprocess.run(["pwsh", "-NoProfile", "-Command", check], input=script, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
