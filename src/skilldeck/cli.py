"""``skilldeck`` command-line interface."""

from __future__ import annotations

import shlex
import stat
from collections.abc import Collection, Iterable
from itertools import groupby
from pathlib import Path

import click

from . import authoring
from .adapters import (
    ADAPTERS,
    ALL_ADAPTERS,
    MIGRATIONS,
    Adapter,
    InstallState,
    LegacyAdapter,
)
from .capabilities import summary as capability_summary
from .catalog import (
    SKILLS_SOURCE_PATH,
    CatalogError,
    build_catalog,
    catalog_schema_text,
    filter_catalog,
)
from .lint import PLACEHOLDER
from .provenance import (
    REPOSITORY_URL,
    canonical_json,
    canonical_skill_digest,
    distribution_provenance,
    load_build_metadata,
    load_content_manifest,
    verify_bundled_skills,
)
from .registry import Skill, SkillError, discover_skills
from .stamp import read as read_stamp
from .targets import Scope

AGENT_CHOICE = click.Choice(sorted(ALL_ADAPTERS))
AGENTS_CHOICE = click.Choice([*sorted(ALL_ADAPTERS), "all"])
MIGRATE_CHOICE = click.Choice([*sorted(MIGRATIONS), "all"])
SCOPE_CHOICE = click.Choice([s.value for s in Scope])

AGENT_OPTION = click.option(
    "--agent",
    "agents",
    required=True,
    multiple=True,
    type=AGENTS_CHOICE,
    help="Target agent; repeat for several, or use 'all' for every agent's "
    "native skills folder (not the legacy formats).",
)
SCOPE_OPTION = click.option(
    "--scope", type=SCOPE_CHOICE, default=Scope.PROJECT.value, show_default=True
)


def _all_skills() -> list[Skill]:
    return discover_skills(known_agents=set(ADAPTERS))


def _resolve_skills(names: tuple[str, ...], select_all: bool) -> list[Skill]:
    if select_all and names:
        raise click.UsageError("give skill name(s) or --all, not both")
    skills = _all_skills()
    if select_all:
        return skills
    if not names:
        raise click.UsageError("specify skill name(s) or use --all")
    by_name = {skill.name: skill for skill in skills}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        raise SkillError(f"unknown skill: {', '.join(unknown)}")
    return [by_name[name] for name in names]


def _resolve_adapters(
    agents: tuple[str, ...],
    scope: Scope,
    everything: Collection[str] = ADAPTERS,
    *,
    installing: bool = False,
) -> tuple[list[Adapter], bool]:
    """Turn ``--agent`` values into the adapters to run, deduped in order.

    ``all`` means every agent in ``everything`` (by default the native
    adapters) that can install at ``scope``; the rest are skipped with a note.
    An agent named explicitly that can't is reported as an error instead, even
    alongside ``all``. So is an agent whose location at ``scope`` can't be
    resolved, such as a relative ``CLAUDE_CONFIG_DIR``. ``installing`` lets
    the error for an unsupported scope suggest another adapter (see
    :meth:`Adapter.check_scope`). Returns the adapters and whether an error
    was reported.
    """
    # dict.fromkeys dedupes, keeping order; a legacy adapter named alongside
    # ``all`` is not in ``everything`` but still runs
    names = [name for name in agents if name != "all"]
    if "all" in agents:
        names = [*sorted(everything), *names]
    names = list(dict.fromkeys(names))
    selected: list[Adapter] = []
    failed = False
    for name in names:
        adapter = ALL_ADAPTERS[name]
        try:
            adapter.check_scope(scope, installing=installing)
        except SkillError as exc:
            if name in agents:  # named explicitly
                click.echo(f"error: {exc}", err=True)
                failed = True
            else:
                click.echo(f"skip {name}: no --scope {scope.value} support", err=True)
            continue
        try:
            adapter.root(scope)
        except SkillError as exc:
            click.echo(f"error: {name}: {exc}", err=True)
            failed = True
            continue
        selected.append(adapter)
    return selected, failed


def _entry_kind(path: Path) -> str:
    """What is at ``path`` (not following a symlink), for messages."""
    try:
        mode = path.lstat().st_mode
    except OSError:
        return "file"  # gone since it was inspected; nothing better to say
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "directory"
    if not stat.S_ISREG(mode):
        return "special file"
    return "file"


def _unmanaged_detail(adapter: Adapter, skill: Skill, scope: Scope) -> str:
    """Explain an UNMANAGED destination and how (or whether) to adopt it.

    ``install --force`` adopts only a regular file; it never replaces a symlink,
    a directory or other special file, so those aren't offered it.
    """
    kind = _entry_kind(adapter.destination(skill, scope))
    if kind != "file":
        return f"{kind}, not managed by skilldeck"
    return "no skilldeck stamp (adopt with: install --force)"


