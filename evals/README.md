# Skill evals

Golden-diff evals for the bundled skills: each fixture is a tiny repository
with **planted defects** in its diff (or, for a clean-diff fixture, none), and a
skill's job is to find them without drowning them in noise. This is what makes
skill edits measurable instead of vibes-based — run it before a release, or
when changing a skill's wording.

## Running

Requires the [Claude Code CLI](https://claude.com/claude-code) (or another
agent CLI, see `--adapter`) and an API key; **it calls a real agent and costs
real money**, which is why it is manual and not part of CI.

```bash
python evals/run_evals.py                     # all fixtures
python evals/run_evals.py --skill logging     # one skill's fixtures
python evals/run_evals.py --skill authentication-review-saml   # one fixture
python evals/run_evals.py --repeat 5          # run each fixture 5 times
python evals/run_evals.py --agent-cmd 'claude -p {prompt}'   # default
python evals/run_evals.py --adapter codex --agent-cmd 'codex exec {prompt}'
python evals/run_evals.py --keep              # keep temp repos + reports
```

| Option | Meaning |
| --- | --- |
| `--skill NAME` | Run only the fixtures that exercise skill `NAME`, or the one fixture whose directory is `NAME`. |
| `--agent-cmd CMD` | Agent command line; `{prompt}` is replaced by the review prompt. Default `claude -p {prompt}`. |
| `--adapter NAME` | Which skilldeck adapter installs the skill into the temp repo (`claude`, `codex`, `copilot`, `cursor`, `kiro`; default `claude`). The prompt names the installed file's path, so pair it with that agent's `--agent-cmd`. |
| `--repeat N` | Run each fixture `N` times (fresh repo each time) and print its pass rate — agents are nondeterministic, so one run says little about a borderline fixture. |
| `--timeout S` | Per-run agent timeout in seconds (default 600). |
| `--keep` | Keep the temp repos even when every run passes. |

For each fixture (and each repeat) the runner:

1. builds a git repo from `base/` (committed to `main`) and overlays
   `change/` on a `change` branch — the diff under review;
2. installs the skill through the chosen adapter at project scope;
3. runs the agent inside the repo with a fixed review prompt that points at the
   installed skill (e.g. `.claude/skills/<skill>/SKILL.md`);
4. scores the agent's **stdout** (see [Scoring](#scoring)).

A run fails outright — without scoring — if the agent exits non-zero or times
out. Failing runs print the agent's stderr and keep their temp directory; each
repo contains the raw `report.txt` (stdout) and `stderr.txt`. The process exits
non-zero if any run failed.

## Scoring

The report is split into individual findings using the shared shape in
[`docs/finding-output.md`](../docs/finding-output.md): a finding starts at a
list item whose text opens with `**[severity]` — the marker may be `-`, `*`,
`1.` or `1)` — and runs until the next finding or markdown heading (a `#`
comment inside a fenced code block doesn't count as a heading).

- **Each plant needs its own finding.** A finding satisfies a plant only if it
  names the plant's file (relative path or basename, or one of its `locators`)
  **and** at least one of its `keywords`, and — when the plant sets
  `min-severity` — its severity is at least that high. Two plants in the same
  file need two different findings: plants are matched to findings one-to-one.
- **Whole words, case-insensitive.** `git` does not match `github`, `state`
  does not match `statement`. A keyword may be a phrase (`long method`); it
  matches across a line wrap. Inflections are not folded, so list `lock` and
  `locking` if either would do.
- **False-positive pressure.** The number of parsed findings must not exceed
  `max-findings`.
- **Format drift is loud.** If a fixture has plants but no findings could be
  parsed, the run fails with `no findings parsed — output format drift?`
  rather than a silent miss; an empty stdout fails as `empty report`.

Text outside any finding — the one-line report header, a closing summary under
its own heading — never satisfies a plant, so "`auth/session.py`: no secrets
logged" in a summary doesn't count as finding the defect.

## Fixture layout

```
evals/fixtures/<skill>[-<variant>]/
├── base/           # pre-change tree (include the context a reviewer needs)
├── change/         # files overlaid on the change branch (contains the plants)
└── expected.yaml   # skill, plants, max-findings
```

```yaml
skill: dependency-review          # the bundled skill to install
plants:                           # [] for a clean-diff fixture
  - file: requirements.txt        # a file in change/, part of the diff
    keywords: [confusion, public index]   # words that describe the defect
    min-severity: high            # optional: low | medium | high | critical
    locators: [corp-auth-client]  # optional: other terms that locate a finding
max-findings: 3                   # cap on total findings (>= number of plants)
```

`expected.yaml` is validated when loaded: unknown keys, a `min-severity` off
the scale, empty keyword lists, and a `max-findings` below the number of plants
are all errors.

- `locators` is for skills whose finding location isn't a file path —
  `dependency-review` reports `package old→new`, so its fixture lists the
  package name.
- `min-severity` should be the lowest severity the skill's own severity rubric
  could defensibly assign the plant (usually one step below what the rubric
  names), so it catches a critical defect reported as `[low]` without making
  the eval flaky.

CI validates fixture structure (`tests/test_eval_fixtures.py`): the fixture
loads, targets a bundled skill, every plant is part of the diff, no plant
keyword appears verbatim in its planted file, and the repo builds — no API
calls. The scorer itself is unit-tested in `tests/test_eval_scoring.py`.

A skill may have more than one fixture: name the directory for the skill, or
add a `-<variant>` suffix (e.g. `ci-workflow-review-gitlab`) and set the
`skill:` field in `expected.yaml` to the skill it exercises.

## Adding a fixture

Keep it minimal: the smallest `base/` that gives the change the context the
skill says it judges by (engine and table size for a migration, the trigger
and permissions for a workflow), clearly planted defects, and a `max-findings`
low enough to punish noise. Keywords must identify the *finding kind* — words a
correct finding would use to describe the defect, not identifiers copied from
the code (a structural test rejects those). Avoid copying the skill's own
worked example: an eval that plants the example mostly tests recall of the
example.

**Clean-diff fixtures** (`plants: []`) measure false positives: a change that
looks risky but is correct (e.g. `security-review-clean` replaces string-built
SQL with a parameterized, owner-scoped query; `resilience-review-clean` adds a
timeout and a bounded, jittered retry to an idempotent GET). Set
`max-findings` to `0`, or `1` to tolerate a single hygiene nit. New skills
should land with a planted fixture, and ideally a clean one.
