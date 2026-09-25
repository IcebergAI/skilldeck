"""Structural lint for the bundled skill bodies.

The Scope/Output boilerplate is hand-maintained across every skill and drifts
(the ``logging`` skill once shipped without a Scope section, and later without
an ``## Output`` heading). These tests pin the structural elements every skill
must carry, asserting on stable phrases or loose patterns rather than exact
wording so editing skills stays low-friction. The one exception is the shared
severity rubric (#103), which ``docs/finding-output.md`` defines once and each
skill inlines word for word, so the tests compare it to the doc.
"""

import re
from pathlib import Path

import pytest

from skilldeck.adapters import ADAPTERS
from skilldeck.registry import discover_skills

SKILLS = discover_skills(known_agents=set(ADAPTERS))
FINDING_OUTPUT_DOC = Path(__file__).resolve().parent.parent / "docs/finding-output.md"

# Skills whose findings top out at high: critical is reserved for
# security-exploitable, data-loss, or outage-causing findings.
CAPPED_AT_HIGH = {"code-smells", "test-review"}

# level-2 heading -> why it must be present
REQUIRED_HEADINGS = {
    "Scope": "a Scope section saying what to review",
    "Output": "an Output section with the finding format",
}
# phrase (matched against whitespace-normalized text) -> why it must be present
REQUIRED_PHRASES = {
    "uncommitted": "diff determination covering uncommitted/untracked changes",
    "For example:": "a worked example finding",
    "Verify before reporting": "the verify-before-reporting instruction",
    "Open the report with one line": "the one-line report header instruction",
}

# regex (matched against whitespace-normalized text) -> why it must match
SCOPE_PATTERNS = {
    r"`git fetch`": "a fetch so the diff uses an up-to-date remote base",
    r"`git diff origin/<base>\.\.\.HEAD`": "a three-dot diff against origin/<base>",
    r"`git (?:ls-files --others --exclude-standard|status --porcelain)`": (
        "a command that lists untracked files"
    ),
}
OUTPUT_PATTERNS = {
    r"shared severity rubric": "a reference to the shared severity rubric",
    r"more than ~\d+ survive.*summarize the rest": "the findings-cap sentence",
    r"`Reviewed origin/\w+\.\.\.HEAD \(": "a three-dot range in the header example",
}
NOTHING_IN_SCOPE = r"say so and stop"


def _normalize(text):
    return " ".join(text.split())


def _section(body, heading):
    """The text under ``## heading`` up to the next level-2 heading."""
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    return match.group(1) if match else ""


def _doc_rubric():
    """The one-paragraph rubric that docs/finding-output.md says skills inline."""
    rubric = _section(FINDING_OUTPUT_DOC.read_text(encoding="utf-8"), "Severity rubric")
    quoted = [line[2:] for line in rubric.splitlines() if line.startswith("> ")]
    assert quoted, "docs/finding-output.md lost its quoted rubric paragraph"
    return _normalize("\n".join(quoted))


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_has_required_structure(skill):
    body = _normalize(skill.body)
    missing = [
        f"'## {heading}' ({why})"
        for heading, why in REQUIRED_HEADINGS.items()
        if not re.search(rf"^## {heading}$", skill.body, re.M)
    ] + [
        f"{phrase!r} ({why})"
        for phrase, why in REQUIRED_PHRASES.items()
        if phrase not in body
    ]
    assert not missing, f"{skill.name}/skill.md is missing: " + "; ".join(missing)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_scope_and_output_carry_the_shared_pieces(skill):
    scope = _normalize(_section(skill.body, "Scope"))
    output = _normalize(_section(skill.body, "Output"))
    missing = [
        f"{why} (/{pattern}/)"
        for patterns, text in ((SCOPE_PATTERNS, scope), (OUTPUT_PATTERNS, output))
        for pattern, why in patterns.items()
        if not re.search(pattern, text)
    ]
    if not re.search(NOTHING_IN_SCOPE, _normalize(skill.body), re.I):
        missing.append("a line for a change that touches nothing in scope")
    assert not missing, f"{skill.name}/skill.md is missing: " + "; ".join(missing)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_inlines_the_shared_severity_rubric(skill):
    assert _doc_rubric() in _normalize(_section(skill.body, "Output")), (
        f"{skill.name}/skill.md: the Output section must inline the severity "
        "rubric paragraph from docs/finding-output.md word for word"
    )


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_uses_three_dot_ranges_only(skill):
    # `main..feature`, `<base>..HEAD`; not `...`, and not a `../` path
    two_dot = re.findall(r"[\w/<>-]*[\w>]\.\.(?!\.)[\w<][\w/<>-]*", skill.body)
    assert not two_dot, f"{skill.name}/skill.md uses a two-dot range: {two_dot}"


