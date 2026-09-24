"""``skilldeck`` command-line interface."""

from __future__ import annotations

import json
import stat
from collections.abc import Collection
from itertools import groupby
from pathlib import Path

import click

from .adapters import (
    ADAPTERS,
    ALL_ADAPTERS,
    MIGRATIONS,
    Adapter,
    InstallState,
    LegacyAdapter,
)
from .provenance import distribution_provenance, verify_bundled_skills
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
    agents: tuple[str, ...], scope: Scope, everything: Collection[str] = ADAPTERS
) -> tuple[list[Adapter], bool]:
    """Turn ``--agent`` values into the adapters to run, deduped in order.

    ``all`` means every agent in ``everything`` (by default the native
    adapters) that can install at ``scope``; the rest are skipped with a note.
    An agent named explicitly that can't is reported as an error instead, even
    alongside ``all``. So is an agent whose location at ``scope`` can't be
    resolved, such as a relative ``CLAUDE_CONFIG_DIR``. Returns the adapters
    and whether an error was reported.
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
            adapter.check_scope(scope)
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
            click.echo(f"  {skill.name:<{width}}  {skill.description}  [{agents}]")


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
def install(
    names: tuple[str, ...],
    install_all: bool,
    agents: tuple[str, ...],
    scope: str,
    force: bool,
) -> None:
    """Install one or more skills for the chosen agent(s)."""
    scope_enum = Scope(scope)
    skills = _resolve_skills(names, install_all)
    adapters, failed = _resolve_adapters(agents, scope_enum)
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
    if failed:
        raise SystemExit(1)


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
def show(name: str, agent: str | None) -> None:
    """Print a skill's body, or its rendered per-agent output."""
    by_name = {skill.name: skill for skill in _all_skills()}
    if name not in by_name:
        raise SkillError(f"unknown skill: {name}")
    skill = by_name[name]
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
        click.echo(json.dumps(data, indent=2, sort_keys=True))
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


def main() -> None:
    try:
        cli()
    except SkillError as exc:
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    main()
