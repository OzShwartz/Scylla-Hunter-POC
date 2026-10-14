"""Windows (cp1252) compatibility: every text-mode file read/write in hunter/
must pin encoding="utf-8" explicitly, or it silently uses the platform's
default encoding - which crashed `report --html` on Windows over the "▸"
character in report.html.j2 (not cp1252)."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HUNTER_DIR = REPO_ROOT / "hunter"
TEXT_IO_CALLS = {"open", "read_text", "write_text"}


def _is_binary_mode(call: ast.Call) -> bool:
    """open(path, "rb") / open(path, "wb") etc. - binary mode takes no
    encoding (and errors if given one), so it's exempt."""
    for arg in call.args[1:]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "b" in arg.value:
            return True
    mode = next((kw.value for kw in call.keywords if kw.arg == "mode"), None)
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def test_every_text_file_io_call_pins_utf8_encoding():
    offenders = []
    for path in sorted(HUNTER_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name not in TEXT_IO_CALLS:
                continue
            if _is_binary_mode(node):
                continue
            has_encoding = any(kw.arg == "encoding" for kw in node.keywords)
            if not has_encoding:
                offenders.append(f"{path.relative_to(HUNTER_DIR.parent)}:{node.lineno} {name}(...)")

    assert not offenders, "Missing encoding=\"utf-8\" on:\n" + "\n".join(offenders)


def test_hunter_run_does_not_crash_when_stdout_is_cp1252():
    """On Windows, redirecting stdout (a pipe, a file, an IDE output panel) makes
    Python fall back to the console code page (cp1252) unless PYTHONUTF8 forces
    UTF-8 - which then crashes on the box-drawing characters in every dry-run
    console block (run/edit/approve/simulate), never on a real stack trace.
    PYTHONIOENCODING is honored cross-platform, so this reproduces the exact
    failure mode on any OS, not just Windows - `hunter/cli.py`'s top-level
    stdout/stderr .reconfigure(encoding="utf-8") is what prevents it.
    """
    env = os.environ.copy()
    env.pop("PYTHONUTF8", None)
    env.pop("ANTHROPIC_API_KEY", None)
    env["PYTHONIOENCODING"] = "cp1252"

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "hunter", *args],
            cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )

    assert run("reset").returncode == 0
    result = run("run")
    assert result.returncode == 0, result.stdout
    assert "Traceback" not in result.stdout
