"""``skilldeck`` command-line interface."""

from __future__ import annotations

from itertools import groupby

import click

from .adapters import ADAPTERS, InstallState
from .registry import Skill, SkillError, discover_skills
from .stamp import parse as parse_stamp
from .targets import Scope

AGENT_CHOICE = click.Choice(sorted(ADAPTERS))
SCOPE_CHOICE = click.Choice([s.value for s in Scope])


def _all_skills() -> list[Skill]:
    return discover_skills(known_agents=set(ADAPTERS))


def _resolve_skills(names: tuple[str, ...], install_all: bool) -> list[Skill]:
    skills = _all_skills()
    if install_all:
        return skills
    if not names:
        raise click.UsageError("specify skill name(s) or use --all")
    by_name = {skill.name: skill for skill in skills}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        raise SkillError(f"unknown skill: {', '.join(unknown)}")
    return [by_name[name] for name in names]


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
@click.option("--agent", required=True, type=AGENT_CHOICE, help="Target agent.")
@click.option(
    "--scope", type=SCOPE_CHOICE, default=Scope.PROJECT.value, show_default=True
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite locally modified or unmanaged destination files.",
)
def install(
    names: tuple[str, ...], install_all: bool, agent: str, scope: str, force: bool
) -> None:
    """Install one or more skills for AGENT."""
    adapter = ADAPTERS[agent]
    scope_enum = Scope(scope)
    failed = False
    for skill in _resolve_skills(names, install_all):
        if not adapter.supports(skill):
            click.echo(f"skip {skill.name}: not supported by {agent}", err=True)
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
@click.option("--agent", required=True, type=AGENT_CHOICE, help="Target agent.")
@click.option(
    "--scope", type=SCOPE_CHOICE, default=Scope.PROJECT.value, show_default=True
)
def uninstall(
    names: tuple[str, ...], uninstall_all: bool, agent: str, scope: str
) -> None:
    """Remove one or more installed skills for AGENT."""
    adapter = ADAPTERS[agent]
    scope_enum = Scope(scope)
    for skill in _resolve_skills(names, uninstall_all):
        removed = adapter.uninstall(skill, scope_enum)
        if removed:
            click.echo(f"removed {skill.name} <- {removed}")
        else:
            click.echo(f"not installed: {skill.name}", err=True)


@cli.command()
@click.option("--agent", required=True, type=AGENT_CHOICE, help="Target agent.")
@click.option(
    "--scope", type=SCOPE_CHOICE, default=Scope.PROJECT.value, show_default=True
)
def status(agent: str, scope: str) -> None:
    """Show installed vs bundled skill versions for AGENT."""
    adapter = ADAPTERS[agent]
    scope_enum = Scope(scope)
    skills = _all_skills()
    width = max(len(s.name) for s in skills)
    for skill in skills:
        if not adapter.supports(skill):
            continue
        state, found = adapter.inspect(skill, scope_enum)
        if state is InstallState.NOT_INSTALLED:
            detail = "not installed"
        elif state is InstallState.UNMANAGED:
            detail = "no skilldeck stamp (adopt with: install --force)"
        else:
            assert found is not None
            if state is InstallState.MODIFIED:
                detail = f"{found.version} modified locally"
            elif state is InstallState.STALE:
                detail = f"{found.version} stale (bundled: {skill.version})"
            else:
                detail = f"{found.version} up to date"
        click.echo(f"{skill.name:<{width}}  {detail}")
    # Files this adapter wrote for skills that are no longer bundled.
    known = {adapter.destination(skill, scope_enum) for skill in skills}
    for path in adapter.installed_files(scope_enum):
        if path in known:
            continue
        found = parse_stamp(path.read_text(encoding="utf-8"))
        label = f"{found.name} {found.version}" if found else "no stamp"
        click.echo(f"orphan: {path} ({label})")


@cli.command()
@click.option("--agent", required=True, type=AGENT_CHOICE, help="Target agent.")
@click.option(
    "--scope", type=SCOPE_CHOICE, default=Scope.PROJECT.value, show_default=True
)
@click.option("--force", is_flag=True, help="Also overwrite locally modified installs.")
def update(agent: str, scope: str, force: bool) -> None:
    """Refresh installed skills that are stale for AGENT."""
    adapter = ADAPTERS[agent]
    scope_enum = Scope(scope)
    updated = 0
    for skill in _all_skills():
        if not adapter.supports(skill):
            continue
        state, found = adapter.inspect(skill, scope_enum)
        if state is InstallState.STALE or (state is InstallState.MODIFIED and force):
            adapter.install(skill, scope_enum, force=True)
            old = found.version if found else "?"
            click.echo(f"updated {skill.name} ({old} -> {skill.version})")
            updated += 1
        elif state is InstallState.MODIFIED:
            click.echo(f"skip {skill.name}: locally modified (use --force)", err=True)
        elif state is InstallState.UNMANAGED:
            click.echo(
                f"skip {skill.name}: no skilldeck stamp (adopt with: install --force)",
                err=True,
            )
    if not updated:
        click.echo("nothing to update")


def main() -> None:
    try:
        cli()
    except SkillError as exc:
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    main()
