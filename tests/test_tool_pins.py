"""The CLI tools CI runs are pinned where Dependabot can see them (#110).

Workflows install zizmor and pypi-attestations with
``uvx -c .github/tools/requirements.txt``; the Dependabot pip ecosystem watches
that file. An inline ``tool==x.y.z`` in a workflow would be invisible to it, and
the copy of the pypi-attestations command in docs/verifying-releases.md must
follow the pin when Dependabot bumps it.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / ".github" / "tools" / "requirements.txt"
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
PINNED_TOOLS = ("pypi-attestations", "zizmor")


def _pins():
    pins = {}
    for line in TOOLS.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, _, version = line.partition("==")
            assert version, f"{TOOLS.name}: {line!r} must be an exact == pin"
            pins[name] = version
    return pins


def test_every_ci_tool_is_pinned_in_the_tools_file():
    assert set(_pins()) == set(PINNED_TOOLS)


def test_workflows_use_the_tools_file_and_no_inline_pins():
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        for tool in PINNED_TOOLS:
            assert not re.search(rf"\b{re.escape(tool)}==", text), (
                f"{workflow.name} pins {tool} inline; pin it in "
                ".github/tools/requirements.txt and run it with "
                "`uvx -c .github/tools/requirements.txt`"
            )
            for line in text.splitlines():
                if re.search(rf"\buvx\b.*\b{re.escape(tool)}\b", line):
                    assert "-c .github/tools/requirements.txt" in line, line
        # sbom-action pins its own Syft release; an explicit syft-version here
        # would be a pin Dependabot cannot update
        assert "syft-version" not in text, workflow.name


def test_dependabot_watches_the_tools_file():
    config = yaml.safe_load(
        (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    )
    watched = {
        (entry["package-ecosystem"], entry["directory"]) for entry in config["updates"]
    }
    assert ("pip", "/.github/tools") in watched


def test_verification_docs_follow_the_pypi_attestations_pin():
    docs = (ROOT / "docs" / "verifying-releases.md").read_text(encoding="utf-8")
    version = _pins()["pypi-attestations"]
    documented = re.findall(r"pypi-attestations==([\w.]+)", docs)
    assert documented, "docs/verifying-releases.md no longer pins pypi-attestations"
    assert set(documented) == {version}, (
        "docs/verifying-releases.md pins pypi-attestations "
        f"{sorted(set(documented))}, but .github/tools/requirements.txt pins "
        f"{version}; update the docs"
    )