def _migration_sources(agent: str, scope: Scope) -> list[LegacyAdapter]:
    """``agent``'s older formats that have a location at ``scope``, one per
    directory: when two resolve to the same one, the first listed in
    ``MIGRATIONS`` is used.
    """
    sources: list[LegacyAdapter] = []
    roots: set[Path] = set()
    for source in MIGRATIONS.get(agent, ()):
        if scope not in source.scopes:
            continue
        root = source.root(scope)
        if root not in roots:
            roots.add(root)
            sources.append(source)
    return sources


def _old_install(
    source: LegacyAdapter, skill: Skill, scope: Scope
) -> tuple[InstallState, Path] | None:
    """The state and path of ``skill``'s file in ``source``'s format at
    ``scope``; None if nothing there can be an install skilldeck made.

    A stamped file always can. Anything else (no stamp, a symlink, a
    directory) is considered only where skilldeck 0.3.0 and earlier wrote
    unstamped installs (``unstamped_installs``); elsewhere it is the user's.
    """
    if not source.supports(skill):
        return None
    state, _ = source.inspect(skill, scope)
    if state is InstallState.NOT_INSTALLED:
        return None
    if state is InstallState.UNMANAGED and not source.unstamped_installs:
        return None
    return state, source.destination(skill, scope)


def _legacy_hint(adapter: Adapter, skills: list[Skill], scope: Scope) -> str | None:
    """Point at ``migrate`` if ``adapter``'s agent has skills installed in an
    older format at ``scope``; None if it has none.

    Counts the stamped installs at the bundled skills' old-format paths, and
    how many of those have local edits. Where skilldeck 0.3.0 and earlier
    wrote installs without a stamp, regular files there without one are
    counted separately: they may be old installs or the user's own files, so
    the hint asks for a check before ``--force``.
    """
    stamped = modified = unstamped = 0
    roots: list[str] = []
    for source in _migration_sources(adapter.name, scope):
        before = stamped + unstamped
        for skill in skills:
            try:
                found = _old_install(source, skill, scope)
            except SkillError:
                continue  # unreadable; migrate will report it
            if found is None:
                continue
            state, path = found
            if state is InstallState.UNMANAGED:
                # a symlink or directory is not an old install
                if _entry_kind(path) == "file":
                    unstamped += 1
                continue
            stamped += 1
            if state is InstallState.MODIFIED:
                modified += 1
        if stamped + unstamped > before:
            roots.append(str(source.root(scope)))
    if not (stamped or unstamped):
        return None
    found_parts = []
    if stamped:
        found_parts.append(f"{stamped} {adapter.name} skill(s) in an older format")
    if unstamped:
        found_parts.append(
            f"{unstamped} file(s) named like a bundled skill without a skilldeck stamp"
        )
    command = f"skilldeck migrate --agent {adapter.name}"
    if scope is not Scope.PROJECT:
        command += f" --scope {scope.value}"
    hint = (
        f"hint: {' and '.join(found_parts)} in {', '.join(roots)}; convert them "
        f"with: {command}"
    )
    notes = []
    if modified:
        notes.append(f"{modified} locally modified: add --force")
    if unstamped:
        notes.append(
            "skilldeck 0.3.0 and earlier didn't stamp installs, so check the "
            "unstamped file(s) are old installs before adding --force"
        )
    if notes:
        hint += f" ({'; '.join(notes)})"
    return hint


@click.group()
@click.version_option(package_name="skilldeck")
def cli() -> None:
    """Install agent-agnostic skills into your coding assistant."""


@cli.command(name="list")
def list_cmd() -> None:
    """List available skills, grouped by category."""
    skills = _all_skills()
    if not skills:
        click.echo("No skills found.")
        return
    width = max(len(s.name) for s in skills)
    by_category = sorted(skills, key=lambda s: (s.category, s.name))
    for category, group in groupby(by_category, key=lambda s: s.category):
        click.echo(f"\n{category}:")
        for skill in group:
            agents = ", ".join(skill.supported_agents)
            line = f"  {skill.name:<{width}}  {skill.description}  [{agents}]"
            if skill.deprecated is not None:
                note = _deprecation_note(
                    skill.deprecated.since, skill.deprecated.replacement
                )
                line += f"  ({note})"
            click.echo(line)


def _deprecation_note(since: str, replacement: str | None) -> str:
    note = f"deprecated since {since}"
    if replacement:
        note += f"; use {replacement}"
    return note


