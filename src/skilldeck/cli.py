"""``skilldeck`` command-line interface."""

from __future__ import annotations

from itertools import groupby
from typing import List, Tuple

import click

from .adapters import ADAPTERS
from .registry import Skill, SkillError, discover_skills
from .targets import Scope

AGENT_CHOICE = click.Choice(sorted(ADAPTERS))
SCOPE_CHOICE = click.Choice([s.value for s in Scope])


def _all_skills() -> List[Skill]:
    return discover_skills(known_agents=set(ADAPTERS))


def _resolve_skills(names: Tuple[str, ...], install_all: bool) -> List[Skill]:
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
@click.option("--scope", type=SCOPE_CHOICE, default=Scope.PROJECT.value, show_default=True)
def install(names: Tuple[str, ...], install_all: bool, agent: str, scope: str) -> None:
    """Install one or more skills for AGENT."""
    adapter = ADAPTERS[agent]
    scope_enum = Scope(scope)
    for skill in _resolve_skills(names, install_all):
        if not adapter.supports(skill):
            click.echo(f"skip {skill.name}: not supported by {agent}", err=True)
            continue
        dest = adapter.install(skill, scope_enum)
        click.echo(f"installed {skill.name} -> {dest}")


@cli.command()
@click.argument("names", nargs=-1)
@click.option("--all", "uninstall_all", is_flag=True, help="Uninstall every skill.")
@click.option("--agent", required=True, type=AGENT_CHOICE, help="Target agent.")
@click.option("--scope", type=SCOPE_CHOICE, default=Scope.PROJECT.value, show_default=True)
def uninstall(names: Tuple[str, ...], uninstall_all: bool, agent: str, scope: str) -> None:
    """Remove one or more installed skills for AGENT."""
    adapter = ADAPTERS[agent]
    scope_enum = Scope(scope)
    for skill in _resolve_skills(names, uninstall_all):
        removed = adapter.uninstall(skill, scope_enum)
        if removed:
            click.echo(f"removed {skill.name} <- {removed}")
        else:
            click.echo(f"not installed: {skill.name}", err=True)


def main() -> None:
    try:
        cli()
    except SkillError as exc:
        raise SystemExit(f"error: {exc}")


if __name__ == "__main__":
    main()
