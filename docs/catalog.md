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
      "source": {
        "repository": "https://github.com/IcebergAI/skilldeck",
        "path": "src/skilldeck/skills/security-review"
      },
      "deprecated": null
    }
  ]
}
```

- `distribution` is the package identity, exactly as
  `skilldeck provenance --json` reports it. `source_ref` and `source_commit`
  are `null` for a build that is not a tagged release.
- `skills` lists every bundled skill exactly once, sorted by `name`.
  `supported_agents` is sorted. Filters (`--category`, `--agent`) only drop
  entries; they never change one.
- `canonical_sha256` is the skill's canonical content digest over its
  `meta.yaml` and `skill.md`: the value in the packaged content manifest, which
  `skilldeck provenance --verify` checks. `catalog` recomputes it from the
  installed files and exits 1, printing nothing on stdout, if any skill no
  longer matches, so a catalog is never produced for content the package did
  not ship.
- `source.path` is the skill's directory in `source.repository`, as a POSIX
  path; combine it with `distribution.source_commit` for a permanent link.
- `deprecated` is `null`, or an object with `since` (the skill version that
  first carried the deprecation), `replacement` (the skill to use instead, or
  `null`) and `reason`. See
  [Deprecating a skill](authoring-skills.md#deprecating-a-skill).

The output is deterministic: the same installed package always prints the same
JSON text (sorted keys, two-space indent, ASCII only with `\u` escapes, ending
in a newline).

The schema ships in the package as `skilldeck/catalog.schema.json`, so
`skilldeck catalog --schema` always prints the schema matching the installed
version; the test suite validates the catalog against it.

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
- changing what a value means, such as the digest algorithm or the bytes
  `canonical_sha256` covers, or the meaning of `since`;
- dropping a guarantee on this page, such as the sort order or one entry per
  skill.

A breaking change updates `CATALOG_SCHEMA_VERSION` in
`src/skilldeck/catalog.py`, the schema's `schema_version` constant and title,
this page, and the CHANGELOG entry, which says what changed.
