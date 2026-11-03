"""Run the visual editor's command tests. Browser checks are recorded in docs/verification.md."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node runs the editor's own code")
def test_visual_editor_commands():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["node", "--test", "tests/js/visual-editor.test.cjs"], cwd=root, check=True)
