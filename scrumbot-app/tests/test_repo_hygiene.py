"""Public-repo hygiene, enforced in CI.

Two rules the product has since day one: no agile jargon in anything a user or
reader sees, and no real phone numbers other than the business line.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Files a reader sees. CLAUDE.md files state the rule and are excluded on purpose.
PUBLIC_GLOBS = [
    "README.md", "CHANGELOG.md", "SECURITY.md", "Makefile", "LICENSE",
    "docs/**/*.md", "scripts/*.py",
    "scrumbot-app/EVALS.md", "scrumbot-app/chat.py", "scrumbot-app/local_server.py",
    "scrumbot-app/site/*.html", "scrumbot-app/evals/regression/MANIFEST.md",
]

BANNED = re.compile(r"\b(sprints?|standups?|fibonacci|scrumbot(?!-(?:app|infra)))\b", re.IGNORECASE)
E164 = re.compile(r"\+1\d{10}")
ALLOWED_NUMBERS = {"+14049485133"}  # the business line


def _public_files():
    for pattern in PUBLIC_GLOBS:
        yield from ROOT.glob(pattern)


@pytest.mark.parametrize("path", sorted(_public_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_banned_words(path):
    hits = [(i, line.strip()) for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1)
            if BANNED.search(line)]
    assert not hits, f"{path.relative_to(ROOT)} contains banned words: {hits[:3]}"


@pytest.mark.parametrize("path", sorted(_public_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_real_phone_numbers(path):
    numbers = {n for n in E164.findall(path.read_text(errors="ignore"))
               if not n.startswith("+1555") and n not in ALLOWED_NUMBERS}
    assert not numbers, f"{path.relative_to(ROOT)} contains phone numbers: {sorted(numbers)}"
