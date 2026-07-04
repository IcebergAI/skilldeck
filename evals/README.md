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
4. scores the report: every plant in `expected.yaml` must be mentioned
   (file name + at least one keyword), and the total finding count must not
   exceed `max-findings` (false-positive pressure).

Failing runs keep their temp directory; each repo contains the raw
`report.txt`.

## Fixture layout

```
evals/fixtures/<skill>/
├── base/           # pre-change tree
├── change/         # files overlaid on the change branch (contains the plant)
└── expected.yaml   # skill, plants (file + keywords), max-findings
```

CI validates fixture structure (`tests/test_eval_fixtures.py`): the fixture
loads, targets a bundled skill, the plant is part of the diff, and the repo
builds — no API calls.

A skill may have more than one fixture: name the directory for the skill, or
add a `-<variant>` suffix (e.g. `ci-workflow-review-gitlab`) and set the
`skill:` field in `expected.yaml` to the skill it exercises.

## Adding a fixture

Keep it minimal: the smallest `base/` that gives the change context, one
clearly planted defect, keywords that identify the *finding kind* (not words
that appear in the code itself), and a `max-findings` low enough to punish
noise. New skills should land with a fixture.
