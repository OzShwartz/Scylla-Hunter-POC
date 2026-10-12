"""Windows (cp1252) compatibility: every text-mode file read/write in hunter/
must pin encoding="utf-8" explicitly, or it silently uses the platform's
default encoding - which crashed `report --html` on Windows over the "▸"
character in report.html.j2 (not cp1252)."""

from __future__ import annotations

import ast
from pathlib import Path

HUNTER_DIR = Path(__file__).resolve().parent.parent / "hunter"
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