def _warn_deprecated(skills: Iterable[Skill]) -> None:
    """Warn on stderr about each deprecated skill in ``skills``, once, by name."""
    for skill in sorted(set(skills), key=lambda skill: skill.name):
        if skill.deprecated is None:
            continue
        note = _deprecation_note(skill.deprecated.since, skill.deprecated.replacement)
        click.echo(
            f"warning: {skill.name} is {note} ({skill.deprecated.reason})", err=True
        )


def _built_from() -> str:
    """Where this package's build metadata says it was built from."""
    try:
        build = load_build_metadata()
    except ValueError as exc:
        return f"unknown ({exc})"
    if build["source_ref"] is None:
        return "a development build, with no release tag or commit"
    return f"{build['source_ref']}, commit {build['source_commit']}"


def _digest_status(skill: Skill) -> str:
    """``skill``'s canonical digest, and whether it matches the content
    manifest this package shipped with (a claim of the package itself)."""
    try:
        meta_text = (skill.path / "meta.yaml").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"unavailable (cannot read meta.yaml: {exc})"
    digest = canonical_skill_digest(meta_text, skill.body)
    try:
        records = load_content_manifest()["skills"]
    except ValueError as exc:
        return f"{digest} (unverified: {exc})"
    recorded = {record["name"]: record["canonical_sha256"] for record in records}
    expected = recorded.get(skill.name)
    if expected is None:
        return f"{digest} (NOT in the content manifest shipped in this package)"
    if digest != expected:
        return (
            f"{digest} (does NOT match the content manifest shipped in this "
            f"package: {expected})"
        )
    return f"{digest} (matches the content manifest shipped in this package)"


def _summary_lines(skill: Skill) -> list[str]:
    """What ``skill`` is, where it comes from, and what it declares it may ask
    an agent to do: the preview ``show --summary`` and ``install --dry-run``
    print."""
    deprecated = "no"
    if skill.deprecated is not None:
        note = _deprecation_note(skill.deprecated.since, skill.deprecated.replacement)
        deprecated = f"{note} ({skill.deprecated.reason})"
    lines = [
        f"{skill.name} {skill.version} ({skill.category})",
        f"  {skill.description}",
        f"  source:      {REPOSITORY_URL}, {SKILLS_SOURCE_PATH}/{skill.name}",
        f"  built from:  {_built_from()} (recorded at build)",
        f"  digest:      {_digest_status(skill)}",
        "  verify:      both lines above are the package's own records; "
        "skilldeck provenance --verify re-hashes the installed skills, and "
        "docs/verifying-releases.md checks the package itself",
        f"  deprecated:  {deprecated}",
        "  capabilities (declared for review, not enforced; anything not listed "
        "is not requested):",
    ]
    for label, entries in capability_summary(skill.capabilities):
        lines.append(f"    {label + ':':<13}{entries[0]}")
        lines.extend(f"    {'':<13}{entry}" for entry in entries[1:])
    return lines


def _echo_json(data: object) -> None:
    """Print ``data`` as canonical JSON, as UTF-8 bytes with ``\\n`` newlines.

    ``click.echo`` writes bytes to the binary stream, so the output is the
    same bytes on every platform (a text stream on Windows would turn each
    newline into CRLF).
    """
    click.echo(canonical_json(data).encode("utf-8"), nl=False)


@cli.command()
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit the deterministic, schema-versioned catalog as JSON.",
)
@click.option(
    "--category",
    "categories",
    multiple=True,
    help="Only skills in this category; repeat to allow several.",
)
@click.option(
    "--agent",
    "agents",
    multiple=True,
    type=click.Choice(sorted(ADAPTERS)),
    help="Only skills that support this agent; repeat to require several.",
)
@click.option(
    "--schema",
    is_flag=True,
    help="Print the JSON Schema of the --json output and exit.",
)
def catalog(
    as_json: bool, categories: tuple[str, ...], agents: tuple[str, ...], schema: bool
) -> None:
    """Describe every bundled skill for tools: identity, version, category,
    supported agents, canonical digest, source and deprecation state.

    Each digest is recomputed from the installed skill files and must match
    the content manifest recorded when the package was built, the same check
    as provenance --verify; the command fails if any does not.
    """
    if schema:
        if as_json or categories or agents:
            raise click.UsageError("--schema takes no other options")
        try:
            text = catalog_schema_text()
        except OSError as exc:
            raise click.ClickException(
                f"cannot read the catalog schema: {exc}"
            ) from exc
        click.echo(text if text.endswith("\n") else text + "\n", nl=False)
        return
    try:
        # the full provenance --verify check first: it also catches files the
        # manifest doesn't list, which the skills themselves can't show
        problems = verify_bundled_skills()
        data = None if problems else build_catalog(_all_skills())
    except CatalogError as exc:
        problems, data = exc.problems, None
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if problems:
        for problem in problems:
            click.echo(f"error: {problem}", err=True)
        click.echo(
            "error: the installed skills do not match the content manifest "
            "recorded when this package was built",
            err=True,
        )
        raise SystemExit(1)
    assert data is not None
    known = {skill["category"] for skill in data["skills"]}
    unknown = sorted(set(categories) - known)
    if unknown:
        click.echo(
            f"warning: no skill has category {', '.join(unknown)}; the categories "
            f"are {', '.join(sorted(known))}",
            err=True,
        )
    data = filter_catalog(data, set(categories), set(agents))
    if as_json:
        _echo_json(data)
        return

    if not data["skills"]:
        click.echo("No matching skills.")
        return
    name_width = max(len(skill["name"]) for skill in data["skills"])
    version_width = max(len(skill["version"]) for skill in data["skills"])
    category_width = max(len(skill["category"]) for skill in data["skills"])
    for skill in data["skills"]:
        line = (
            f"{skill['name']:<{name_width}}  {skill['version']:<{version_width}}  "
            f"{skill['category']:<{category_width}}  {skill['canonical_sha256']}"
        )
        deprecated = skill["deprecated"]
        if deprecated is not None:
            note = _deprecation_note(deprecated["since"], deprecated["replacement"])
            line += f"  ({note})"
        click.echo(line)


