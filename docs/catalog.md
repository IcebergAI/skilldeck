# The skill catalog

`skilldeck catalog --json` describes every bundled skill for tools: registries,
policy checks, update bots, or anything else that should not parse
`skilldeck list`. The output is a stable, versioned contract; this page
describes it and the rules for changing it.

```bash
skilldeck catalog --json                          # every bundled skill
skilldeck catalog --json --category security      # repeat for any of several
skilldeck catalog --json --agent claude           # repeat to require several
skilldeck catalog --schema                        # the JSON Schema it follows
skilldeck catalog                                 # a readable table
```

To read the catalog of a particular release without installing it, run the
command from that release's wheel, e.g. `uvx skilldeck@X.Y.Z catalog --json`.
Releases do not publish the catalog as a separate asset: it is derived
entirely from the wheel, so verify the wheel as described in
[Verifying a Skilldeck release](verifying-releases.md) and generate the catalog
from it, rather than trusting a second file that could drift from it.

## What it contains

```json
{
  "schema_version": 1,
  "distribution": {
    "name": "skilldeck",
    "version": "X.Y.Z",
    "source_repository": "https://github.com/IcebergAI/skilldeck",
    "source_ref": "refs/tags/vX.Y.Z",
    "source_commit": "<40 hex digits>"
  },
  "skills": [
    {
      "name": "security-review",
      "version": "0.5.1",
      "category": "security",
      "description": "...",
      "supported_agents": ["claude", "codex", "copilot", "cursor", "kiro"],
      "canonical_sha256": "sha256:<64 hex digits>",
      "rendered_sha256": {
        "claude": "sha256:<64 hex digits>",
        "codex": "sha256:<64 hex digits>",
        "copilot": "sha256:<64 hex digits>",
        "cursor": "sha256:<64 hex digits>",
        "kiro": "sha256:<64 hex digits>"
      },
      "source": {
        "repository": "https://github.com/IcebergAI/skilldeck",
        "path": "src/skilldeck/skills/security-review"
      },
      "deprecated": null,
      "capabilities": {
        "schema": 1,
        "files": {"read": "repo", "write": "none"},
        "commands": ["git fetch", "git diff", "git ls-files"],
        "network": [
          "the git remote, via git fetch, to bring the base branch up to date"
        ],
        "credentials": [],
        "tools": [],
        "artifacts": []
      }
    }
  ]
}
```

- `distribution` is the package identity, exactly as
  `skilldeck provenance --json` reports it. `source_ref` and `source_commit`
  are `null` for a build that is not a tagged release.
- `skills` lists every bundled skill exactly once, sorted by `name`.
  `supported_agents` is sorted. Filters (`--category`, `--agent`) only drop
  entries; they never change one. A `--category` no skill has still gives a
  valid (possibly empty) catalog and exit status 0, with a warning on stderr
  naming the categories that exist.
- `canonical_sha256` is the skill's canonical content digest over its
  `meta.yaml` and `skill.md`: the value in the packaged content manifest, which
  `skilldeck provenance --verify` checks.
