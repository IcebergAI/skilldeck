"""Structural lint for the bundled skill bodies.

The Scope/Output boilerplate is hand-maintained across every skill and drifts
(the ``logging`` skill once shipped without a Scope section). These tests pin
the structural elements every skill must carry, asserting on stable phrases
rather than exact wording so editing skills stays low-friction.
"""

import re

import pytest

from skilldeck.adapters import ADAPTERS
from skilldeck.registry import discover_skills

SKILLS = discover_skills(known_agents=set(ADAPTERS))

# phrase -> why it must be present
REQUIRED_PHRASES = {
    "## Scope": "a Scope section saying what to review",
    "uncommitted": "diff determination covering uncommitted/untracked changes",
    "**critical** —": "domain-specific severity anchors",
    "For example:": "a worked example finding",
    "Verify before reporting": "the verify-before-reporting instruction",
    "Open the report with one line": "the one-line report header instruction",
}


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_has_required_structure(skill):
    missing = [
        f"{phrase!r} ({why})"
        for phrase, why in REQUIRED_PHRASES.items()
        if phrase not in skill.body
    ]
    assert not missing, f"{skill.name}/skill.md is missing: " + "; ".join(missing)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_heading_matches_name(skill):
    first_line = skill.body.splitlines()[0]
    assert first_line.startswith("# "), f"{skill.name}: body must open with a heading"
    slug = re.sub(r"[^a-z0-9]+", "-", first_line[2:].strip().lower()).strip("-")
    assert slug == skill.name, (
        f"{skill.name}: heading {first_line!r} does not match the skill name"
    )


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_description_is_a_single_sentence_line(skill):
    assert "\n" not in skill.description, f"{skill.name}: description must be one line"
    assert skill.description.endswith("."), (
        f"{skill.name}: description should end with a period"
    )


def test_all_bundled_skills_are_covered():
    # If discovery ever silently returns nothing, every parametrized test above
    # would pass vacuously.
    assert len(SKILLS) >= 7