@cli.command()
@click.argument("names", nargs=-1)
@click.option("--all", "install_all", is_flag=True, help="Install every skill.")
@AGENT_OPTION
@SCOPE_OPTION
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite locally modified or unmanaged destination files.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Write nothing: preview each skill's source, digest and declared "
    "capabilities, and what installing it would do.",
)
def install(
    names: tuple[str, ...],
    install_all: bool,
    agents: tuple[str, ...],
    scope: str,
    force: bool,
    dry_run: bool,
) -> None:
    """Install one or more skills for the chosen agent(s)."""
    scope_enum = Scope(scope)
    skills = _resolve_skills(names, install_all)
    adapters, failed = _resolve_adapters(agents, scope_enum, installing=True)
    if dry_run:
        if not _preview_install(skills, adapters, scope_enum, force) or failed:
            raise SystemExit(1)
        return
    installed: set[Skill] = set()
    for adapter in adapters:
        for skill in skills:
            if not adapter.supports(skill):
                click.echo(
                    f"skip {skill.name}: not supported by {adapter.name}", err=True
                )
                continue
            try:
                dest = adapter.install(skill, scope_enum, force=force)
            except SkillError as exc:
                click.echo(f"error: {exc}", err=True)
                failed = True
                continue
            click.echo(f"installed {skill.name} -> {dest}")
            installed.add(skill)
    _warn_deprecated(installed)
    if failed:
        raise SystemExit(1)


def _preview_install(
    skills: list[Skill], adapters: list[Adapter], scope: Scope, force: bool
) -> bool:
    """Print what ``install`` would do, writing nothing; return whether every
    install would succeed.

    Each skill's summary comes first, then one line per adapter. The checks
    are a real install's (``Adapter.install`` with ``dry_run``), with the
    same errors on stderr, except that instead of creating the destination's
    folder it checks the folder could be created; a failure only writing
    reveals, such as a full disk, still shows up only in a real install.
    """
    ok = True
    for index, skill in enumerate(skills):
        if index:
            click.echo()
        for line in _summary_lines(skill):
            click.echo(line)
        for adapter in adapters:
            if not adapter.supports(skill):
                click.echo(
                    f"skip {skill.name}: not supported by {adapter.name}", err=True
                )
                continue
            try:
                state, found = adapter.inspect(skill, scope)
                dest = adapter.install(skill, scope, force=force, dry_run=True)
            except SkillError as exc:
                click.echo(f"error: {exc}", err=True)
                ok = False
                continue
            action = "would install"
            if state is InstallState.STALE and found is not None:
                action = f"would update ({found.version} -> {skill.version})"
            elif state is InstallState.CURRENT:
                action = "would rewrite (up to date)"
            elif state is InstallState.MODIFIED:
                action = "would overwrite local modifications"
            elif state is InstallState.UNMANAGED:
                action = "would overwrite a file without a skilldeck stamp"
            click.echo(f"  {adapter.name}: {action} -> {dest}")
    click.echo("dry run: nothing was written")
    return ok


