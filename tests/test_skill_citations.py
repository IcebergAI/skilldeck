"""Citation hygiene for the bundled skill bodies.

CLAUDE.md asks every skill to ground its checklist in authoritative sources
cited in the body. These checks keep those citations current (#102): every
skill links a source, none cites a superseded edition of a standard, none links
a documentation path that only survives as a redirect, and the ASVS requirement
IDs security-review cites sit under the chapter they belong to. The general
rules live in ``skilldeck.lint``, which ``skilldeck validate`` reports too.
"""

import re

import pytest

from skilldeck import lint
from skilldeck.adapters import ADAPTERS
from skilldeck.registry import discover_skills

SKILLS = discover_skills(known_agents=set(ADAPTERS))


def _problems(skill, rule):
    return [
        p.message
        for p in lint.reference_problems(skill.name, skill.body)
        if p.rule == rule
    ]


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_cites_at_least_one_source(skill):
    assert not _problems(skill, "references.cited-source"), (
        f"{skill.name}/skill.md links no authoritative source"
    )


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_cites_no_superseded_standard(skill):
    stale = _problems(skill, "references.superseded")
    assert not stale, f"{skill.name}/skill.md: " + "; ".join(stale)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_links_no_redirect_only_doc_paths(skill):
    stale = _problems(skill, "references.redirect-url")
    assert not stale, f"{skill.name}/skill.md: " + "; ".join(stale)


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("See the OWASP cheat sheets.", "references.cited-source"),
        (
            "[A03:2021](https://owasp.org/Top10/A03_2021-Injection/)",
            "references.superseded",
        ),
        ("[ASVS](https://owasp.org/asvs) ASVS v4.0.3", "references.superseded"),
        ("[LLM01:2025](https://genai.owasp.org/)", "references.superseded"),
        ("[docs](https://docs.gitlab.com/ee/ci/)", "references.redirect-url"),
    ],
)
def test_reference_rules_catch_what_they_are_for(text, rule):
    problems = lint.reference_problems("x", text)
    assert rule in {p.rule for p in problems}


def test_security_review_asvs_ids_sit_under_their_chapter():
    body = next(s for s in SKILLS if s.name == "security-review").body
    bullets = re.findall(
        r"^- \*\*V(\d+) [^*]+\*\* — (.*?)(?=^- \*\*V|\n\n)", body, re.M | re.S
    )
    assert len(bullets) == 17, "expected one bullet per ASVS 5.0 chapter"
    misfiled = [
        f"{ref} under V{chapter}"
        for chapter, text in bullets
        for group in re.findall(r"\(([^()]*)\)", text)
        for ref in re.findall(r"\b\d+\.\d+(?:\.\d+)?\b", group)
        if ref.split(".")[0] != chapter
    ]
    assert not misfiled, "ASVS IDs cited under the wrong chapter: " + ", ".join(
        misfiled
    )
