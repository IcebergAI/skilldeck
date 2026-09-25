"""The rules a skill's files must follow: one source of truth.

``skilldeck validate`` reports these rules, and the test suite applies the
same functions to every bundled skill, so the structural template, the
citation hygiene and the placeholder check are defined once, here.

The structure rules pin what every review skill carries (see
``docs/authoring-skills.md``): a ``## Scope`` section that determines the diff
the same way in every skill, and an ``## Output`` section with the shared
finding format, the severity rubric from ``docs/finding-output.md`` word for
word, a worked example, the verify-before-reporting instruction, the findings
cap and the one-line report header. They match stable phrases or loose
patterns rather than exact wording, so editing a skill stays low-friction;
the rubric is the one exact match.

Every rule has an id, a level and a remediation in :data:`RULES`. An
``error`` is something wrong; ``incomplete`` means authoring work remains
(``TODO(author)`` placeholders, no cited source yet, no eval fixture), which
is what a freshly scaffolded skill reports until its content is written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: marks content a skill author still has to write; ``skilldeck new`` puts it
#: wherever the template cannot know the domain, and validate reports it
PLACEHOLDER = "TODO(author)"

ERROR = "error"
INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class Rule:
    level: str
    #: what the rule requires, in one line
    summary: str
    #: how to fix a problem the rule reports
    remediation: str


_AUTHORING = "docs/authoring-skills.md"

#: every rule ``skilldeck validate`` can report, by id
RULES: dict[str, Rule] = {
    # meta.yaml, as the registry validates it (skilldeck.registry)
    "meta.missing": Rule(
        ERROR,
        "the skill directory has a meta.yaml",
        "create meta.yaml with name, description, category, version and "
        "supported-agents (skilldeck new writes one)",
    ),
    "meta.encoding": Rule(ERROR, "meta.yaml is UTF-8", "save meta.yaml as UTF-8"),
    "meta.syntax": Rule(
        ERROR,
        "meta.yaml is a YAML mapping",
        "fix the YAML so the file is a mapping of field: value lines",
    ),
    "meta.missing-field": Rule(
        ERROR,
        "meta.yaml has every required field",
        "add the missing field(s); all of name, description, category, version "
        f"and supported-agents are required ({_AUTHORING}#metayaml)",
    ),
    "meta.unknown-field": Rule(
        ERROR,
        "meta.yaml has only the known fields",
        "remove the field or correct its spelling",
    ),
    "meta.name": Rule(
        ERROR,
        "name is 1-64 lowercase letters, digits and single hyphens",
        "use a name like my-review: lowercase letters and digits, single "
        "hyphens between them",
    ),
    "meta.name-mismatch": Rule(
        ERROR,
        "name matches the skill's directory name",
        "rename the directory or change name so the two match",
    ),
    "meta.description": Rule(
        ERROR,
        "description is one non-empty line of at most 1024 characters",
        "write the description as a single line (a folded block needs >-)",
    ),
    "meta.description-period": Rule(
        ERROR,
        "description is one sentence ending with a period",
        "end the description with a period",
    ),
    "meta.category": Rule(
        ERROR,
        "category is a non-empty string",
        "set category to a grouping such as security or review",
    ),
    "meta.version": Rule(
        ERROR,
        "version is a MAJOR.MINOR.PATCH string",
        'quote the version as MAJOR.MINOR.PATCH, e.g. version: "0.1.0"',
    ),
    "meta.supported-agents": Rule(
        ERROR,
        "supported-agents is a non-empty list of distinct agent names",
        "list each agent once, e.g. supported-agents: [claude, codex]",
    ),
    "meta.unknown-agent": Rule(
        ERROR,
        "supported-agents names only agents skilldeck has adapters for",
        "use only claude, codex, copilot, cursor and kiro; the legacy "
        "adapters (copilot-prompt, cursor-rule, kiro-steering) follow their "
        "agent's entry and are never listed",
    ),
    "meta.deprecated": Rule(
        ERROR,
        "deprecated, when present, has since, reason and optional replacement",
        f"fix the deprecated record as {_AUTHORING}#deprecating-a-skill "
        "describes, or remove it",
    ),
    "meta.deprecated-replacement": Rule(
        ERROR,
        "a deprecated skill's replacement is a current sibling skill that "
        "supports the same agents",
        "name a skill in the same directory that is not deprecated and "
        "supports every agent this one does",
    ),
    # skill.md
    "body.missing": Rule(
        ERROR,
        "the skill directory has a skill.md",
        "create skill.md with the skill body (skilldeck new writes a skeleton)",
    ),
    "body.encoding": Rule(ERROR, "skill.md is UTF-8", "save skill.md as UTF-8"),
    "skill.unexpected-file": Rule(
        ERROR,
        "the skill directory holds only meta.yaml and skill.md",
        "move the file out of the skill directory: installs carry only "
        "meta.yaml and skill.md, and provenance --verify rejects other files",
    ),
    "structure.heading": Rule(
        ERROR,
        "skill.md opens with a '# Title' whose words spell the skill name",
        "start skill.md with a heading such as '# My Review' for my-review",
    ),
    "structure.section": Rule(
        ERROR,
        "skill.md has the ## Scope and ## Output sections",
        f"add the section, following the structural template in {_AUTHORING}",
    ),
    "structure.phrase": Rule(
        ERROR,
        "skill.md carries the shared instructions every review skill has",
        f"add the missing instruction; see the structural template in {_AUTHORING}",
    ),
    "structure.scope": Rule(
        ERROR,
        "## Scope determines the diff the same way in every skill",
        "in ## Scope, determine the diff with `git fetch`, then "
        "`git diff origin/<base>...HEAD`, plus uncommitted changes and "
        "untracked files (`git ls-files --others --exclude-standard`)",
    ),
    "structure.output": Rule(
        ERROR,
        "## Output carries the shared finding-report pieces",
        "add the missing piece to ## Output, as in docs/finding-output.md",
    ),
    "structure.severity-rubric": Rule(
        ERROR,
        "## Output inlines the shared severity rubric word for word",
        "copy the quoted rubric paragraph from docs/finding-output.md"
        "#severity-rubric into ## Output unchanged",
    ),
    "structure.nothing-in-scope": Rule(
        ERROR,
        "skill.md says what to do when the change touches nothing in its area",
        "add a line telling the agent, when the change touches nothing in the "
        "skill's area, to say so and stop",
    ),
    "structure.two-dot-range": Rule(
        ERROR,
        "git ranges are three-dot (origin/<base>...HEAD)",
        "use a three-dot range, e.g. origin/<base>...HEAD",
    ),
    "references.cited-source": Rule(
        INCOMPLETE,
        "skill.md links at least one authoritative source",
        "ground the checklist in sources you fetched (OWASP, CIS, vendor "
        "docs) and cite them as Markdown links in the body",
    ),
    "references.superseded": Rule(
        ERROR,
        "skill.md cites no superseded edition of a standard",
        "cite the current edition named in the message",
    ),
    "references.redirect-url": Rule(
        ERROR,
        "skill.md links no documentation path that only survives as a redirect",
        "link the canonical URL named in the message",
    ),
    "content.placeholder": Rule(
        INCOMPLETE,
        f"no {PLACEHOLDER} placeholder remains",
        f"replace every {PLACEHOLDER} placeholder with the real content",
    ),
    # adapters and catalog
    "render.failed": Rule(
        ERROR,
        "every adapter for the skill's agents can render it",
        "change what the message names so the adapter can write it (the "
        "legacy cursor-rule format cannot escape some descriptions)",
    ),
    "catalog.entry": Rule(
        ERROR,
        "the skill's catalog entry builds",
        "fix the error in the message; skilldeck catalog --json must be able "
        "to describe the skill",
    ),
    # checks that apply only in a skilldeck checkout
    "eval.fixture-missing": Rule(
        INCOMPLETE,
        "an eval fixture with a planted defect exercises the skill",
        "add an eval fixture that plants a defect the skill must find; see "
        "evals/README.md#adding-a-fixture",
    ),
    "eval.fixture-invalid": Rule(
        ERROR,
        "the skill's eval fixtures load, and their planted files are in change/",
        "fix the fixture as the message says; see evals/README.md#fixture-layout",
    ),
    "docs.finding-output": Rule(
        INCOMPLETE,
        "docs/finding-output.md lists the skill and its classifier",
        "add the skill to docs/finding-output.md: the list of review skills "
        "at the top and the per-skill classifier table (and to Which skill "
        "owns what if it overlaps another skill)",
    ),
    "generated.stale": Rule(
        ERROR,
        "the generated plugin tree and content manifests match the skills",
        "regenerate with `uv run --extra dev python scripts/build_plugin.py` "
        "and commit the result; never edit generated files by hand",
    ),
    "generated.unchecked": Rule(
        ERROR,
        "the generated-output check can run",
        "fix the error in the message, then validate again",
    ),
}


@dataclass(frozen=True)
class Problem:
    """One broken rule, located as precisely as possible."""

    #: the file, as a POSIX path, relative to the working directory when under it
    path: str
    rule: str
    message: str
    #: 1-based line in ``path``, when the problem sits on one
    line: int | None = None
    #: the skill it belongs to; None for a checkout-wide problem
    skill: str | None = None
    #: a remediation specific to this problem, overriding the rule's
    hint: str | None = None

    @property
    def level(self) -> str:
        return RULES[self.rule].level

    @property
    def remediation(self) -> str:
        return self.hint or RULES[self.rule].remediation

    def sort_key(self) -> tuple[bool, str, str, int, str, str]:
        # skills by name first, checkout-wide problems last
        return (
            self.skill is None,
            self.skill or "",
            self.path,
            self.line or 0,
            self.rule,
            self.message,
        )


# -- the structural template --------------------------------------------------

#: the one-paragraph severity rubric every review skill's ``## Output``
#: inlines word for word; docs/finding-output.md quotes the same paragraph
#: (a test keeps the two identical), and ``skilldeck new`` writes it
SEVERITY_RUBRIC = """\
Rate `severity` on the shared severity rubric, impact × likelihood:
**critical** — high impact (code execution, auth bypass, stolen credentials or
bulk data, data loss, an outage), readily triggered (by anyone who can reach
it, or in routine operation); **high** — high impact behind a common
precondition (an authenticated user, a collaborator, a routine failure), or
medium impact (limited exposure, degraded service) readily triggered;
**medium** — high impact only under an unusual precondition, medium impact
behind a common one, or low impact readily triggered (a weakened defense
anyone can reach); **low** — medium impact only under an unusual
precondition, or low impact behind any precondition (most defense in depth
and hygiene).
"""

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
# regex (matched against the whitespace-normalized section) -> why it must match
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
# `main..feature`, `<base>..HEAD`; not `...`, and not a `../` path
TWO_DOT_RANGE = re.compile(r"[\w/<>-]*[\w>]\.\.(?!\.)[\w<][\w/<>-]*")


def normalize(text: str) -> str:
    """``text`` with every run of whitespace collapsed to one space."""
    return " ".join(text.split())


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _line_at(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _heading(body: str, heading: str) -> re.Match[str] | None:
    return re.search(rf"^## {re.escape(heading)}[ \t]*$", body, re.M)


def section(body: str, heading: str) -> str:
    """The text under ``## heading`` up to the next level-2 heading."""
    match = re.search(
        rf"^## {re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", _lf(body), re.M | re.S
    )
    return match.group(1) if match else ""