@cli.command()
@click.argument("names", nargs=-1)
@click.option("--all", "uninstall_all", is_flag=True, help="Uninstall every skill.")
@AGENT_OPTION
@SCOPE_OPTION
@click.option(
    "--force",
    is_flag=True,
    help="Also delete locally modified or unmanaged files (a symlink is "
    "unlinked; its target is kept).",
)
def uninstall(
    names: tuple[str, ...],
    uninstall_all: bool,
    agents: tuple[str, ...],
    scope: str,
    force: bool,
) -> None:
    """Remove one or more installed skills for the chosen agent(s)."""
    scope_enum = Scope(scope)
    skills = _resolve_skills(names, uninstall_all)
    adapters, failed = _resolve_adapters(agents, scope_enum)
    for adapter in adapters:
        for skill in skills:
            try:
                removed = adapter.uninstall(skill, scope_enum, force=force)
            except SkillError as exc:
                click.echo(f"error: {exc}", err=True)
                failed = True
                continue
            if removed:
                click.echo(f"removed {skill.name} <- {removed}")
            else:
                click.echo(f"not installed for {adapter.name}: {skill.name}", err=True)
    if failed:
        raise SystemExit(1)


@cli.command()
@click.argument("name")
@click.option(
    "--agent",
    type=AGENT_CHOICE,
    default=None,
    help="Preview the rendered output for this agent instead of the raw body.",
)
@click.option(
    "--summary",
    is_flag=True,
    help="Print the skill's source, digest and declared capabilities instead.",
)
def show(name: str, agent: str | None, summary: bool) -> None:
    """Print a skill's body, its rendered per-agent output, or a summary of
    where it comes from and what it may ask an agent to do."""
    if summary and agent is not None:
        raise click.UsageError("give --summary or --agent, not both")
    by_name = {skill.name: skill for skill in _all_skills()}
    if name not in by_name:
        raise SkillError(f"unknown skill: {name}")
    skill = by_name[name]
    if summary:
        for line in _summary_lines(skill):
            click.echo(line)
        return
    if agent is None:
        text = skill.body
    else:
        adapter = ALL_ADAPTERS[agent]
        if not adapter.supports(skill):
            raise SkillError(f"{name} does not support {agent}")
        text = adapter.render(skill)
    click.echo(text if text.endswith("\n") else text + "\n", nl=False)


@cli.command()
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit deterministic machine-readable provenance metadata.",
)
@click.option(
    "--verify",
    is_flag=True,
    help="Re-hash the installed skill files and fail unless every one matches "
    "its recorded canonical digest.",
)
def provenance(as_json: bool, verify: bool) -> None:
    """Show the package source and bundled skill identities.

    Without --verify this reports the identities recorded when the package was
    built; it does not re-read the installed skill files.
    """
    try:
        data = distribution_provenance()
        problems = verify_bundled_skills() if verify else []
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if problems:
        for problem in problems:
            click.echo(f"error: {problem}", err=True)
        click.echo(
            "error: the installed skills do not match the content manifest "
            "recorded when this package was built",
            err=True,
        )
        raise SystemExit(1)
    if as_json:
        _echo_json(data)
        return

    package = data["distribution"]
    click.echo(f"{package['name']} {package['version']}")
    click.echo(f"repository: {package['source_repository']}")
    click.echo(f"source ref: {package['source_ref'] or 'unavailable'}")
    click.echo(f"source commit: {package['source_commit'] or 'unavailable'}")
    click.echo("bundled skills:")
    if not data["skills"]:
        click.echo("  (none)")
    width = max((len(skill["name"]) for skill in data["skills"]), default=0)
    for skill in data["skills"]:
        click.echo(
            f"  {skill['name']:<{width}}  {skill['version']}  "
            f"{skill['canonical_sha256']}"
        )
    if verify:
        click.echo(
            f"verified: {len(data['skills'])} installed skill(s) match their "
            "recorded canonical digests"
        )


@cli.command()
@AGENT_OPTION
@SCOPE_OPTION
def status(agents: tuple[str, ...], scope: str) -> None:
    """Show installed vs bundled skill versions for the chosen agent(s)."""
    scope_enum = Scope(scope)
    skills = _all_skills()
    width = max((len(s.name) for s in skills), default=0)
    adapters, failed = _resolve_adapters(agents, scope_enum)
    multi = len(adapters) > 1
    indent = "  " if multi else ""
    for index, adapter in enumerate(adapters):
        if multi:
            if index:
                click.echo()
            click.echo(f"{adapter.name}:")
        for skill in skills:
            if not adapter.supports(skill):
                continue
            try:
                state, found = adapter.inspect(skill, scope_enum)
            except SkillError as exc:
                click.echo(f"{indent}error: {exc}", err=True)
                failed = True
                continue
            if state is InstallState.NOT_INSTALLED:
                detail = "not installed"
            elif state is InstallState.UNMANAGED:
                detail = _unmanaged_detail(adapter, skill, scope_enum)
            else:
                assert found is not None
                if state is InstallState.MODIFIED:
                    detail = f"{found.version} modified locally"
                elif state is InstallState.STALE:
                    detail = f"{found.version} stale (bundled: {skill.version})"
                else:
                    detail = f"{found.version} up to date"
            click.echo(f"{indent}{skill.name:<{width}}  {detail}")
        # Stamped files this adapter wrote for skills no longer bundled. The
        # install directories are shared with the user's own files, so
        # anything without a readable skilldeck stamp is none of our business.
        known = {adapter.destination(skill, scope_enum) for skill in skills}
        for path in adapter.installed_files(scope_enum):
            if path in known:
                continue
            orphan = read_stamp(path)
            if orphan is None:
                continue
            label = f"{orphan.name} {orphan.version}"
            if orphan.modified:
                label += ", modified locally"
            click.echo(f"{indent}orphan: {path} ({label})")
        hint = _legacy_hint(adapter, skills, scope_enum)
        if hint:
            click.echo(f"{indent}{hint}")
    if failed:
        raise SystemExit(1)