- `rendered_sha256` maps each agent in `supported_agents` to the SHA-256 of
  the file skilldeck installs for that agent (its native `SKILL.md`; the
  opt-in legacy formats are not listed). See
  [Canonical and rendered digests](#canonical-and-rendered-digests).
- `source.path` is the skill's directory in `source.repository`, as a POSIX
  path; combine it with `distribution.source_commit` for a permanent link.
- `deprecated` is `null`, or an object with `since` (the skill version that
  first carried the deprecation), `replacement` (the skill to use instead, or
  `null`) and `reason`. See
  [Deprecating a skill](authoring-skills.md#deprecating-a-skill).
- `capabilities` is what the skill declares it may ask an agent to do,
  exactly as its `meta.yaml` states it: `schema` (the capability schema,
  `1`), `files.read` (`none`, `diff` or `repo`), `files.write` (`none` or
  `repo`), and the `commands`, `network`, `credentials`, `tools` and
  `artifacts` lists in the order the skill declares them, `[]` for none.
  Anything not listed is not requested; the declaration is for review, and
  nothing enforces it. See
  [Capabilities](authoring-skills.md#capabilities). `schema` is always `1`
  under catalog `schema_version` 1: a new capability schema is a breaking
  catalog change, which bumps `schema_version`.

`catalog` runs the full `skilldeck provenance --verify` check first. If any
installed skill no longer matches its recorded digest, is missing, has a file
the content manifest does not list next to it (OS and editor leftovers
included), or has a `meta.yaml`, `skill.md` or skill directory that is a
symlink or junction (or the skills directory holds anything else), it prints
each problem on stderr, nothing on stdout, and exits 1. It never produces a
catalog for content the package did not ship. See the
[bundle rules](authoring-skills.md#what-a-skill-directory-may-hold).

The output is deterministic: the same installed package always prints the same
bytes on every platform: UTF-8 (in fact ASCII, with `\u` escapes), sorted
keys, two-space indent, `\n` line endings and a final newline. The JSON is
written as bytes, so Windows does not turn the newlines into CRLF.

The schema ships in the package as `skilldeck/catalog.schema.json`, so
`skilldeck catalog --schema` always prints the schema matching the installed
version; the test suite validates the catalog against it. Some guarantees are
stronger than JSON Schema can express, and consumers may rely on them
anyway: `skills` is sorted by `name` with one entry per name, and
`rendered_sha256` has exactly the keys in `supported_agents`.

## Canonical and rendered digests

The two digests answer different questions:

- `canonical_sha256` identifies the skill **source**: one value per skill,
  whichever agent you install it for. It is a domain-separated hash of
  `meta.yaml` and `skill.md` with line endings normalised, the identity
  release verification and `provenance --verify` use. You cannot recompute it
  from an installed file.
- `rendered_sha256.<agent>` identifies the **installed file** for that agent.
  The value after `sha256:` is exactly the `hash=` in the install stamp that
  ends every file skilldeck writes:

  ```
  <!-- skilldeck name=security-review version=0.5.1 hash=<64 hex digits> -->
  ```

  The stamp's hash covers the file's bytes up to (not including) that last
  line. It depends on the rendering code as well as the skill, so a skilldeck
  upgrade can change it without a skill version change; the skill `version`
  and `canonical_sha256` stay put in that case.

To check an installed skill against the catalog, compare the stamp's `name`
and `version` with the entry, then its `hash=` with
`rendered_sha256.<agent>`. Also hash the content above the stamp yourself: a
stamp whose hash no longer matches the content means local edits
(`skilldeck status` reports this as "modified locally").

## Compatibility rules

`schema_version` is an integer, currently `1`. Check it before reading
anything else, and reject a version you do not know.

These are **additive** and keep the same `schema_version`:

- a new property on any object, including a new optional field in
  `deprecated` or `source`;
- a new skill, category or agent name, or a skill removed from the bundle
  (catalog content, not schema).

Consumers must ignore properties they do not recognise, and the published
schema allows them, so a consumer built for an older catalog keeps working.

These are **breaking** and bump `schema_version`:

- removing or renaming a property, or moving it to another object;
- changing a property's type, or allowing `null` where it was not allowed;
- changing what a value means, such as the digest algorithm, the bytes
  `canonical_sha256` covers, `rendered_sha256` no longer matching the install
  stamp, or the meaning of `since`;
- a new capability schema (`capabilities.schema`), or a new value for
  `capabilities.files.read` or `capabilities.files.write`;
- dropping a guarantee on this page, such as the sort order or one entry per
  skill.

A breaking change updates `CATALOG_SCHEMA_VERSION` in
`src/skilldeck/catalog.py`, the schema's `schema_version` constant and title,
this page, and the CHANGELOG entry, which says what changed.
