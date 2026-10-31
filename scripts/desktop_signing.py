"""Sign and notarize the macOS app and disk image with a Developer ID.

Release builds set QUILLSAIL_MACOS_IDENTITY (a "Developer ID Application" identity),
QUILLSAIL_MACOS_KEYCHAIN (the keychain holding it) and QUILLSAIL_NOTARY_PROFILE (a
`notarytool store-credentials` profile in that keychain). The workflow creates these from
repository secrets; this script never sees a password. Without an identity, local and fork
builds stay ad-hoc signed, which Gatekeeper blocks until the user allows the app.
"""
from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import tempfile
import time
from pathlib import Path

THIN = {b"\xfe\xed\xfa\xce": ">", b"\xce\xfa\xed\xfe": "<", b"\xfe\xed\xfa\xcf": ">", b"\xcf\xfa\xed\xfe": "<"}
FAT = {b"\xca\xfe\xba\xbe": 20, b"\xca\xfe\xba\xbf": 32}
EXECUTABLE = 2  # MH_EXECUTE: these get the hardened-runtime entitlements.
ENTITLEMENTS = Path(__file__).with_name("desktop_entitlements.plist")
NOTARY_DEADLINE = 30 * 60  # Seconds Apple gets to receive and judge one upload.
UPLOADS, UPLOAD_TIMEOUT, STATUS_TIMEOUT = 3, 10 * 60, 2 * 60
FINISHED = {"Accepted", "Invalid", "Rejected"}


def identity():
    return os.environ.get("QUILLSAIL_MACOS_IDENTITY") or None


def notarizing():
    return bool(identity() and os.environ.get("QUILLSAIL_NOTARY_PROFILE"))


def status():
    """Recorded in each macOS build report; releases require "developer-id-notarized"."""
    return "developer-id-notarized" if notarizing() else "developer-id" if identity() else "ad-hoc"


def _keychain():
    keychain = os.environ.get("QUILLSAIL_MACOS_KEYCHAIN")
    return ["--keychain", keychain] if keychain else []


def run(*args, timeout=600):
    subprocess.run([str(arg) for arg in args], check=True, timeout=timeout)


def retry(*args, attempts=3):
    """Apple's timestamp and ticket services sometimes drop requests, so retry before failing."""
    for attempt in range(1, attempts + 1):
        try:
            return run(*args)
        except subprocess.CalledProcessError:
            if attempt == attempts:
                raise
            print(f"{Path(str(args[0])).name} failed; retrying ({attempt} of {attempts - 1}).")
            time.sleep(20 * attempt)


def stapler(action, path):
    retry("xcrun", "stapler", action, path)


def macho_type(path):
    """Return the Mach-O file type (executable, library, bundle), or None for other files."""
    with path.open("rb") as handle:
        header = handle.read(8)
        if header[:4] in FAT:
            count = struct.unpack(">I", header[4:8])[0]
            if not 0 < count < 32:  # Java class files share the fat magic number.
                return None
            entry = handle.read(FAT[header[:4]])
            offset = struct.unpack(">I", entry[8:12])[0] if len(entry) == 20 else struct.unpack(">Q", entry[8:16])[0]
            handle.seek(offset)
            header = handle.read(8)
        order = THIN.get(header[:4])
        if order is None:
            return None
        handle.seek(handle.tell() - 8 + 12)
        return struct.unpack(order + "I", handle.read(4))[0]


def _sign(paths, *, entitlements=False, runtime=True):
    if not paths:
        return
    command = ["codesign", "--force", "--timestamp", "--sign", identity(), *_keychain()]
    if runtime:
        command += ["--options", "runtime"]
    if entitlements:
        command += ["--entitlements", ENTITLEMENTS]
    for start in range(0, len(paths), 100):
        # --force makes a repeated signature safe after a missing timestamp.
        retry(*command, *paths[start:start + 100])


