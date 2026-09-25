"""Structural lint for the bundled skill bodies.

The Scope/Output boilerplate is hand-maintained across every skill and drifts
(the ``logging`` skill once shipped without a Scope section, and later without
an ``## Output`` heading). The rules that pin the structural elements every
skill must carry live in ``skilldeck.lint``, where ``skilldeck validate``
reports them too; these tests apply them to every bundled skill. They assert
on stable phrases or loose patterns rather than exact wording so editing
skills stays low-friction. The one exception is the shared severity rubric
(#103), which ``docs/finding-output.md`` defines once and each skill inlines
word for word; ``skilldeck.lint.SEVERITY_RUBRIC`` must match the doc.
"""

import re
from dataclasses import replace
from pathlib import Path

import pytest

from skilldeck import authoring, lint
from skilldeck.adapters import ADAPTERS
from skilldeck.registry import discover_skills

SKILLS = discover_skills(known_agents=set(ADAPTERS))
FINDING_OUTPUT_DOC = Path(__file__).resolve().parent.parent / "docs/finding-output.md"

# Skills whose findings top out at high: critical is reserved for
# security-exploitable, data-loss, or outage-causing findings.
CAPPED_AT_HIGH = {"code-smells", "test-review"}


def _explain(problems):
    return "; ".join(f"[{p.rule}] {p.message}" for p in problems)


def _doc_rubric():
    """The one-paragraph rubric that docs/finding-output.md says skills inline."""
    rubric = lint.section(
        FINDING_OUTPUT_DOC.read_text(encoding="utf-8"), "Severity rubric"
    )
    quoted = [line[2:] for line in rubric.splitlines() if line.startswith("> ")]
    assert quoted, "docs/finding-output.md lost its quoted rubric paragraph"
    return lint.normalize("\n".join(quoted))


def test_package_rubric_is_the_doc_rubric():
    # skilldeck validate and skilldeck new use the package copy; the doc is
    # where people read it, so the two must never drift apart
    assert lint.normalize(lint.SEVERITY_RUBRIC) == _doc_rubric()


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_follows_the_structural_template(skill):
    problems = lint.structure_problems(skill.name, skill.body)
    assert not problems, f"{skill.name}/skill.md: " + _explain(problems)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_description_is_a_single_sentence_line(skill):
    problems = lint.description_problems(skill.name, skill.description)
    assert not problems, f"{skill.name}/meta.yaml: " + _explain(problems)


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_has_no_placeholder_left(skill):
    meta = (skill.path / "meta.yaml").read_text(encoding="utf-8")
    problems = lint.placeholder_problems(skill.body, "skill.md")
    problems += lint.placeholder_problems(meta, "meta.yaml")
    assert not problems, f"{skill.name}: " + _explain(problems)


def test_capped_skills_exist():
    # A renamed skill would otherwise drop out of the parametrized test below.
    assert not CAPPED_AT_HIGH - {s.name for s in SKILLS}


@pytest.mark.parametrize(
    "skill", [s for s in SKILLS if s.name in CAPPED_AT_HIGH], ids=lambda s: s.name
)
def test_non_security_skills_never_rate_critical(skill):
    # The inlined rubric defines critical; nothing else may use it.
    rest = lint.normalize(skill.body).replace(_doc_rubric(), "")
    assert not re.search(r"\bcritical\b", rest, re.I), (
        f"{skill.name}/skill.md mentions critical outside the shared rubric"
    )
    assert re.search(r"top out at \*\*high\*\*", rest)


def test_finding_output_doc_lists_every_skill():
    doc = FINDING_OUTPUT_DOC.read_text(encoding="utf-8")
    problems = [p for s in SKILLS for p in lint.finding_output_problems(doc, s.name)]
    assert not problems, _explain(problems)


# The declared-commands rule lives in skilldeck.lint (KNOWN_PROGRAMS,
# MENTIONED_ONLY), where skilldeck validate reports it too. Programs any
# bundled skill declares count as commands, as on main.
COMMAND_PROGRAMS = lint.command_programs(skill.capabilities for skill in SKILLS)


def _spans(skill):
    return [span for span, _ in lint.code_spans(skill.body)]


def _undeclared(skill):
    """Code spans in ``skill``'s body that run a known program with a command
    its capabilities don't declare."""
    return lint.undeclared_commands(
        skill.name, skill.body, skill.capabilities, COMMAND_PROGRAMS
    )


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_skill_declares_the_commands_its_body_names(skill):
    # the capability declaration must keep up with the body, both ways
    undeclared = _undeclared(skill)
    assert not undeclared, (
        f"{skill.name}/skill.md runs commands its meta.yaml capabilities.commands "
        f"does not declare: {undeclared} (declare them, or, for a span the skill "
        "only quotes, add it to MENTIONED_ONLY in skilldeck/lint.py)"
    )
    unused = lint.unused_commands(skill.body, skill.capabilities)
    assert not unused, (
        f"{skill.name}/meta.yaml declares commands its skill.md never names: {unused}"
    )
    # the rule validate reports agrees
    problems = lint.command_problems(
        skill.name, skill.body, skill.capabilities, COMMAND_PROGRAMS
    )
    assert not problems, _explain(problems)


def test_mentioned_only_spans_are_still_in_their_skills():
    by_name = {skill.name: skill for skill in SKILLS}
    for name, mentioned in lint.MENTIONED_ONLY.items():
        assert mentioned <= set(_spans(by_name[name])), name


