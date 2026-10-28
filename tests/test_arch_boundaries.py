"""Architecture boundary guards.

Keeps the layering honest over time: core must not know about the UI
layer, otherwise headless reuse of the orchestrator breaks again.
"""

from __future__ import annotations

import re
from pathlib import Path

_CORE_DIR = Path(__file__).parents[1] / "src" / "muster" / "core"

_IMPORT_WIDGETS_RE = re.compile(
    r"^\s*(?:from|import)\s+\S*widgets", re.MULTILINE
)


def test_core_never_imports_widgets():
    """core -> widgets imports are a layering violation (S2 regression guard)."""
    offenders = []
    for path in sorted(_CORE_DIR.rglob("*.py")):
        match = _IMPORT_WIDGETS_RE.search(path.read_text(encoding="utf-8"))
        if match:
            offenders.append(f"{path.name}: {match.group(0).strip()}")
    assert offenders == []
