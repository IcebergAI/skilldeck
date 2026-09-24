# Skill evals

Golden-diff evals for the bundled skills: each fixture is a tiny repository
with a **planted defect** in its diff, and a skill's job is to find it without
drowning it in noise. This is what makes skill edits measurable instead of
vibes-based — run it before a release, or when changing a skill's wording.

## Running

Requires the [Claude Code CLI](https://claude.com/claude-code) (or any agent
CLI) and an API key; **it calls a real agent and costs real money**, which is
why it is manual and not part of CI.

```bash
python evals/run_evals.py                     # all fixtures
python evals/run_evals.py --skill logging     # one fixture
python evals/run_evals.py --agent-cmd 'claude -p {prompt}'   # default
python evals/run_evals.py --keep              # keep temp repos + reports
```

For each fixture the runner:

1. builds a git repo from `base/` (committed to `main`) and overlays
   `change/` on a `change` branch — the diff under review;
2. installs the skill for Claude at project scope;
3. runs the agent inside the repo with a fixed review prompt;
4. scores stdout only after a successful agent exit: every plant in
   `expected.yaml` must match a distinct finding (repository-relative path,
   overlapping line range, minimum severity, and a whole-word keyword in
   its **Issue** text), and the total finding count must not
   exceed `max-findings` (false-positive pressure).

Failing runs keep their temp directory; each repo contains the raw
`report.txt`. Timeouts and non-zero exits fail the fixture and are recorded
in `agent-error.txt`; stderr is never scored as findings.

Reports follow [the shared finding format](../docs/finding-output.md), with
an indented **Issue** and **Fix** under each header. `-`, `*`, `+` and numbered
top-level bullets are counted equally. Empty reports, zero parsed findings,
malformed finding items and unclosed code fences fail rather than bypass the
finding cap. Fenced examples and unrelated prose do not supply matches.
For evals, the prompt requests a `file:line` or `file:start-end` location even
for dependency findings, so they can be checked against the planted source.

This remains a deterministic lexical check, not a semantic judge: a match
does not establish that the explanation or proposed fix is correct. Inspect
the saved reports when assessing skill quality.

## Fixture layout

```
evals/fixtures/<skill>/
├── base/           # pre-change tree
├── change/         # files overlaid on the change branch (contains the plant)
└── expected.yaml   # skill, plants (file + lines + keywords), max-findings
```

CI validates fixture structure (`tests/test_eval_fixtures.py`): the fixture
loads, targets a bundled skill, the plant is part of the diff, and the repo
builds — no API calls.

Each plant has an inclusive `lines: [start, end]` range in the changed file
and an optional `min-severity` (`low`, `medium`, `high`, `critical`; default
`low`). For example:

```yaml
skill: logging
plants:
  - file: auth/session.py
    lines: [14, 14]
    keywords: [secret, credential, sensitive]
    min-severity: high
max-findings: 4
```

One finding cannot satisfy two plants, including two defects in the same
file. Keywords are case-insensitive and use word boundaries (`lock` does
not match `block` or `lockfile`). CI rejects keywords found verbatim in the
plant's changed file, including comments, so copying code cannot earn a hit.

A skill may have more than one fixture: name the directory for the skill, or
add a `-<variant>` suffix (e.g. `ci-workflow-review-gitlab`) and set the
`skill:` field in `expected.yaml` to the skill it exercises.

## Adding a fixture

Keep it minimal: the smallest `base/` that gives the change context, one
clearly planted defect, keywords that identify the *finding kind* (not words
that appear in the code itself), and a `max-findings` low enough to punish
noise. New skills should land with a fixture.
