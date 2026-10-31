import importlib.util
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("desktop_signing", ROOT / "scripts/desktop_signing.py")
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


def thin(filetype, magic=b"\xcf\xfa\xed\xfe"):
    order = signing.THIN[magic]
    return magic + struct.pack(order + "III", 0x0100000C, 0, filetype) + bytes(16)


def fat(*slices):
    header = b"\xca\xfe\xba\xbe" + struct.pack(">I", len(slices))
    offset, entries, body = 4096, b"", b""
    for item in slices:
        entries += struct.pack(">5I", 0, 0, offset + len(body), len(item), 12)
        body += item
    return (header + entries).ljust(offset, b"\0") + body


@pytest.mark.parametrize(("content", "expected"), [
    (thin(2), 2), (thin(6), 6), (thin(8), 8),
    (thin(2, b"\xfe\xed\xfa\xce"), 2),
    (fat(thin(2), thin(2)), 2), (fat(thin(6)), 6),
    (b"\xca\xfe\xba\xbe\x00\x00\x00\x41" + bytes(32), None),  # A Java class file, not a fat binary.
    (b"#!/bin/sh\n", None), (b"", None), (b"\xcf\xfa", None),
])
def test_mach_o_files_and_executables_are_recognized(tmp_path, content, expected):
    path = tmp_path / "file"
    path.write_bytes(content)
    assert signing.macho_type(path) == expected