@cli.command()
@AGENT_OPTION
@SCOPE_OPTION
@click.option("--force", is_flag=True, help="Also overwrite locally modified installs.")
def update(agents: tuple[str, ...], scope: str, force: bool) -> None:
    """Refresh installed skills that are stale for the chosen agent(s)."""
    scope_enum = Scope(scope)
    skills = _all_skills()
    adapters, failed = _resolve_adapters(agents, scope_enum)
    multi = len(adapters) > 1
    indent = "  " if multi else ""
    refreshed: set[Skill] = set()
    for index, adapter in enumerate(adapters):
        if multi:
            if index:
                click.echo()
            click.echo(f"{adapter.name}:")
        updated = errors = 0
        for skill in skills:
            if not adapter.supports(skill):
                continue
            try:
                state, found = adapter.inspect(skill, scope_enum)
                if state is InstallState.STALE or (
                    state is InstallState.MODIFIED and force
                ):
                    adapter.install(skill, scope_enum, force=True)
                    old = found.version if found else "?"
                    click.echo(
                        f"{indent}updated {skill.name} ({old} -> {skill.version})"
                    )
                    updated += 1
                    refreshed.add(skill)
                elif state is InstallState.MODIFIED:
                    click.echo(
                        f"{indent}skip {skill.name}: locally modified (use --force)",
                        err=True,
                    )
                elif state is InstallState.UNMANAGED:
                    detail = _unmanaged_detail(adapter, skill, scope_enum)
                    click.echo(f"{indent}skip {skill.name}: {detail}", err=True)
            except SkillError as exc:
                click.echo(f"{indent}error: {exc}", err=True)
                errors += 1
        if errors:
            failed = True
        elif not updated:
            click.echo(f"{indent}nothing to update")
        hint = _legacy_hint(adapter, skills, scope_enum)
        if hint:
            click.echo(f"{indent}{hint}")
    _warn_deprecated(refreshed)
    if failed:
        raise SystemExit(1)


@cli.command()
@click.option(
    "--agent",
    "agents",
    required=True,
    multiple=True,
    type=MIGRATE_CHOICE,
    help="Agent whose older-format installs to migrate; repeat for several, or "
    "use 'all'.",
)
@SCOPE_OPTION
@click.option(
    "--force",
    is_flag=True,
    help="Also migrate old files that are locally modified or have no "
    "skilldeck stamp (the bundled skill replaces them; a symlink is unlinked, "
    "its target kept). A modified or unmanaged file at the new location is "
    "never overwritten.",
)
def migrate(agents: tuple[str, ...], scope: str, force: bool) -> None:
    """Move skills installed in an older format to the native skills folder.

    For each bundled skill installed in the agent's old format (Codex custom
    prompts, Copilot prompt files, Cursor rules, Kiro steering files), install
    the SKILL.md version, then remove the old file. A locally modified
    SKILL.md already in place is kept as it is.
    """
    scope_enum = Scope(scope)
    skills = _all_skills()
    adapters, failed = _resolve_adapters(agents, scope_enum, MIGRATIONS)
    multi = len(adapters) > 1
    indent = "  " if multi else ""
    for index, adapter in enumerate(adapters):
        if multi:
            if index:
                click.echo()
            click.echo(f"{adapter.name}:")
        migrated = skipped = errors = 0
        for source in _migration_sources(adapter.name, scope_enum):
            for skill in skills:
                try:
                    found = _old_install(source, skill, scope_enum)
                    if found is None:
                        continue
                    state, old = found
                    reason = _migrate_blocker(old, state, force)
                    if reason:
                        click.echo(f"{indent}skip {skill.name}: {reason}", err=True)
                        skipped += 1
                        continue
                    kept = _install_native(adapter, skill, scope_enum)
                    source.uninstall(skill, scope_enum, force=force)
                except SkillError as exc:
                    click.echo(f"{indent}error: {exc}", err=True)
                    errors += 1
                    continue
                new = adapter.destination(skill, scope_enum)
                if kept:
                    click.echo(
                        f"{indent}migrated {skill.name}: removed {old}; kept the "
                        f"locally modified {new}"
                    )
                else:
                    click.echo(f"{indent}migrated {skill.name}: {old} -> {new}")
                migrated += 1
        if errors:
            failed = True
        elif not (migrated or skipped):
            click.echo(f"{indent}nothing to migrate")
    if failed:
        raise SystemExit(1)