def heading_slug(title: str) -> str:
    """The skill name a ``# Title`` heading spells: ``My Review`` -> my-review."""
    return re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")


def structure_problems(name: str, body: str, path: str = "skill.md") -> list[Problem]:
    """Every structural-template rule the ``skill.md`` of skill ``name`` breaks."""
    body = _lf(body)
    flat = normalize(body)
    problems: list[Problem] = []

    def add(rule: str, message: str, line: int | None = None) -> None:
        problems.append(Problem(path, rule, message, line, name))

    first = body.split("\n", 1)[0]
    if not first.startswith("# "):
        add("structure.heading", "skill.md must open with a '# Title' heading", 1)
    elif heading_slug(first[2:]) != name:
        add(
            "structure.heading",
            f"heading {first!r} does not spell the skill name {name!r}",
            1,
        )
    headings = {heading: _heading(body, heading) for heading in REQUIRED_HEADINGS}
    for heading, why in REQUIRED_HEADINGS.items():
        if headings[heading] is None:
            add("structure.section", f"missing '## {heading}' ({why})")
    for phrase, why in REQUIRED_PHRASES.items():
        if phrase not in flat:
            add("structure.phrase", f"missing {phrase!r} ({why})")
    for heading, rule, patterns in (
        ("Scope", "structure.scope", SCOPE_PATTERNS),
        ("Output", "structure.output", OUTPUT_PATTERNS),
    ):
        found = headings[heading]
        if found is None:
            continue  # reported once, as the missing section
        text = normalize(section(body, heading))
        line = _line_at(body, found.start())
        for pattern, why in patterns.items():
            if not re.search(pattern, text):
                add(rule, f"## {heading} lacks {why} (/{pattern}/)", line)
    output = headings["Output"]
    if output is not None and normalize(SEVERITY_RUBRIC) not in normalize(
        section(body, "Output")
    ):
        add(
            "structure.severity-rubric",
            "## Output does not inline the severity rubric paragraph from "
            "docs/finding-output.md word for word",
            _line_at(body, output.start()),
        )
    if not re.search(NOTHING_IN_SCOPE, flat, re.I):
        add(
            "structure.nothing-in-scope",
            "no line says what to do when the change touches nothing in scope "
            f"(/{NOTHING_IN_SCOPE}/)",
        )
    for match in TWO_DOT_RANGE.finditer(body):
        add(
            "structure.two-dot-range",
            f"two-dot range {match.group(0)!r}",
            _line_at(body, match.start()),
        )
    return problems


