# Lifecycle and compatibility

This page is skilldeck's contract for change. It says what each kind of
version bump promises, how long a deprecated skill, agent or format stays,
what happens to files you have already installed, and which output you can
build tools on. It applies to every published release, starting with the
first one.

A CI check enforces the parts a script can check (see
[Release checks](#release-checks)). The rest is for reviewers.

## At a glance

| Change | Package release (before 1.0 / from 1.0) | Notice | CHANGELOG entry |
|---|---|---|---|
| Fix a skill's wording, typos or citations | patch | none | Changed or Fixed |
| Add a skill, agent, format, command, option or catalog field | minor / minor | none | Added |
| Deprecate a skill, agent, format, command or option | minor / minor | none: this starts the notice period | Deprecated (checked for skills) |
| Remove a skill | minor / major | deprecation published at least 90 days earlier (180 from 1.0; a maintainer policy choice) (checked) | Removed (checked) |
| Remove an agent or format, or drop an agent from one skill | minor / major | the same, unless the vendor removed it first | Removed (checked) |
| Make a breaking change to a skill (a minor bump while the skill is 0.x, a major one from 1.0.0) | minor / minor | none: read the entry before `update` | Changed, with the new version (checked for a new major) |
| Change the stamp format | minor / minor | none: old stamps stay readable | Changed |
| Bump the catalog's `schema_version` | minor / major | none | **Breaking:** (checked) |
| Fix an urgent security problem | whatever the change needs | may skip all of it | Security, plus an advisory |

## Versions

### The package

The package version (`pyproject.toml`, and `skilldeck --version`) follows
[SemVer](https://semver.org/). It covers skilldeck's public surface:

- the commands, their options, defaults and exit codes;
- which skills and agents exist, by name;
- where each adapter installs, and the file it writes (the
  [compatibility matrix](compatibility.md));
- the install stamp;
- the machine-readable output listed under
  [The command line](#the-command-line);
- the `meta.yaml` fields skill authors can use;
- the Python versions it runs on.

A skill's guidance is versioned by the skill itself (see
[Skill versions](#skill-versions)), not by the package.

**Before 1.0 (now)**, a breaking change bumps the minor version (`0.4.0` →
`0.5.0`). A deprecation, or a new skill, agent, format, command, option or
catalog field, also needs at least a minor release. Fixes can go in either
kind of release. So a patch release (`0.4.0` → `0.4.1`) only fixes things:
it never adds a feature, or removes, deprecates or breaks anything, and is
always safe to take.

A change is breaking if it does any of these:

- removes a skill, agent, format, command or option;
- moves an install location, or changes the stamp so that existing installs
  are no longer recognised;
- bumps the `schema_version` of the catalog or of `provenance --json`;
- changes a default, or what an exit code means;
- drops a Python version (0.2.0 dropped 3.9).

**From 1.0**, a breaking change needs a major release, a deprecation or a new
feature needs a minor release, and a fix needs a patch release. Dropping a
Python version counts as a minor change once that version has reached its
upstream end of life. Dropping one that upstream still supports is breaking.

The release check holds releases to this. The newest dated CHANGELOG section
can't be a patch release if it has `### Removed` or `### Deprecated` entries,
or an entry marked **Breaking:**. From 1.0, Removed and Breaking entries need
a major release. `scripts/prepare_release.py` refuses such a version before
it writes anything. Reviewers check the rest, such as a new feature slipped
into a patch release.

`### Removed` is only for removals from the public surface above: skills,
agents and adapters, commands and options, fields of the stable output
formats, and `meta.yaml` fields. Removing internal code, such as an unused
helper function, is a `### Changed` entry, so it doesn't force a minor
release.

### Skill versions

Each skill's `version` in `meta.yaml` is SemVer too, applied to what the skill
tells the agent to do. Like the package, a skill gets SemVer's 0.x exception:
while it is 0.x, a change that would be major bumps its minor version
(`0.4.0` → `0.5.0`). From 1.0.0 it follows SemVer fully. So a shared change,
such as a new severity rubric in every review skill, doesn't push every 0.x
skill to 1.0.0.

| Bump (from 1.0.0) | When the change | Examples |
|---|---|---|
| major | takes something away, or changes the shape of the result | removing a checklist area or a kind of finding; narrowing what the skill reviews; handing an area to another skill in [Which skill owns what](finding-output.md#which-skill-owns-what); changing the output shape (the finding format, severity rubric or report header) |
| minor | adds to what the skill does, without taking anything away | new checks or a new checklist area; new sources that add checks; covering another kind of file; deprecating the skill; changing its `category`, which moves it between `catalog --category` filters |
| patch | leaves what it reports unchanged | wording, typos, clarifications, citation and link fixes, a clearer worked example, a new `description` |

While a skill is 0.x, read "major" in this table as a minor bump, and "minor"
as a minor or patch bump.

Adding an agent to `supported-agents` is a patch. Dropping one follows
[Dropping an agent from a skill](#dropping-an-agent-from-a-skill).

A breaking skill change needs at least a minor package release, and a
`### Changed` entry naming the skill and its new version, saying what changed
and what users should do. The release check requires that entry when the
skill's major version goes up (0.x → 1.0.0, 1.x → 2.0.0); for a 0.x skill's
breaking minor bump, and for the package release it lands in, it is a
reviewer's job.

How skill versions meet `status` and `update`:

- Each installed file's stamp records the skill version, so
  `skilldeck status` shows `1.3.0 stale (bundled: 2.0.0)` when a newer version
  is bundled.
- "Stale" compares content, not versions. A file is stale whenever it differs
  from what installing now would write. A skilldeck upgrade that changes how
  a skill is rendered makes installs stale with the same version on both
  sides.
- `skilldeck update` rewrites every stale, unedited install, whatever the size
  of the bump. It never overwrites a locally modified install without
  `--force`. Check the CHANGELOG for breaking skill changes before you run it.
  To stay on the old guidance for a while, keep running the older skilldeck
  release (`uvx skilldeck@X.Y.Z`), or edit the installed file, which `update`
  then leaves alone.

## Deprecating a skill

A deprecated skill stays in the bundle, installable and listed, for the
notice period. To deprecate one:

1. Add `deprecated` to its `meta.yaml` and bump its minor version.
   [Deprecating a skill](authoring-skills.md#deprecating-a-skill) gives the
   fields and the rules the loader applies:

   ```yaml
   version: 1.3.0
   deprecated:
     since: 1.3.0               # the skill's own version, not skilldeck's
     replacement: new-review    # optional
     reason: Renamed to new-review.
   ```

   `reason` is required, so a skill without a replacement still says why.
2. Add a `### Deprecated` entry under `[Unreleased]` in `CHANGELOG.md` (checked).
   Name the skill in backticks, give its replacement or the reason, and say
   that it will be removed no earlier than 90 days after the release (180
   from 1.0).
3. Ship it in a minor release.

Once it's released:

- `skilldeck list` and `skilldeck catalog` mark it
  `(deprecated since 1.3.0; use new-review)`;
- `install` and `update` print a warning on stderr whenever they write it;
- `skilldeck catalog --json` reports `deprecated` with `since`, `replacement`
  and `reason`, for tools.

Installed copies keep working, and `update` keeps them current. A deprecated
skill still gets fixes, security fixes included, but no new checks. New work
goes into its replacement.

Claude Code plugin users see no warning. The plugin carries the skill
unchanged, so the CHANGELOG is where they learn about the deprecation.

## Removing a skill

The notice period has two parts:

- the deprecation must ship in at least one **published** release: a
  `vX.Y.Z` tag on `main` whose own files mark the skill `deprecated` and whose
  own CHANGELOG has a `### Deprecated` entry naming it;
- the removal can merge no sooner than **90 days** after that release (**180
  days** from 1.0), counted from the later of its CHANGELOG date and its tag's
  date. Before 1.0 it goes in a minor release, and from 1.0 in a major one.

The 90 and 180 days, like the 7-day target under
[Security fixes](#security-fixes), are the maintainers' policy choices rather
than anything an outside standard sets. Changing one means changing this page
and `scripts/check_lifecycle.py` together.

Why these numbers:

- Users see a deprecation only through a release. `list`, `install`,
  `update` and the catalog report the deprecation state of the version you
  run, so a deprecation that no release has published has warned nobody.
- 90 days is a quarter. A team that upgrades its tools quarterly, whether
  pinned in CI or on a `uv tool upgrade` schedule, gets at least one release
  that warns before the skill is gone.
- Before 1.0 the set of skills is small and still changing, so waiting longer
  mostly delays the cleanup. From 1.0, 180 days gives two quarterly upgrade
  cycles, and removals are collected into the rarer major releases.

To remove the skill:

1. Delete its directory and regenerate the plugin (`scripts/build_plugin.py`).
2. Add a `### Removed` entry naming the skill (checked). Say what replaces it
   and how to delete installed copies (see below).

The release check also requires the skill to have been deprecated at the
base of the pull request. If any release tag contains the skill, it also
requires a release to have published the deprecation for the notice period.
It reads that from the release tags themselves, not from the pull request's
CHANGELOG, so a Deprecated entry added to an old section afterwards doesn't
count. A skill that no release ever contained must still be deprecated first,
but it has no waiting period. [Security fixes](#security-fixes) can skip all
of this.

A removed skill is gone from `list` and from the catalog. The catalog has no
"removed" state: the CHANGELOG's Removed entry is the record, and the release
check makes sure it exists.

### What happens to installed copies

skilldeck never deletes a removed skill's files by itself. After you upgrade
to a release without the skill:

- `skilldeck status --agent <agent>` lists each leftover copy as
  `orphan: <path> (<name> <version>)`;
- `skilldeck update` ignores it, so the copy stays as it was and the agent
  keeps loading it;
- `skilldeck uninstall <name>` fails with `error: unknown skill: <name>`, and
  `uninstall --all` leaves it alone, because `uninstall` only knows bundled
  skills.

To get rid of a copy, delete it yourself (the file, and the `<name>/` folder
it sits in for a `SKILL.md` agent), using the path `status` prints. You can
also run `skilldeck uninstall <name> --agent <agent>` before you upgrade,
while you still have a release that bundles the skill. Claude Code plugin
users lose the skill when the plugin next updates after the removal reaches
`main`.

### Renaming a skill

A rename is a new skill plus a deprecation:

1. In one pull request, add the skill under its new name and mark the old one
   `deprecated` with `replacement: <new name>`. The new skill must support
   every agent the old one does, or the loader refuses the replacement. Add
   an `### Added` entry for the new name and a `### Deprecated` entry for the
   old one.
2. Both ship for the notice period. `skilldeck install <old name>` still
   works, and warns you to use the new name. The catalog lists the old skill
   with its `replacement`, so tools can move users over.
3. Remove the old skill as described above.

Users switch by installing the new name and uninstalling the old one. Both
commands work throughout the notice period:

```bash
skilldeck install new-review --agent claude
skilldeck uninstall old-review --agent claude
```

`test_walkthrough_renaming_a_skill` in `tests/test_lifecycle.py` runs through
these steps, checking the catalog and the release check at each one.

## Agents and formats

skilldeck supports an agent while the vendor ships it and a primary source
confirms where it reads skills: the agent's code, a shipped binary, or the
vendor's docs. It doesn't promise to support every agent, or every agent
version, forever. The [compatibility matrix](compatibility.md) lists each
agent and format, and how each was checked.

### Adding an agent or format

A new agent (a native adapter) or a new legacy format is a feature. It ships
in a minor release with an `### Added` entry, the adapter's contract fixtures
and a matrix row. See [Adding a new agent](adapters.md#adding-a-new-agent).

### When the vendor changes something

Follow
[When a vendor changes a location or format](compatibility.md#when-a-vendor-changes-a-location-or-format).
The vendor's timeline wins. skilldeck points its adapter at the new location
as soon as a primary source confirms the move. It keeps the old format as an
opt-in legacy adapter while agent versions still in use read it, and adds it
to `MIGRATIONS` so that `skilldeck migrate --agent <agent>` moves existing
installs.

A format the vendor has stopped loading leaves nothing to protect. It can
stop being an install target without notice and stay only as a `migrate`
source, as happened when Codex dropped custom prompts in 0.118.0. If users
have to move their installs, the CHANGELOG entry is marked **Breaking:** and
gives the `migrate` command to run.

### Removing an agent or format

When skilldeck itself drops an agent or a legacy format, for example because
the product was discontinued or can no longer be checked, it follows the same
steps as for a skill:

1. **Deprecate** the adapter in a minor release, with a `### Deprecated`
   entry naming it and a note in its matrix row.
2. **Wait** for the same notice period: 90 days after the release that
   published the deprecation (180 from 1.0).
3. **Remove** it from `ADAPTERS` or `LEGACY_ADAPTERS`, along with its
   contract fixtures and matrix row. Add a `### Removed` entry of its own
   that names the adapter and no skill (checked), and lists the paths it
   installed to. An entry saying one skill no longer supports the agent
   doesn't count. If a successor format exists, keep the old one in
   `MIGRATIONS` so that `migrate` can still move installs.

After the removal, skilldeck rejects `--agent <name>`, so `status` and
`uninstall` can no longer see that adapter's files. Remove them before you
upgrade, with `skilldeck uninstall --all --agent <name>` (once for each
scope), or delete them by hand from the paths the Removed entry lists.

The release check requires the Removed entry. Reviewers check the
deprecation and the notice period for adapters, because a script can't tell
a skilldeck decision from a vendor-forced removal, which is exempt.

### Dropping an agent from a skill

Removing an agent from one skill's `supported-agents`, while skilldeck keeps
supporting the agent, removes the skill for that agent's users. It needs a
minor release before 1.0 and a major one from 1.0. Announce it first with a
`### Deprecated` entry naming the skill and the agent, and wait the same
notice period. The removal then needs a single `### Removed` entry naming
both the skill and the agent (checked).

Installed copies for that agent stay where they are, and the agent keeps
loading them, but skilldeck stops managing them. `status --agent <agent>` no
longer lists the skill, not even as an orphan, and `update` no longer
refreshes it. `skilldeck uninstall <skill> --agent <agent>` still removes it,
so the Removed entry should give that command.

`tests/test_lifecycle.py` pins this behaviour and walks through removing an
agent from one skill and removing an adapter altogether.

## Metadata and file formats

### `meta.yaml`

The loader rejects any `meta.yaml` key it doesn't know, so a skill can't use
a new field until a skilldeck release knows it. Adding a field is therefore a
minor package release. That release updates the loader
(`src/skilldeck/registry.py`), [Authoring skills](authoring-skills.md) and, if
tools should see the field, the catalog, where it is an additive change.
Removing or renaming a field, or tightening a rule so that existing metadata
fails, is breaking for skill authors.

The one lifecycle field is `deprecated`, with `since`, `reason` and an
optional `replacement`. It deliberately has no removal date or version. The
notice period starts when a release publishes the deprecation, and only the
release tag knows that: its date, its files and its CHANGELOG, which the
release check reads. A date written into `meta.yaml` in advance would be a
guess that could disagree with them.

### The catalog

`skilldeck catalog --json` follows the
[compatibility rules in docs/catalog.md](catalog.md#compatibility-rules):
additive changes keep `schema_version` 1, and breaking ones bump it. A bump
needs a CHANGELOG entry marked **Breaking:** that mentions `schema_version`
(checked), so it goes in a minor release before 1.0 and a major one from 1.0.

The catalog can represent every state in a skill's lifecycle:

| State | Catalog entry |
|---|---|
| active | `"deprecated": null` |
| deprecated, with a replacement | `"deprecated": {"since": "1.3.0", "replacement": "new-review", "reason": "..."}` |
| deprecated, with a reason only | `"deprecated": {"since": "1.3.0", "replacement": null, "reason": "..."}` |
| removed | not in `skills`; the CHANGELOG records the removal |

A tool that remembers skills from an earlier catalog should treat a name that
disappears as removed, and look up its replacement in the last catalog that
listed it. `tests/test_lifecycle.py` checks each state against the published
schema.

### Install stamps

Every installed file ends with one stamp line:

```
<!-- skilldeck name=security-review version=0.5.1 hash=<64 hex digits> -->
```

The format has no version marker. It is version 1 by its shape, and
`skilldeck.stamp.parse` reads only that shape. The stamp is how `status`,
`update`, `install` and `uninstall` recognise skilldeck's own unedited files,
so a file whose stamp skilldeck can't read counts as one it didn't write:
`update` skips it, and `install` and `uninstall` refuse it without `--force`.
That already happened once, to the unstamped files of skilldeck 0.3.0 and
earlier.

So a change to the stamp format follows these rules:

1. **Keep reading every format skilldeck has written.** No release drops one.
   Each costs one pattern.
2. **Mark the new format**, for example `<!-- skilldeck stamp=2 name=... -->`,
   so that it can't be mistaken for version 1. A stamp with no marker stays
   version 1.
3. **Let `update` do the migration.** An unedited file with a version 1 stamp
   no longer matches what installing writes, so `status` shows it as stale and
   `update` rewrites it with the new stamp. No migration command and no
   `--force` are needed. An edited file shows as "modified locally" and is
   left alone, as it is today.
4. **Keep `hash=` meaning the same thing**: the SHA-256 of the file above the
   stamp, which the catalog's `rendered_sha256` equals. Changing that would
   also be a breaking catalog change.
5. **Record it** with a `### Changed` entry, and update the adapter contract
   fixtures, since the stamp is part of every expected file. That changes the
   compatibility digest too.

A stamp-format change that follows these rules is a minor release.
Downgrading skilldeck across one isn't supported: the older release reads the
new stamp as no stamp, and needs `install --force` to take the files back.

`tests/test_stamp.py` pins the version 1 format byte for byte.
`test_walkthrough_stamp_format_migration` in `tests/test_lifecycle.py`
simulates a second format and checks that `status` and `update` migrate files
as described here.

### Lockfiles and install state

Today the install state is the stamped files themselves. There is no lockfile
or install database. When [#71](https://github.com/IcebergAI/skilldeck/issues/71)
adds lockfiles, they follow these rules (what a lockfile records is #71's
decision):

- A lockfile carries its own integer `schema_version`, under the catalog's
  additive and breaking rules.
- Like stamps, every lockfile version skilldeck has written stays readable.
- A locked skill, agent or format that has been removed fails clearly,
  before anything is written, with an error that names it and points to the
  CHANGELOG. A deprecated one keeps working through the notice period, with
  the usual warning.

Lockfiles aren't a stable contract until they ship under these rules.

## The command line

These are stable and covered by the package version:

- command and option names, arguments, defaults, and the `--agent` and
  `--scope` values;
- exit codes: 0 for success, 1 when anything failed, 2 for a usage error;
- install locations and file contents, as pinned by the
  [adapter contracts](compatibility.md#contract-tests);
- `skilldeck catalog --json` and `--schema` (see [the catalog](catalog.md));
- `skilldeck provenance --json` (`schema_version` 1), under the same additive
  and breaking rules as the catalog.

Eval run records are not part of the package: they come from the
repository's eval tooling (`evals/run_evals.py`). Their stability follows
their own `schema_version` (`evals/run-record.schema.json`, currently 1)
under the catalog's additive and breaking rules, not the package version.

Human-readable output isn't stable, and can change in any release without
notice. That covers `list`, `status`, `update`, `install`, `uninstall`,
`migrate`, `show`, plain `catalog` and `provenance`, and the wording of every
warning and error. Use `--json` where it exists. `status` has no
machine-readable form yet, so don't parse it.

To remove or rename a command or option, deprecate it first: its help text
says so, and using it prints a warning. Then wait the same notice period. A
renamed option keeps its old spelling as a deprecated alias for that time.

## Security fixes

The urgent path is for a vulnerability in skilldeck's code or releases, or
for a skill whose guidance is itself harmful, such as one telling an agent to
weaken a security control.

It may skip:

- the deprecation and the notice period, so a harmful skill can be changed or
  removed straight away, and so can an adapter;
- batching: the fix is released as soon as it merges, not with the next
  planned release.

It must still:

- go through the normal release: the release checks, the tag and the gated
  release workflow;
- bump versions as SemVer requires, so a removal still needs a minor release
  before 1.0;
- add a `### Security` entry that names what is affected in backticks, gives
  the affected versions, and says what users should do (for example
  `skilldeck update`, or `skilldeck uninstall <name> --agent <agent>`), along
  with the usual Removed or Changed entry;
- for a skill removed this way, start its `### Removed` entry with
  `**Security:**`, for example
  ``- **Security:** `old-review`, which told agents to skip TLS checks.``
  The release check skips the deprecation and notice requirements only for a
  Removed entry with that mark and a Security entry naming the same skill, both
  added by the pull request. A Security entry that merely mentions a skill
  doesn't exempt its removal;
- for a vulnerability in skilldeck itself, publish a GitHub security advisory,
  handling the report as [SECURITY.md](../SECURITY.md) describes.

Fixes ship on the latest release only, with no backports. For a confirmed
high- or critical-severity issue, the maintainers aim for a release within 7
days. That target is their policy choice, like the notice periods, and
[SECURITY.md](../SECURITY.md) states it too.

## Release checks

`scripts/check_lifecycle.py` runs in CI's `lint` job on every pull request as
`--base origin/<target branch>`, comparing the pull request with its target.
It fails unless `CHANGELOG.md` has:

- for a **removed skill**, a `### Removed` entry naming it. The skill must
  also have been deprecated at the base, and if a release tag contains it, a
  release must have published the deprecation at least 90 days earlier (180
  from 1.0): a `vX.Y.Z` tag reachable from the base whose own `meta.yaml`
  marks the skill deprecated and whose own CHANGELOG has a `### Deprecated`
  entry naming it, counted from the later of that section's date and the
  tag's date. The [urgent security path](#security-fixes) skips both
  requirements;
- for a **newly deprecated skill**, a `### Deprecated` entry naming it;
- for an **agent dropped from a skill's `supported-agents`**, a single
  `### Removed` entry naming both the skill and the agent. If the agent's
  adapter is gone altogether, the next rule covers it instead;
- for a **removed adapter** (listed in the base's
  `tests/fixtures/adapter-contracts/contracts.json` but no longer in
  `ALL_ADAPTERS`), a `### Removed` entry of its own that names it and no
  skill;
- for a **new major skill version** (0.x → 1.0.0, 1.x → 2.0.0), a
  `### Changed`, `### Removed` or `### Security` entry naming the skill and
  giving its new version;
- for a **catalog `schema_version` change**, an entry marked **Breaking:**
  that mentions `schema_version`.

Entries count only in sections the pull request adds: `## [Unreleased]`, or
a dated section the base's CHANGELOG doesn't have yet, which is where cutting
a release in the same pull request moves them. A section an earlier release
published doesn't count. Entries must name each skill, agent or adapter in
backticks of its own, like `` `old-review` ``: a name inside a longer code
span, such as a command, doesn't count. Every error says what is missing,
where to add it, and which section of this page applies.

The notice rules need the release tags. CI's `lint` job fetches them; in a
checkout without any `vX.Y.Z` tag reachable from the base, the script prints
`note: no release tags found; notice-period rules skipped` with a reminder to
run `git fetch --tags`, and checks everything else.

With or without `--base`, the script also applies the version-bump rule from
[The package](#the-package) to the newest dated section. On a push to `main`
and under `pytest` it runs that rule on the real CHANGELOG, and
`tests/test_lifecycle.py` tests every rule on small synthetic repositories.
To run it yourself before pushing:

```bash
uv run --locked --extra dev python scripts/check_lifecycle.py --base origin/main
```

These stay with reviewers:

- whether a skill change is major, minor or patch (the check only sees the
  number);
- that a breaking skill change comes with at least a minor package release,
  and, for a 0.x skill's breaking minor bump, a Changed entry;
- that a new feature isn't released in a patch release, and that
  `### Removed` holds only public-surface removals;
- the deprecation and notice period for removing an adapter, a format, a
  command or an option, or dropping an agent from a skill, where a vendor's
  move can make the notice moot;
- whether an entry actually gives the replacement and the commands to run;
- the stamp-format rules;
- whether a fix qualifies for the urgent security path.
