"""Build a native desktop bundle. Run on the OS/architecture being packaged.

Install the wheel with [desktop-build] in a clean virtual environment first.
Only package resources and dependency licenses enter the app; no instance data.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from PIL import Image

import copydesk
from copydesk.update_install import extract_archive, marker_path, read_install


def target_name(system=None, machine=None):
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    architecture = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    supported = {("Darwin", "arm64"): "macos-arm64", ("Darwin", "x86_64"): "macos-x86_64",
                 ("Windows", "x86_64"): "windows-x86_64", ("Linux", "x86_64"): "linux-x86_64"}
    try:
        return supported[system, architecture]
    except KeyError:
        raise ValueError(f"Unsupported desktop build platform: {system}/{machine}") from None


def licenses(target):
    target.mkdir(parents=True, exist_ok=True)
    for distribution in importlib.metadata.distributions():
        for file in distribution.files or []:
            if any(part.lower() in {"licenses", "license", "copying", "notice"} or part.lower().startswith(("license.", "copying.", "notice.")) for part in file.parts):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    relative = Path(*(part for part in file.parts if part not in {"..", ".", "/", "\\"}))
                    destination = target / distribution.metadata["Name"] / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)


def render_icon(source, destination):
    """Render the vector logo on a white, rounded app icon tile."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise ValueError("The QuillSail vector icon could not be loaded.")
    renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
    canvas = QImage(1024, 1024, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    try:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.GlobalColor.white)
        painter.drawRoundedRect(QRectF(64, 64, 896, 896), 196, 196)
        renderer.render(painter, QRectF(176, 176, 672, 672))
    finally:
        painter.end()
    if not canvas.save(str(destination)):
        raise RuntimeError("The QuillSail app icon could not be saved.")


