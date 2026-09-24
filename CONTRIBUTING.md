# Contributing to skilldeck

Thanks for taking the time. Contributions are welcome and held to the same bar as
everything else here — we're picky about code, not about people.

## Before you start

- For anything non-trivial, **open an issue first**. A two-minute chat saves a two-day
  rework.
- Found a security issue? Don't open a public issue — see [SECURITY.md](SECURITY.md).

## Getting set up

You'll need [uv](https://docs.astral.sh/uv/) (there's no system pip in CI).

```bash
git clone https://github.com/IcebergAI/skilldeck && cd skilldeck
uv run --extra dev skilldeck list   # run the CLI in place, no install needed
```

## Making a change

1. Branch off `main`.
2. Keep the change small and focused — one idea per PR.
3. Update tests and docs alongside the code, not afterwards.
4. Record anything notable in [CHANGELOG.md](CHANGELOG.md) under `## [Unreleased]`
   ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format).

### Run the checks before pushing

CI runs lint, format, types, a 3.10–3.14 pytest matrix (plus Windows and macOS, and
the lowest allowed dependency versions), and a workflow lint on every PR. Run the same
checks locally so there are no surprises:

```bash
uv run --extra dev ruff check . && uv run --extra dev ruff format --check . \
  && uv run --extra dev mypy && uv run --extra dev pytest
```

Always pass `--extra dev`: the linters and test runner live in the `dev` extra, and a
bare `uv run` does not install them.

Because the suite also runs on Windows, tests pass `encoding="utf-8"` to every text
read and write (Windows defaults to the locale's code page) and create symlinks through
the `symlink` fixture in `tests/conftest.py`, which skips only when the account may not
create them.

## Authoring or changing a skill

Skills live in `src/skilldeck/skills/<name>/` as a `meta.yaml` + `skill.md`, authored
once in an agent-neutral format — never hand-edit per-agent output. A skill's
`meta.yaml` `name` must match its directory name. See
[docs/authoring-skills.md](docs/authoring-skills.md) for the full guide, and bump that
skill's own `version` in `meta.yaml` whenever its content changes.

## Opening the pull request

- Make sure the checks above pass.
- Fill in the PR template so reviewers know what changed and why.
- Expect a review that's thorough and friendly. Small PRs get reviewed faster.
