"""Citation hygiene for the bundled skill bodies.

CLAUDE.md asks every skill to ground its checklist in authoritative sources
cited in the body. These checks keep those citations current (#102): every
skill links a source, none cites a superseded edition of a standard, none links
a documentation path that only survives as a redirect, and the ASVS requirement
IDs security-review cites sit under the chapter they belong to.
"""

import re

import pytest

from skilldeck.adapters import ADAPTERS
from skilldeck.registry import discover_skills

SKILLS = discover_skills(known_agents=set(ADAPTERS))
LINK_RE = re.compile(r"\]\((https://[^)\s]+)\)")

# pattern -> what to cite instead
SUPERSEDED = {
    r"\bA\d{2}:2021\b|/Top10/A\d{2}_2021-": "OWASP Top 10:2025 (owasp.org/Top10/2025/)",
    r"\bASVS\s*v?4\.": "ASVS 5.0",
    # the 2026 edition renumbered the entries, so a 2025 ID names a different risk
    r"\bLLM\d{2}:2025\b": "OWASP Top 10 for LLM Applications 2026 (LLMxx:2026)",
}

# old doc paths that only work through redirects -> the canonical form
STALE_URL_PREFIXES = {
    "https://docs.gitlab.com/ee/": "https://docs.gitlab.com/<path>/",
    "https://docs.github.com/en/actions/security-for-github-actions/": (
        "https://docs.github.com/en/actions/reference/security/..."
    ),
    "https://docs.github.com/en/actions/security-guides/": (
        "https://docs.github.com/en/actions/reference/security/..."
    ),
}


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_cites_at_least_one_source(skill):
    assert LINK_RE.search(skill.body), (
        f"{skill.name}/skill.md links no authoritative source"
    )


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_cites_no_superseded_standard(skill):
    stale = [
        f"{m.group(0)!r} (cite {current})"
        for pattern, current in SUPERSEDED.items()
        for m in re.finditer(pattern, skill.body)
    ]
    assert not stale, f"{skill.name}/skill.md: " + "; ".join(stale)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_links_no_redirect_only_doc_paths(skill):
    stale = [
        f"{url} (use {canonical})"
        for url in LINK_RE.findall(skill.body)
        for prefix, canonical in STALE_URL_PREFIXES.items()
        if url.startswith(prefix)
    ]
    assert not stale, f"{skill.name}/skill.md: " + "; ".join(stale)


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