def description_problems(
    name: str, description: str, path: str = "meta.yaml"
) -> list[Problem]:
    """The description rules beyond what the registry checks."""
    if description.endswith("."):
        return []
    return [
        Problem(
            path,
            "meta.description-period",
            "description should be one sentence ending with a period",
            skill=name,
        )
    ]


# -- references -----------------------------------------------------------------

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


def reference_problems(name: str, body: str, path: str = "skill.md") -> list[Problem]:
    """Citation hygiene: a source is linked, and none is superseded or stale."""
    body = _lf(body)
    problems: list[Problem] = []
    if not LINK_RE.search(body):
        problems.append(
            Problem(
                path,
                "references.cited-source",
                "no authoritative source is linked (a Markdown link to an "
                "https:// page)",
                skill=name,
            )
        )
    for pattern, current in SUPERSEDED.items():
        for match in re.finditer(pattern, body):
            problems.append(
                Problem(
                    path,
                    "references.superseded",
                    f"{match.group(0)!r} is superseded; cite {current}",
                    _line_at(body, match.start()),
                    name,
                )
            )
    for match in LINK_RE.finditer(body):
        url = match.group(1)
        for prefix, canonical in STALE_URL_PREFIXES.items():
            if url.startswith(prefix):
                problems.append(
                    Problem(
                        path,
                        "references.redirect-url",
                        f"{url} only works through a redirect; use {canonical}",
                        _line_at(body, match.start()),
                        name,
                    )
                )
    return problems