@pytest.mark.parametrize(("environment", "expected"), [
    ({}, "ad-hoc"),
    ({"QUILLSAIL_NOTARY_PROFILE": "notary"}, "ad-hoc"),
    ({"QUILLSAIL_MACOS_IDENTITY": "Developer ID Application: Example (TEAMID1234)"}, "developer-id"),
    ({"QUILLSAIL_MACOS_IDENTITY": "Developer ID Application: Example (TEAMID1234)",
      "QUILLSAIL_NOTARY_PROFILE": "notary"}, "developer-id-notarized"),
])
def test_signature_status_follows_the_configured_identity(monkeypatch, environment, expected):
    for name in ("QUILLSAIL_MACOS_IDENTITY", "QUILLSAIL_NOTARY_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    assert signing.status() == expected


def test_signing_goes_inside_out_with_entitlements_only_on_executables(tmp_path, monkeypatch):
    monkeypatch.setenv("QUILLSAIL_MACOS_IDENTITY", "Developer ID Application: Example (TEAMID1234)")
    monkeypatch.setenv("QUILLSAIL_MACOS_KEYCHAIN", "/tmp/signing.keychain-db")
    app = tmp_path / "QuillSail.app"
    framework = app / "Contents/Frameworks/QtCore.framework"
    (framework / "Versions/A").mkdir(parents=True)
    (framework / "Versions/A/QtCore").write_bytes(thin(6))
    (framework / "QtCore").symlink_to("Versions/A/QtCore")
    (app / "Contents/MacOS").mkdir()
    (app / "Contents/MacOS/QuillSail").write_bytes(thin(2))
    helper = app / "Contents/Resources/updater"
    helper.mkdir(parents=True)
    (helper / "QuillSailUpdater").write_bytes(fat(thin(2), thin(2)))
    (helper / "module.so").write_bytes(thin(8))
    (helper / "notes.txt").write_text("not code")
    calls = []
    monkeypatch.setattr(signing, "run", lambda *args, **_: calls.append([str(arg) for arg in args]))

    signing.sign_app(app)

    names = [Path(path).name for call in calls for path in call if path.startswith(str(app))]
    assert set(names[:2]) == {"QtCore", "module.so"}
    assert set(names[2:4]) == {"QuillSail", "QuillSailUpdater"}
    assert names[4:] == ["QtCore.framework", "QuillSail.app"]
    assert "notes.txt" not in names
    assert ["--entitlements" in call for call in calls] == [False, True, False, True]
    assert all("runtime" in call and "--timestamp" in call and "--deep" not in call for call in calls)
    assert all("/tmp/signing.keychain-db" in call for call in calls)


def test_builds_without_an_identity_stay_ad_hoc_signed(tmp_path, monkeypatch):
    monkeypatch.delenv("QUILLSAIL_MACOS_IDENTITY", raising=False)
    calls = []
    monkeypatch.setattr(signing, "run", lambda *args, **_: calls.append([str(arg) for arg in args]))
    signing.sign_app(tmp_path / "QuillSail.app")
    assert calls == [["codesign", "--force", "--deep", "--sign", "-", str(tmp_path / "QuillSail.app")]]


@pytest.mark.parametrize(("failures", "succeeds"), [(2, True), (3, False)])
def test_dropped_connections_to_apples_ticket_service_are_retried(tmp_path, monkeypatch, failures, succeeds):
    attempts = []

    def flaky(*args, **_):
        attempts.append(args)
        if len(attempts) <= failures:
            raise signing.subprocess.CalledProcessError(65, list(args))

    monkeypatch.setattr(signing, "run", flaky)
    monkeypatch.setattr(signing.time, "sleep", lambda _: None)
    if succeeds:
        signing.stapler("validate", tmp_path / "QuillSail.dmg")
    else:
        with pytest.raises(signing.subprocess.CalledProcessError):
            signing.stapler("validate", tmp_path / "QuillSail.dmg")
    assert len(attempts) == 3


installers_spec = importlib.util.spec_from_file_location("desktop_installers", ROOT / "scripts/desktop_installers.py")
installers = importlib.util.module_from_spec(installers_spec)
installers_spec.loader.exec_module(installers)


@pytest.mark.parametrize(("failures", "succeeds"), [(3, True), (4, False)])
def test_a_busy_new_disk_image_is_attached_again(tmp_path, monkeypatch, failures, succeeds):
    attempts = []

    def busy(*args):
        attempts.append(args)
        if len(attempts) <= failures:
            raise installers.subprocess.CalledProcessError(1, list(args))

    monkeypatch.setattr(installers, "run", busy)
    monkeypatch.setattr(installers.time, "sleep", lambda _: None)
    if succeeds:
        installers.attach(tmp_path / "QuillSail.dmg", tmp_path / "mounted")
    else:
        with pytest.raises(installers.subprocess.CalledProcessError):
            installers.attach(tmp_path / "QuillSail.dmg", tmp_path / "mounted")
    assert len(attempts) == 4
    assert all(call[:2] == ("hdiutil", "attach") for call in attempts)


def test_a_missing_timestamp_is_retried_when_signing(tmp_path, monkeypatch):
    monkeypatch.setenv("QUILLSAIL_MACOS_IDENTITY", "Developer ID Application: Example (TEAMID1234)")
    image = tmp_path / "QuillSail.dmg"
    calls = []

    def timestamp_server_drops_once(*args, **_):
        calls.append(args)
        if len(calls) == 1:
            raise signing.subprocess.CalledProcessError(1, list(args))

    monkeypatch.setattr(signing, "run", timestamp_server_drops_once)
    monkeypatch.setattr(signing.time, "sleep", lambda _: None)
    signing.sign_disk_image(image)
    assert len(calls) == 2
    assert calls[0] == calls[1] and "--force" in calls[0] and "--timestamp" in calls[0]


def notary_service(monkeypatch, replies):
    """Answer notarytool commands from scripted replies; None is a stalled connection."""
    calls = []

    def notarytool(command, **kwargs):
        calls.append(command)
        queue = replies[command[2]]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if reply is None:
            raise signing.subprocess.TimeoutExpired(command, kwargs["timeout"])
        return signing.subprocess.CompletedProcess(command, 0, signing.json.dumps(reply), "")

    monkeypatch.setenv("QUILLSAIL_NOTARY_PROFILE", "notary")
    monkeypatch.delenv("QUILLSAIL_MACOS_KEYCHAIN", raising=False)
    monkeypatch.setattr(signing.subprocess, "run", notarytool)
    monkeypatch.setattr(signing.time, "sleep", lambda _: None)
    stapled = []
    monkeypatch.setattr(signing, "stapler", lambda action, path: stapled.append((action, path)))
    return calls, stapled


def test_stalled_notary_connections_are_retried_on_the_same_submission(tmp_path, monkeypatch):
    image = tmp_path / "QuillSail.dmg"
    calls, stapled = notary_service(monkeypatch, {
        "submit": [None, {"id": "submission-1"}],
        "info": [None, {"status": "In Progress"}, {"status": "Accepted"}],
    })

    signing.notarize(image)

    assert [call[2] for call in calls] == ["submit", "submit", "info", "info", "info"]
    assert all(call[3] == "submission-1" for call in calls[2:])
    assert all("--wait" not in call and "notary" in call for call in calls)
    assert stapled == [("staple", image)]


def test_an_upload_apple_never_receives_fails_after_three_attempts(tmp_path, monkeypatch):
    calls, stapled = notary_service(monkeypatch, {"submit": [None]})
    with pytest.raises(RuntimeError, match="did not receive QuillSail.dmg"):
        signing.notarize(tmp_path / "QuillSail.dmg")
    assert [call[2] for call in calls] == ["submit"] * 3
    assert stapled == []


def test_a_rejected_submission_prints_apples_log_and_is_not_stapled(tmp_path, monkeypatch):
    calls, stapled = notary_service(monkeypatch, {
        "submit": [{"id": "submission-1"}], "info": [{"status": "Invalid"}], "log": [{}],
    })
    with pytest.raises(RuntimeError, match="did not notarize QuillSail.dmg: Invalid"):
        signing.notarize(tmp_path / "QuillSail.dmg")
    assert calls[-1][2:4] == ["log", "submission-1"]
    assert stapled == []


def test_notarization_stops_waiting_at_the_deadline(tmp_path, monkeypatch):
    calls, stapled = notary_service(monkeypatch, {
        "submit": [{"id": "submission-1"}], "info": [{"status": "In Progress"}],
    })
    clock = iter(range(0, 10 * signing.NOTARY_DEADLINE, 10 * 60))
    monkeypatch.setattr(signing.time, "monotonic", lambda: next(clock))
    with pytest.raises(RuntimeError, match=r"has not finished notarizing QuillSail.dmg \(submission submission-1\)"):
        signing.notarize(tmp_path / "QuillSail.dmg")
    assert [call[2] for call in calls] == ["submit", "info", "info", "info", "info"]
    assert stapled == []