def _install_native(adapter: Adapter, skill: Skill, scope: Scope) -> bool:
    """Put ``skill`` in ``adapter``'s own folder for ``migrate``; return
    whether a locally modified install already there was kept.

    Unlike ``install --force``, this never overwrites a file with local edits
    or one skilldeck didn't write: ``migrate --force`` is about the old file.
    A modified install of the skill counts as migrated already; anything else
    in the way raises :class:`SkillError`, so the old file is kept.
    """
    state, _ = adapter.inspect(skill, scope)
    if state is InstallState.MODIFIED:
        return True
    if state is InstallState.UNMANAGED:
        dest = adapter.destination(skill, scope)
        kind = _entry_kind(dest)
        if kind == "file":
            what = "has no skilldeck stamp"
            fix = "move it aside, or replace it with install --force"
        else:
            what = f"is a {kind}"
            fix = "move it aside"
        raise SkillError(
            f"cannot migrate {skill.name}: {dest} {what}, and migrate never "
            f"replaces what skilldeck didn't write; {fix}, then re-run "
            "(the old file is kept)"
        )
    if state is not InstallState.CURRENT:
        adapter.install(skill, scope)
    return False


def _migrate_blocker(old: Path, state: InstallState, force: bool) -> str | None:
    """Why the old-format file at ``old`` is left in place; None to migrate it.

    The same rules as ``uninstall``: an unedited, stamped install is moved;
    one with local edits, no stamp, or a symlink needs ``--force``; a
    directory or other special file is never removed.
    """
    kind = _entry_kind(old)
    if kind in ("directory", "special file"):
        return f"{old} is a {kind}, which skilldeck never removes"
    if force:
        return None
    if kind == "symlink":
        return (
            f"{old} is a symlink skilldeck did not create; left in place "
            "(--force migrates it, removing the link but not its target)"
        )
    if state is InstallState.UNMANAGED:
        return (
            f"{old} has no skilldeck stamp (hand-written, from another tool, "
            "or installed by skilldeck 0.3.0 or earlier); left in place "
            "(--force migrates it)"
        )
    if state is InstallState.MODIFIED:
        return (
            f"{old} has local modifications; left in place (--force replaces "
            "it with the bundled skill)"
        )
    return None


_NO_SKILLS_DIR = (
    "not inside a skilldeck checkout, so there is no default skills directory"
)


