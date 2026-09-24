# Skill evals

Golden-diff evals for the bundled skills: each fixture is a tiny repository
with **planted defects** in its diff (or, for a clean-diff fixture, none), and a
skill's job is to find them without drowning them in noise. This is what makes
skill edits measurable instead of vibes-based — run it before a release, or
when changing a skill's wording.

## Running

Requires an agent CLI — [Claude Code](https://claude.com/claude-code) by
default, or the OpenAI Codex CLI, or any other through `--agent-cmd` — and its
credentials; **it calls a real agent and costs real money**, which is why it is
manual and not part of CI. Check the plan first with `--dry-run`, which invokes
no agent.

```bash
python evals/run_evals.py --dry-run           # validate fixtures, print the plan
python evals/run_evals.py                     # all fixtures, Claude Code
python evals/run_evals.py --skill logging     # one skill's fixtures
python evals/run_evals.py --skill authentication-review-saml   # one fixture
python evals/run_evals.py --repeat 5 --skill logging   # pass rate per fixture
python evals/run_evals.py --harness codex     # Codex CLI + the codex adapter
python evals/run_evals.py --model sonnet      # request a model from the harness
python evals/run_evals.py --agent-cmd 'my-agent --print {prompt}'   # any CLI
python evals/run_evals.py --replay path/to/run-record.json   # same config again
python evals/run_evals.py --keep              # keep the review repos
```

| Option | Meaning |
| --- | --- |
| `--skill NAME` | Run only the fixtures that exercise skill `NAME`, or the one fixture whose directory is `NAME`. |
| `--harness NAME` | Agent CLI preset: `claude` (default), `codex`, or `custom` (see [Harnesses](#harnesses)). A preset sets the command and the adapter that matches it. |
| `--agent-cmd CMD` | Agent command line, overriding the preset's; `{prompt}` is replaced by the review prompt and `{model}` by `--model`. Without `--harness`, it makes a `custom` harness. |
| `--adapter NAME` | Which skilldeck adapter installs the skill into the temp repo (`claude`, `codex`, `copilot`, `cursor`, `kiro`). Defaults to the harness's (`claude` for `custom`). The prompt names the installed file's path, so it must be the adapter the agent reads. |
| `--model NAME` | Model to request, substituted for `{model}` (the presets pass it as `--model NAME`) and recorded. Without it the harness's own default is used, and not recorded. |
| `--repeat N` | Run each fixture `N` times (fresh repo each time) and print its pass rate — agents are nondeterministic, so one run says little about a borderline fixture. |
| `--timeout S` | Per-run agent timeout in seconds (default 600). |
| `--max-runs N` | Refuse to start if more than `N` runs (fixtures × repeats) are planned (default 50). |
| `--dry-run` | Validate the fixtures and print the planned runs; no agent (or anything else) is run. Exits 2 on an invalid fixture or a plan over `--max-runs`. |
| `--replay RECORD` | Re-run a [run record](#run-records)'s exact configuration; see [Replaying](#replaying). |
| `--include-reports` | Also copy each run's raw stdout and stderr into the run record. |
| `--keep` | Keep the review repos even when every run passes. |

For each fixture (and each repeat) the runner:

1. builds a git repo from `base/` plus the skill, installed through the
   chosen adapter at project scope (committed to `main`, so the skill file is
   neither in the diff nor an untracked change the skill would review);
2. overlays `change/` on a `change` branch — the diff under review;
3. runs the agent inside the repo with a fixed review prompt that points at the
   installed skill (e.g. `.claude/skills/<skill>/SKILL.md`);
4. scores the agent's **stdout** (see [Scoring](#scoring)).

A run fails outright — without scoring — if the agent exits non-zero or times
out; failing runs print the agent's stderr. Runs are **sequential** (concurrency
1): one agent at a time, so `--max-runs` bounds the spend and the wall-clock
time together.

Everything lands in a temp work dir, printed at the start:

```
skilldeck-evals-XXXX/
├── run-record.json                        # the run record (below)
├── artifacts/run-<N>/<fixture>/report.txt # raw stdout, the scored report
├── artifacts/run-<N>/<fixture>/stderr.txt
└── repos/run-<N>/<fixture>/               # the review repos
```

The review repos are deleted when every run passes (unless `--keep`); the
record and the raw output are always kept. The process exits 0 when every run
passed, 1 when any failed, 2 when the evals could not run (invalid fixture,
budget, changed digests on replay, agent command not found) and 130 when
interrupted — the record is written in every case that started running.

## Harnesses

| Harness | Command | Adapter | Version probe |
| --- | --- | --- | --- |
| `claude` | `claude -p {prompt}`; with a model `claude --model {model} -p {prompt}` | `claude` | `claude --version` |
| `codex` | `codex exec {prompt}`; with a model `codex exec --model {model} {prompt}` | `codex` | `codex --version` |
| `custom` | `--agent-cmd`, verbatim | `--adapter` (default `claude`) | none |

Both presets run the agent's documented non-interactive mode with no other
flags: Claude Code's print mode, and `codex exec`, which prints the final
message on stdout (progress goes to stderr, which is not scored) and runs in a
read-only sandbox by default. The Codex preset is best-effort — it has not yet
been exercised in a recorded run. `--agent-cmd` overrides a preset's command
but keeps its name, adapter and version probe (the command's own executable
with `--version`); add flags there, such as an approval or sandbox mode. A
harness that reports token usage or cost would fill the record's `usage` and
`cost_usd`; no preset parses them yet, so both are `null`.

## Run records

Every run writes `run-record.json`, a provider-neutral, schema-versioned record
([`run-record.schema.json`](run-record.schema.json), JSON Schema 2020-12) with
sorted keys and LF newlines, so equal records are equal bytes on every
platform:

- **what ran**: the skilldeck version, the checkout's git commit and whether
  it had uncommitted changes (`null` outside a checkout), and the digest of
  `run_evals.py` itself (the scorer and the prompt);
- **against what**: per fixture, a digest of every file in its directory
  (newlines normalised, so a Windows checkout agrees), the skill's name,
  version, canonical digest (the one in `src/skilldeck/_content_manifest.json`)
  and the digest of the file the adapter installed, plus the exact prompt;
- **how**: the harness name, the exact command template, the model (if
  requested), the harness version (the probe's first line, `null` if it
  failed), the adapter, and the repeat, timeout and budget;
- **every planned run**: its status — `passed`, `failed` (scored and
  missed), `agent_failed` (non-zero exit), `timed_out`, `error` (the repo
  could not be built, or the agent could not start) or `not_run` (the
  invocation stopped early) — with start and end timestamps, duration, exit
  code, parsed finding count, the scorer's reasons, and the paths of its raw
  output, relative to the record;
- a **summary**: planned, attempted, passed, failed and not-run counts.

The record never contains the raw reports or stderr unless you pass
`--include-reports`, so it can be shared as-is; the raw files stay in the work
dir beside it.

## Replaying

`--replay RECORD` re-runs the recorded fixtures with the recorded harness,
command, model, adapter, repeat count and timeout (so it takes no other
configuration options; `--max-runs`, `--dry-run`, `--keep` and
`--include-reports` still apply). Before anything runs it recomputes every
fixture digest and skill digest and **refuses** (exit 2) if any fixture, skill
or installed skill file changed since the record — a changed eval is a
different experiment. A different harness version or a changed runner is
printed as a note, not refused. The new record's `config.replay_of` holds the
digest of the record it replayed; comparing the two records' runs is the
variance check. `--replay RECORD --dry-run` verifies the digests without
running anything.

## Scoring

The report is split into individual findings using the shared shape in
[`docs/finding-output.md`](../docs/finding-output.md): a finding starts at a
list item whose text opens with `**[severity]` — the marker may be `-`, `*`,
`1.` or `1)` — and, like a markdown list item, runs until the next finding, a
heading, a thematic break (`---`), a sibling list item, or, after a blank
line, text that is no longer indented past the bullet (an unindented
`**Issue:**` or `**Fix:**` line is tolerated). Fenced code inside a finding is
opaque, so a `#` comment in a suggested fix isn't a heading; a fence closes
only on a run of the same character at least as long as the one that opened
it. A report wrapped in a ```` ```markdown ```` fence still parses, and the
wrapper's closing fence ends the last finding.

- **Each plant needs its own finding.** A finding satisfies a plant only if it
  names the plant's file (relative path or basename, or one of its `locators`)
  **and** at least one of its `keywords`, and — when the plant sets
  `min-severity` — its severity is at least that high. Two plants in the same
  file need two different findings: plants are matched to findings one-to-one.
- **Whole words, case-insensitive.** `git` does not match `github`, `state`
  does not match `statement`. A keyword may be a phrase (`long method`); it
  matches across a line wrap and inline markdown (`no assert` matches
  ``no `assert` ``). Inflections are not folded and a stem never matches
  (`re-pars` matches nothing), so list `lock` and `locking` if either would do.
- **False-positive pressure.** The number of parsed findings must not exceed
  `max-findings`.
- **Format drift is loud.** If a fixture has plants but no findings could be
  parsed, the run fails with `no findings parsed — output format drift?`
  rather than a silent miss. On any fixture, clean ones included, a list item
  led by a severity in another shape (`1. [high] …`, `- **High** — …`) fails
  the run as `output format drift?` too: a finding the parser can't see would
  otherwise not count toward `max-findings`. An empty stdout fails as
  `empty report`.

Text outside any finding — the one-line report header, a closing summary after
the last finding — never satisfies a plant, so "`auth/session.py`: no secrets
logged" at the end of a report doesn't count as finding the defect.

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
    keywords: [confusion, same name]      # words that describe the defect
    min-severity: medium          # optional: low | medium | high | critical
    locators: [corp-auth-client]  # optional: other terms that locate a finding
max-findings: 3                   # cap on total findings (>= number of plants)
```

`expected.yaml` is validated when loaded: unknown keys, a `min-severity` off
the scale, empty keyword lists, and a `max-findings` below the number of plants
are all errors.

- `locators` is for skills whose finding location isn't a file path —
  `dependency-review` reports `package old→new`, so its fixture lists the
  package name.
- `min-severity` is a floor, not the expected rating: set it one step below
  the level the skill's severity rubric (or its worked example) gives the
  defect, so it catches a critical defect reported as `[low]` without failing
  a run over a one-step disagreement.

CI validates fixture structure (`tests/test_eval_fixtures.py`): the fixture
loads, targets a bundled skill, every plant is part of the diff, no plant
keyword appears verbatim in its planted file, and the repo builds — no API
calls. Each planted fixture also has sample reports there
(`SAMPLE_REPORTS`): a correct report must pass, and a finding about a
different real defect in the same file must satisfy no plant, which catches
keywords that are too narrow to match or generic enough to match the wrong
finding. The scorer itself is unit-tested in `tests/test_eval_scoring.py`, and
the run records, harness presets, budgets, dry runs and replay, with stand-in
agents, in `tests/test_eval_runs.py`.

A skill may have more than one fixture: name the directory for the skill, or
add a `-<variant>` suffix (e.g. `ci-workflow-review-gitlab`) and set the
`skill:` field in `expected.yaml` to the skill it exercises.

## Adding a fixture

Keep it minimal: the smallest `base/` that gives the change the context the
skill says it judges by (engine and table size for a migration, the trigger
and permissions for a workflow), clearly planted defects, and a `max-findings`
low enough to punish noise. Keywords must identify the *finding kind* — words a
correct finding would use to describe the defect, not identifiers copied from
the code (a structural test rejects those), nor a category or fix that also
fits other defects in the file (a CICD-SEC classifier, "Extract"). Plant every
serious defect the file really has, so a report can't pass on the wrong one,
and add the fixture's `SAMPLE_REPORTS` entry. Avoid copying the skill's own
worked example: an eval that plants the example mostly tests recall of the
example.

**Clean-diff fixtures** (`plants: []`) measure false positives: a change that
looks risky but is correct (e.g. `security-review-clean` replaces string-built
SQL with a parameterized, owner-scoped query; `resilience-review-clean` adds a
timeout and a bounded, jittered retry to an idempotent GET). Set
`max-findings` to `0`, or `1` to tolerate a single hygiene nit. New skills
should land with a planted fixture, and ideally a clean one.