def command_smoke(executable):
    """Run a disposable publication through the terminal installer's command. This sends no email."""
    with tempfile.TemporaryDirectory(prefix="quillsail-command-smoke-", ignore_cleanup_errors=True) as folder:
        environment = {**os.environ, "HOME": folder, "USERPROFILE": folder, "LOCALAPPDATA": folder, "XDG_DATA_HOME": folder,
                       "QUILLSAIL_INSTANCE_HOME": os.path.join(folder, "manager")}

        def command(*arguments):
            result = subprocess.run([str(executable), "cli", *arguments], timeout=180, capture_output=True, text=True, env=environment)
            if result.returncode:
                raise RuntimeError(f"The packaged command failed for {arguments}: {result.stdout!r} {result.stderr!r}")
            return result.stdout

        # Its output must reach whoever ran it.
        for arguments, expected in (((), "Usage: quillsail"), (("instance", "--help"), "Usage: quillsail instance")):
            if expected not in (printed := command(*arguments)):
                raise RuntimeError(f"The packaged command printed nothing useful for {arguments}: {printed!r}")
        try:
            command("instance", "--name", "Command smoke", "--background", "--no-browser")
            if not json.loads(command("instance", "status", "--json"))["running"]:
                raise RuntimeError("The packaged command's background publication isn't running.")
            if "ticket=" not in command("instance", "open", "--no-browser"):
                raise RuntimeError("The packaged command didn't get a new link from its running publication.")
        finally:
            command("instance", "stop", "--all")
        if json.loads(command("instance", "status", "--json"))["running"]:
            raise RuntimeError("The packaged command's background publication didn't stop.")
    print(json.dumps({"command_smoke": "passed", "background_publication": True, "new_link": True, "sent_emails": 0}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("dist/desktop"))
    parser.add_argument("--target", choices=["macos-arm64", "macos-x86_64", "windows-x86_64", "linux-x86_64"], help="Reject a runner with the wrong native architecture.")
    arguments = parser.parse_args()
    target = target_name()
    if arguments.target and arguments.target != target:
        parser.error(f"Requested {arguments.target}, but this runner builds {target}.")
    if sys.platform == "darwin":
        from cryptography.hazmat.bindings import _rust

        linkage = subprocess.check_output(["otool", "-L", _rust.__file__], text=True)
        if re.search(r"lib(?:ssl|crypto)(?:\.\d+)*\.dylib", linkage):
            raise RuntimeError(
                "The macOS cryptography binding dynamically links OpenSSL. Install desktop build dependencies "
                "in a clean environment with OPENSSL_STATIC=1 and --no-cache-dir before bundling."
            )
    root = Path(__file__).resolve().parents[1]
    output = arguments.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = root / "build/desktop"
    work.mkdir(parents=True, exist_ok=True)
    notices = work / "licenses"
    licenses(notices)
    shutil.copy2(root / "LICENSE", notices / "QuillSail-LICENSE")
    logo = Path(copydesk.__file__).parent / "static/brand/quillsail.svg"
    icon = work / ("QuillSail.icns" if sys.platform == "darwin" else "QuillSail.ico")
    if sys.platform in {"darwin", "win32"}:
        raster = work / "QuillSail-icon.png"
        render_icon(logo, raster)
        with Image.open(raster) as image:
            image.save(icon)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
               "--name", "QuillSail", "--distpath", str(output), "--workpath", str(work / "pyinstaller"),
               "--specpath", str(work), "--collect-all", "copydesk", "--collect-data", "certifi", "--hidden-import", "sqlalchemy.dialects.sqlite",
               "--add-data", str(notices) + os.pathsep + "licenses",
               "--exclude-module", "pytest", "--exclude-module", "tkinter", "--exclude-module", "IPython"]
    if sys.platform in {"darwin", "win32"}:
        command += ["--icon", str(icon)]
    if sys.platform == "darwin":
        command += ["--osx-bundle-identifier", "org.quillsail.desktop"]
    command += [str(root / "scripts/desktop_entry.py")]
    subprocess.run(command, check=True)
    # The helper has its own small Python runtime and runs outside the app that
    # it replaces (required while Windows still holds executable/library locks).
    helper_output = work / "helper-dist"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
                    "--name", "QuillSailUpdater", "--distpath", str(helper_output),
                    "--workpath", str(work / "helper-build"), "--specpath", str(work),
                    str(root / "scripts/update_helper_entry.py")], check=True)
    app_root = output / ("QuillSail.app" if sys.platform == "darwin" else "QuillSail")
    resources = app_root / "Contents/Resources" if sys.platform == "darwin" else app_root
    shutil.copytree(helper_output / "QuillSailUpdater", resources / "updater", dirs_exist_ok=True, symlinks=True)
    marker_path(app_root, target).write_text(json.dumps({"format": "quillsail.install.v1",
        "version": copydesk.__version__, "target": target, "updater_protocol": 1}) + "\n", encoding="utf-8")
    # Installer provenance is build-machine specific, never needed at runtime.
    for path in output.rglob("direct_url.json"):
        path.unlink()
    name = f"QuillSail-{copydesk.__version__}-{target}"
    if sys.platform == "darwin":
        app = output / "QuillSail.app"
        plist = app / "Contents/Info.plist"
        with plist.open("rb") as handle:
            metadata = plistlib.load(handle)
        metadata.update(CFBundleShortVersionString=copydesk.__version__, CFBundleVersion=copydesk.__version__)
        with plist.open("wb") as handle:
            plistlib.dump(metadata, handle)
        import desktop_signing

        desktop_signing.sign_app(app)
        executable = app / "Contents/MacOS/QuillSail"
    elif sys.platform == "win32":
        executable = output / "QuillSail/QuillSail.exe"
    else:
        executable = output / "QuillSail/QuillSail"
    # This uses a disposable database and file mail. It sends no email.
    subprocess.run([str(executable), "--smoke-test"], check=True, timeout=120)
    subprocess.run([str(executable), "--smoke-test-gui"], check=True, timeout=120)
    command_smoke(executable)
    helper = resources / "updater" / ("QuillSailUpdater.exe" if sys.platform == "win32" else "QuillSailUpdater")
    subprocess.run([str(helper), "--smoke-test"], check=True, timeout=120)
    if sys.platform == "darwin":
        # Notarize and staple before archiving, so the updater archive and DMG carry the ticket.
        if desktop_signing.notarizing():
            desktop_signing.notarize(app)
        artifact = output / (name + ".zip")
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(artifact)], check=True)
    elif sys.platform == "win32":
        artifact = Path(shutil.make_archive(str(output / name), "zip", root_dir=output, base_dir="QuillSail"))
    else:
        artifact = output / (name + ".tar.gz")
        with tarfile.open(artifact, "w:gz") as archive:
            archive.add(output / "QuillSail", arcname="QuillSail")
    # Exercise the actual platform archive, including macOS framework symlinks.
    with tempfile.TemporaryDirectory(prefix="quillsail-update-extraction-") as folder:
        extracted = extract_archive(artifact, Path(folder) / "unpacked", target)
        assert read_install(extracted)["version"] == copydesk.__version__
        if sys.platform == "darwin":
            desktop_signing.verify(extracted)
    from desktop_installers import build

    installer = build(output, app_root, target, copydesk.__version__, icon if sys.platform != "linux" else logo, artifact)
    report = {"installer": installer.name, "installer_sha256": hashlib.sha256(installer.read_bytes()).hexdigest(),
              "installer_lifecycle_check": True, "version": copydesk.__version__, "target": target, "archive": artifact.name,
              "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), "setup_restart_check": True,
              "gui_lifecycle_check": True, "updater_install_check": True, "commit": os.environ.get("GITHUB_SHA", "local")}
    if sys.platform == "darwin":
        report["macos_signature"] = desktop_signing.status()
    (output / (name + ".json")).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Desktop bundle ready: {output / name}")


if __name__ == "__main__":
    main()
