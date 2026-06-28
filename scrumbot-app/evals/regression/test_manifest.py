"""Meta-test: keep MANIFEST.md honest.

Every regression test named in MANIFEST.md must actually exist as a collectable
test. A renamed or deleted test silently orphans its manifest row otherwise —
this fails loudly when that happens.
"""
import re
from pathlib import Path

_MANIFEST = Path(__file__).parent / "MANIFEST.md"
# Matches `test_file.py::test_name` (with optional pytest param id like `[case1]`)
# inside the manifest table. Group 1 = filename, group 2 = bare test name
# (param suffix stripped — we only check the test function exists).
_REF = re.compile(r"\b(test_[A-Za-z0-9_]+\.py)::(test_[A-Za-z0-9_]+)(?:\[[^\]]*\])?")


def _manifest_refs():
    text = _MANIFEST.read_text()
    return _REF.findall(text)


def _defines(source: str, test_name: str) -> bool:
    """True if `source` defines `def test_name(`, ignoring commented-out lines.

    Anchored to (indentation-only) line start so a `# def test_x(` comment or a
    mention inside a string/docstring doesn't count as a real definition.
    """
    pattern = re.compile(rf"(?m)^[ \t]*def {re.escape(test_name)}\s*\(")
    return bool(pattern.search(source))


def test_manifest_has_entries():
    assert _manifest_refs(), "MANIFEST.md lists no test references — table format may have changed"


def test_every_manifest_test_exists():
    missing = []
    here = Path(__file__).parent
    for filename, test_name in _manifest_refs():
        path = here / filename
        if not path.exists():
            missing.append(f"{filename} (file not found)")
            continue
        if not _defines(path.read_text(), test_name):
            missing.append(f"{filename}::{test_name} (def not found)")
    assert not missing, "MANIFEST.md references tests that don't exist: " + ", ".join(missing)