def sign_app(app):
    """Sign every nested binary, then each framework, then the app (inside out, no --deep)."""
    if not identity():
        run("codesign", "--force", "--deep", "--sign", "-", app)
        return
    binaries, frameworks = {}, []
    for folder, directories, files in os.walk(app):
        base = Path(folder)
        frameworks += [base / name for name in directories if name.endswith(".framework") and not (base / name).is_symlink()]
        for name in files:
            path = base / name
            if not path.is_symlink() and (kind := macho_type(path)) is not None:
                binaries[path] = kind
    _sign([path for path, kind in binaries.items() if kind != EXECUTABLE])
    _sign([path for path, kind in binaries.items() if kind == EXECUTABLE], entitlements=True)
    for framework in sorted(frameworks, key=lambda path: len(path.parts), reverse=True):
        _sign([framework])
    _sign([app], entitlements=True)


def sign_disk_image(image):
    _sign([image], runtime=False)


def _profile():
    return ["--keychain-profile", os.environ["QUILLSAIL_NOTARY_PROFILE"], *_keychain()]


def notarytool(*args, timeout):
    """Run a notarytool command and return its JSON reply, or {} when Apple didn't answer."""
    command = ["xcrun", "notarytool", *[str(arg) for arg in args], *_profile(), "--output-format", "json"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"notarytool {args[0]} got no answer from Apple within {timeout // 60} minutes.")
        return {}
    try:
        return json.loads(result.stdout)
    except ValueError:
        print(f"notarytool {args[0]} failed: {result.stderr.strip() or 'no response'}")
        return {}


def notarize(path):
    """Submit an app or disk image to Apple's notary service, wait, then staple the ticket.

    Each upload and status check has its own time limit, so a stalled connection to Apple is
    retried on the same submission instead of holding the build until the job times out.
    """
    deadline = time.monotonic() + NOTARY_DEADLINE
    with tempfile.TemporaryDirectory(prefix="quillsail-notarize-") as folder:
        upload = path
        if path.suffix == ".app":
            upload = Path(folder) / (path.stem + ".zip")
            run("ditto", "-c", "-k", "--keepParent", path, upload)
        for attempt in range(1, UPLOADS + 1):
            submission_id = notarytool("submit", upload, timeout=UPLOAD_TIMEOUT).get("id")
            if submission_id:
                break
            if attempt == UPLOADS or time.monotonic() > deadline:
                raise RuntimeError(f"Apple did not receive {path.name}.")
            print(f"Uploading {path.name} failed; retrying ({attempt} of {UPLOADS - 1}).")
            time.sleep(20 * attempt)
    while (status := notarytool("info", submission_id, timeout=STATUS_TIMEOUT).get("status")) not in FINISHED:
        if time.monotonic() > deadline:
            raise RuntimeError(f"Apple has not finished notarizing {path.name} (submission {submission_id}).")
        time.sleep(20)
    if status != "Accepted":
        # Apple's log names each rejected file and the reason.
        subprocess.run(["xcrun", "notarytool", "log", submission_id, *_profile()], timeout=300)
        raise RuntimeError(f"Apple did not notarize {path.name}: {status}.")
    print(f"Notarized {path.name} (submission {submission_id}).")
    stapler("staple", path)


def verify(path):
    """Check the signature, and for release builds the Developer ID, runtime, timestamp and ticket."""
    run("codesign", "--verify", "--deep", "--strict", path)
    if not identity():
        return
    details = subprocess.run(["codesign", "-dvv", str(path)], capture_output=True, text=True, check=True).stderr
    if (not re.search(r"^Authority=Developer ID Application: ", details, re.MULTILINE)
            or "Timestamp=" not in details
            or (path.suffix == ".app" and not re.search(r"flags=0x[0-9a-f]+\([^)]*runtime", details))):
        raise RuntimeError(f"{path.name} is not signed with a timestamped Developer ID and hardened runtime.")
    if notarizing():
        stapler("validate", path)