# -- placeholders and docs --------------------------------------------------------


def placeholder_problems(
    text: str, path: str, skill: str | None = None
) -> list[Problem]:
    """One problem if ``text`` still holds :data:`PLACEHOLDER` markers."""
    lines = [
        number
        for number, line in enumerate(_lf(text).split("\n"), start=1)
        if PLACEHOLDER in line
    ]
    if not lines:
        return []
    count = text.count(PLACEHOLDER)
    shown = ", ".join(map(str, lines[:10])) + (", ..." if len(lines) > 10 else "")
    noun = "placeholder remains" if count == 1 else "placeholders remain"
    where = "line" if len(lines) == 1 else "lines"
    return [
        Problem(
            path,
            "content.placeholder",
            f"{count} {PLACEHOLDER} {noun} ({where} {shown})",
            lines[0],
            skill,
        )
    ]


def finding_output_problems(
    doc: str, name: str, path: str = "docs/finding-output.md"
) -> list[Problem]:
    """Whether docs/finding-output.md lists review skill ``name``: in its
    opening list of review skills and in its per-skill classifier table."""
    doc = _lf(doc)
    intro = doc.split("\n## ", 1)[0]
    table = section(doc, "Fields")
    missing = []
    if f"`{name}`" not in intro:
        missing.append("the list of review skills at the top")
    if f"| `{name}` |" not in table:
        missing.append("the per-skill classifier table")
    if not missing:
        return []
    return [
        Problem(
            path,
            "docs.finding-output",
            f"{name} is not in {' or '.join(missing)}",
            skill=name,
        )
    ]
