"""Static checks and logic tests for the browser UI."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
INDEX = TESTS_DIR.parent / "app" / "static" / "index.html"


def test_page_has_no_external_resources_and_never_uses_innerhtml():
    html = INDEX.read_text(encoding="utf-8")

    urls = re.findall(r"https?://[^\s\"')]+", html.replace("http://www.w3.org/2000/svg", ""))

    assert urls == []                     # works offline, nothing to leak or break
    assert "innerHTML" not in html        # results are rendered as text only
    assert "outerHTML" not in html and "document.write" not in html


def test_page_exposes_the_expected_controls():
    html = INDEX.read_text(encoding="utf-8")

    for marker in ('id="question"', 'id="send"', 'id="output"', "/api/query", "QueryPilot"):
        assert marker in html, marker


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
@pytest.mark.parametrize("script", ["ui_logic.js", "ui_wiring.js"])
def test_ui_scripts_run_in_node(script):
    completed = subprocess.run(
        ["node", str(TESTS_DIR / script)], capture_output=True, text=True, timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"
