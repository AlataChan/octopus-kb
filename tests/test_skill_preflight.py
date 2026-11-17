"""Each independently installed skill must retain the same preflight contract."""
from pathlib import Path
import re
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ("kb", "kb-ingest", "kb-maintain", "kb-retrieve")


@pytest.mark.parametrize("name", SKILLS)
def test_independently_installed_skill_has_local_preflight(name, tmp_path):
    installed = tmp_path / "installed" / name
    shutil.copytree(ROOT / "skills" / name, installed)
    text = (installed / "SKILL.md").read_text(encoding="utf-8")
    preflight = text.index("## 0. 执行前预检")
    match = re.search(r"\]\((references/runtime-preflight\.md)\)", text)
    assert match is not None
    assert match.start() > preflight
    assert (installed / match.group(1)).is_file()
    # No sibling skill or repository tree is present in this installation.
    assert list(installed.parent.iterdir()) == [installed]


@pytest.mark.parametrize("name", SKILLS[1:])
def test_preflight_distribution_copies_match_canonical(name):
    canonical = ROOT / "skills/kb/references/runtime-preflight.md"
    copy = ROOT / "skills" / name / "references/runtime-preflight.md"
    assert copy.read_bytes() == canonical.read_bytes()
