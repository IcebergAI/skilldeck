#!/usr/bin/env python3
"""Check ``skilldeck provenance --json`` output from an installed distribution.

CI and the release build install the built wheel or sdist into a clean venv and
run ``skilldeck provenance --json`` there. This asserts that the installed
package reports the expected version and exact source identity (tag ref and
full commit), and that its bundled skills are exactly the ones in the committed
content manifest, so the install really is the build under test.

Pure standard library so it runs with any ``python3``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_URL = "https://github.com/IcebergAI/skilldeck"
CONTENT_MANIFEST = ROOT / "src" / "skilldeck" / "_content_manifest.json"


class ProvenanceError(ValueError):
    """The installed distribution does not report the expected identity."""


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"{path} is not valid UTF-8 JSON") from exc


def verify(
    report: object,
    manifest: object,
    *,
    version: str,
    source_ref: str,
    source_commit: str,
) -> None:
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise ProvenanceError("unsupported provenance report")
    expected_distribution = {
        "name": "skilldeck",
        "version": version,
        "source_repository": REPOSITORY_URL,
        "source_ref": source_ref,
        "source_commit": source_commit,
    }
    distribution = report.get("distribution")
    if distribution != expected_distribution:
        raise ProvenanceError(
            f"installed distribution reports {distribution!r}, "
            f"expected {expected_distribution!r}"
        )
    if not isinstance(manifest, dict) or manifest.get("package_version") != version:
        raise ProvenanceError(f"committed content manifest is not for {version}")
    records = manifest.get("skills")
    if not isinstance(records, list) or not records:
        raise ProvenanceError("committed content manifest has no skills")
    expected_skills = [
        {key: record.get(key) for key in ("name", "version", "canonical_sha256")}
        for record in records
        if isinstance(record, dict)
    ]
    if report.get("skills") != expected_skills:
        raise ProvenanceError(
            "installed skills do not match the committed content manifest"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="saved provenance --json output")
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-ref", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--manifest", type=Path, default=CONTENT_MANIFEST)
    args = parser.parse_args()
    try:
        verify(
            _load(args.report),
            _load(args.manifest),
            version=args.expected_version,
            source_ref=args.expected_ref,
            source_commit=args.expected_commit,
        )
    except (OSError, ProvenanceError) as exc:
        parser.error(str(exc))
    print(
        f"ok: installed skilldeck {args.expected_version} reports "
        f"{args.expected_ref} at {args.expected_commit}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