def test_a_command_no_skill_declares_yet_is_still_caught():
    # the fixed list flags programs that no skill declares, so adding the
    # first scanner, network call or test run to a body can't slip through
    security = next(skill for skill in SKILLS if skill.name == "security-review")
    added = (
        "\nAlso run `semgrep --config auto`, `curl https://example.com/x` and"
        " `pytest -x`; `semgrep` alone is a mention.\n"
    )
    edited = replace(security, body=security.body + added)
    assert _undeclared(edited) == [
        "curl https://example.com/x",
        "pytest -x",
        "semgrep --config auto",
    ]
    problems = lint.command_problems(
        edited.name, edited.body, edited.capabilities, COMMAND_PROGRAMS
    )
    assert [p.rule for p in problems] == ["capabilities.undeclared-command"] * 3
    assert {p.line for p in problems} == {edited.body.count("\n")}


def test_an_unused_command_and_an_undeclared_remote_are_caught():
    security = next(skill for skill in SKILLS if skill.name == "security-review")
    capabilities = replace(
        security.capabilities,
        commands=(*security.capabilities.commands, "semgrep"),
        network=(),
    )
    rules = [
        p.rule
        for p in lint.command_problems(security.name, security.body, capabilities)
    ]
    assert rules == ["capabilities.unused-command", "capabilities.network"]


@pytest.mark.parametrize("skill", SKILLS, ids=lambda s: s.name)
def test_git_fetch_is_declared_as_network_use(skill):
    if "git fetch" in skill.capabilities.commands:
        assert any("git remote" in entry for entry in skill.capabilities.network)


def test_all_bundled_skills_are_covered():
    # If discovery ever silently returns nothing, every parametrized test above
    # would pass vacuously.
    assert len(SKILLS) >= 7


# --- the rules catch what they are for ------------------------------------------

# Every required piece, the rule that must fire when it is gone, and how to
# remove it from a body that has it. Listed here rather than read from lint's
# tables, so dropping a table entry fails a test instead of passing silently.
REQUIRED_PIECES = [
    ("Scope heading", "structure.section", "\n## Scope\n", "\n## Where\n"),
    ("Output heading", "structure.section", "\n## Output\n", "\n## Report\n"),
    ("uncommitted changes", "structure.phrase", "uncommitted", "pending"),
    ("worked example", "structure.phrase", "For example:", "Such as:"),
    ("verify", "structure.phrase", "Verify before reporting", "Check first"),
    ("header", "structure.phrase", "Open the report with one line", "Report"),
    ("fetch", "structure.scope", "`git fetch`", "`git pull`"),
    (
        "three-dot diff",
        "structure.scope",
        "`git diff origin/<base>...HEAD`",
        "`git diff origin/<base> HEAD`",
    ),
    (
        "untracked files",
        "structure.scope",
        "`git ls-files --others --exclude-standard`",
        "`git ls-files`",
    ),
    ("rubric reference", "structure.output", "shared severity rubric", "rubric"),
    ("findings cap", "structure.output", "more than ~10 survive", "many survive"),
    (
        "header range",
        "structure.output",
        "`Reviewed origin/main...HEAD (",
        "`Reviewed main (",
    ),
    ("nothing in scope", "structure.nothing-in-scope", "say so and stop", "end"),
]


def _skeleton():
    """A body that has every piece: what skilldeck new writes."""
    return authoring.SKILL_TEMPLATE.format(
        title="Widget Review", rubric=lint.SEVERITY_RUBRIC
    )


def test_the_skeleton_has_every_piece():
    assert lint.structure_problems("widget-review", _skeleton()) == []


@pytest.mark.parametrize(
    ("rule", "old", "new"),
    [piece[1:] for piece in REQUIRED_PIECES],
    ids=[piece[0] for piece in REQUIRED_PIECES],
)
def test_removing_a_required_piece_fires_its_rule(rule, old, new):
    body = _skeleton()
    pattern = r"\s+".join(map(re.escape, old.split(" ")))
    changed, count = re.subn(pattern, new, body)
    assert count, f"the skeleton lacks {old!r}"
    rules = {p.rule for p in lint.structure_problems("widget-review", changed)}
    assert rule in rules


_GOOD = SKILLS[0]


def _rules(body, name=_GOOD.name):
    return {p.rule for p in lint.structure_problems(name, body)}


def test_rules_catch_a_missing_section():
    body = _GOOD.body.replace("\n## Scope\n", "\n## Where to look\n")
    assert "structure.section" in _rules(body)


def test_rules_catch_a_reworded_rubric():
    body = _GOOD.body.replace("readily triggered", "easily triggered")
    assert _rules(body) == {"structure.severity-rubric"}


def test_rules_catch_a_heading_that_does_not_spell_the_name():
    assert _rules(_GOOD.body, name="another-name") == {"structure.heading"}


def test_rules_catch_a_two_dot_range():
    body = _GOOD.body + "\nCompare `main..feature` first.\n"
    (problem,) = lint.structure_problems(_GOOD.name, body)
    assert problem.rule == "structure.two-dot-range"
    assert problem.line == body.count("\n")


def test_rules_read_crlf_bodies():
    body = _GOOD.body.replace("\n", "\r\n")
    assert not lint.structure_problems(_GOOD.name, body)