@cli.command(name="new")
@click.argument("name")
@click.option(
    "--category", required=True, help="The skill's category, e.g. security or review."
)
@click.option(
    "--description",
    default=None,
    help="The one-sentence description (default: a placeholder to replace).",
)
@click.option(
    "--agent",
    "agents",
    multiple=True,
    type=click.Choice(sorted(ADAPTERS)),
    help="An agent the skill supports; repeat for several (default: all).",
)
@click.option(
    "--dir",
    "skills_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="The skills directory to create it in. Default: src/skilldeck/skills "
    "of the skilldeck checkout you are in; required anywhere else.",
)
@click.option(
    "--no-eval-fixture",
    is_flag=True,
    help="In a skilldeck checkout, don't scaffold evals/fixtures/<name>/.",
)
def new(
    name: str,
    category: str,
    description: str | None,
    agents: tuple[str, ...],
    skills_dir: Path | None,
    no_eval_fixture: bool,
) -> None:
    """Scaffold a new skill: meta.yaml and a skill.md skeleton.

    The skeleton has the structure every review skill shares and a
    TODO(author) placeholder wherever domain content goes; it states no
    domain guidance. In a skilldeck checkout it also scaffolds an eval
    fixture. skilldeck never writes into its installed package.
    """
    if skills_dir is None:
        checkout = authoring.find_checkout(Path.cwd())
        if checkout is None:
            raise click.UsageError(
                f"{_NO_SKILLS_DIR}: pass --dir PATH, e.g. your organization's "
                "skills directory (skilldeck never writes into its installed "
                "package)"
            )
        skills_dir = checkout.skills_dir
    try:
        files = authoring.scaffold(
            name,
            category=category,
            description=description,
            agents=list(dict.fromkeys(agents)) or sorted(ADAPTERS),
            skills_dir=skills_dir,
            eval_fixture=not no_eval_fixture,
        )
        authoring.write_files(files)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    except OSError as exc:
        raise click.ClickException(f"cannot create {name}: {exc}") from exc
    for path in files:
        click.echo(f"created {authoring.display_path(path)}")
    in_checkout = authoring.checkout_of(skills_dir) is not None
    if in_checkout:
        check = f"uv run --extra dev skilldeck validate {name}"
    else:
        check = (
            "skilldeck validate --skills-dir "
            f"{shlex.quote(authoring.display_path(skills_dir))} {name}"
        )
    steps = [
        f"Replace every {PLACEHOLDER} placeholder. Ground the checklist in "
        "sources you fetched and cite them as links; the template states no "
        "domain guidance of its own.",
        "Declare in meta.yaml's capabilities anything the skill asks beyond "
        "the read-only review it declares now (another command, an edit, a "
        "credential, an agent tool, a file it creates).",
    ]
    if in_checkout:
        steps += [
            f"Build the eval fixture in evals/fixtures/{name}/ (see "
            "evals/README.md), add its SAMPLE_REPORTS entry in "
            "tests/test_eval_fixtures.py, and add the skill to "
            "docs/finding-output.md.",
            "Regenerate the plugin tree: uv run --extra dev python "
            "scripts/build_plugin.py",
        ]
    steps.append(f"Check it: {check}")
    if in_checkout:
        steps.append(
            "Before you push, run the full check suite in CONTRIBUTING.md "
            "(uv run --extra dev pytest checks what validate cannot, such as "
            "SAMPLE_REPORTS)."
        )
    click.echo("\nNext:")
    for number, step in enumerate(steps, start=1):
        click.echo(f"  {number}. {step}")


def _is_path_argument(target: str) -> bool:
    """A skill directory path, as opposed to a skill name."""
    return target in (".", "..") or "/" in target or "\\" in target


@cli.command()
@click.argument("targets", nargs=-1, metavar="[NAME|PATH]...")
@click.option(
    "--skills-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Where to find skills given by NAME, and every skill when none is "
    "given. Default: src/skilldeck/skills of the skilldeck checkout you are in.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit the deterministic machine-readable report as JSON.",
)
def validate(targets: tuple[str, ...], skills_dir: Path | None, as_json: bool) -> None:
    """Check skills against every authoring rule, offline.

    Checks meta.yaml, the skill.md structure and cited sources, leftover
    placeholders, rendering by every adapter and the catalog entry; in a
    skilldeck checkout also the eval fixture, docs/finding-output.md and the
    generated plugin tree. Each problem names its file, rule and fix. Exits 0
    when clean, 1 on any problem.

    Give skill NAMEs from the skills directory, or PATHs to skill directories
    (anything with a slash, e.g. ./my-skill); with neither, every skill in the
    skills directory is checked.
    """
    if skills_dir is None:
        checkout = authoring.find_checkout(Path.cwd())
        default_dir = checkout.skills_dir if checkout is not None else None
    elif not skills_dir.is_dir():
        raise click.UsageError(f"--skills-dir {skills_dir} is not a directory")
    else:
        default_dir = skills_dir
    no_dir = (
        f"{_NO_SKILLS_DIR}: pass --skills-dir PATH, or skill directory paths "
        "(e.g. ./my-skill)"
    )
    paths: list[Path] = []
    for target in targets:
        if not target.strip():
            raise click.UsageError("an empty skill name or path")
        if _is_path_argument(target):
            path = Path(target)
            if not path.is_dir():
                raise click.UsageError(f"{target} is not a directory")
            paths.append(path)
            continue
        if default_dir is None:
            raise click.UsageError(no_dir)
        path = default_dir / target
        if not path.is_dir():
            hint = (
                f"; to check the directory {target}, pass ./{target}"
                if Path(target).is_dir()
                else ""
            )
            raise click.UsageError(
                f"no skill {target!r} in {authoring.display_path(default_dir)}{hint}"
            )
        paths.append(path)
    if not targets:
        if default_dir is None:
            raise click.UsageError(no_dir)
        paths = authoring.skill_dirs(default_dir)
        if not paths:
            raise click.UsageError(
                f"no skills in {authoring.display_path(default_dir)}"
            )
    report = authoring.validate(paths)
    if as_json:
        _echo_json(report.to_json())
    else:
        for line in authoring.format_report(report):
            click.echo(line)
    if not report.ok:
        raise SystemExit(1)


def main() -> None:
    try:
        cli()
    except SkillError as exc:
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    main()