def test_capped_skills_exist():
    # A renamed skill would otherwise drop out of the parametrized test below.
    assert not CAPPED_AT_HIGH - {s.name for s in SKILLS}


@pytest.mark.parametrize(
    "skill", [s for s in SKILLS if s.name in CAPPED_AT_HIGH], ids=lambda s: s.name
)
def test_non_security_skills_never_rate_critical(skill):
    # The inlined rubric defines critical; nothing else may use it.
    rest = _normalize(skill.body).replace(_doc_rubric(), "")
    assert not re.search(r"\bcritical\b", rest, re.I), (
        f"{skill.name}/skill.md mentions critical outside the shared rubric"
    )
    assert re.search(r"top out at \*\*high\*\*", rest)


def test_finding_output_doc_lists_every_skill():
    doc = FINDING_OUTPUT_DOC.read_text(encoding="utf-8")
    intro = doc.split("\n## ", 1)[0]
    table = _section(doc, "Fields")
    missing = [
        s.name
        for s in SKILLS
        if f"`{s.name}`" not in intro or f"| `{s.name}` |" not in table
    ]
    assert not missing, f"docs/finding-output.md does not list: {missing}"


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


# Programs a code span in a skill body is taken to run: every program some
# official skill declares a command for. (Skills also quote commands as
# patterns to look for, such as `sh -c` in a CI job, so a wider list would
# flag those.) A span that is only the program's name is a mention.
COMMAND_PROGRAMS = {
    command.split(" ")[0]
    for skill in SKILLS
    for command in skill.capabilities.commands
    if not command.startswith("<")
}
_CODE_SPAN_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)


def _runs(span, command):
    return span == command or span.startswith(command + " ")


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_declares_the_commands_its_body_names(skill):
    # the capability declaration must keep up with the body, both ways
    spans = [" ".join(m.group(2).split()) for m in _CODE_SPAN_RE.finditer(skill.body)]
    declared = skill.capabilities.commands
    undeclared = sorted(
        {
            span
            for span in spans
            if span.split(" ")[0] in COMMAND_PROGRAMS
            and span not in COMMAND_PROGRAMS
            and not any(_runs(span, command) for command in declared)
        }
    )
    assert not undeclared, (
        f"{skill.name}/skill.md runs commands its meta.yaml capabilities.commands "
        f"does not declare: {undeclared}"
    )
    unused = [
        command
        for command in declared
        if not command.startswith("<")
        and not any(
            _runs(span, command) or span == command.split(" ")[0] for span in spans
        )
    ]
    assert not unused, (
        f"{skill.name}/meta.yaml declares commands its skill.md never names: {unused}"
    )


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_git_fetch_is_declared_as_network_use(skill):
    if "git fetch" in skill.capabilities.commands:
        assert any("git remote" in entry for entry in skill.capabilities.network)


def test_all_bundled_skills_are_covered():
    # If discovery ever silently returns nothing, every parametrized test above
    # would pass vacuously.
    assert len(SKILLS) >= 7
