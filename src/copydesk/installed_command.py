"""Keep the terminal installer's `quillsail` command working after an app update.

Updating the app doesn't rerun the installer. Older installers wrote a command that
could only open the window and threw away all output, so the app replaces it on start.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import sys
from pathlib import Path

MARKER = "Installed by the QuillSail installer."
OLD_DESCRIPTION = "Opens the QuillSail desktop app."
DESCRIPTION = "Runs the quillsail command from the app."
OLD_POSIX = re.compile(r"^app='.*?^executable='(?P<target>[^']+)'$.*\Z", re.MULTILINE | re.DOTALL)
OLD_WINDOWS = re.compile(r'^start "" "(?P<target>[^"]+)" %\*', re.MULTILINE)


def updated_command(text: str) -> tuple[str, str] | None:
    """For a command from an older installer: the app it runs, and its new text."""
    if MARKER not in text:
        return None
    text = text.replace(OLD_DESCRIPTION, DESCRIPTION)
    if match := OLD_POSIX.search(text):
        target = match["target"]
        return target, text[:match.start()] + f"executable='{target}'\nexec \"$executable\" cli \"$@\"\n"
    if match := OLD_WINDOWS.search(text):
        target = match["target"]
        return target, text[:match.start()] + f'"{target}" cli %*' + text[match.end():]
    return None


def refresh_installed_command() -> None:
    """Replace an older command that runs this app. Never touch anything else."""
    default = Path.home() / ".local/bin" / ("quillsail.cmd" if sys.platform == "win32" else "quillsail")
    for candidate in filter(None, {shutil.which("quillsail"), str(default)}):
        with contextlib.suppress(OSError):
            path = Path(candidate)
            # Latin-1 keeps every byte as it was, whatever encoding the installer used.
            update = updated_command(path.read_bytes().decode("latin-1"))
            if update and os.path.samefile(os.path.expandvars(update[0]), sys.executable):
                temporary = path.with_name(f"{path.name}.new-{os.getpid()}")
                temporary.write_bytes(update[1].encode("latin-1"))
                temporary.chmod(path.stat().st_mode)
                os.replace(temporary, path)
