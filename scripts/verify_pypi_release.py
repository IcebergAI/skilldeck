#!/usr/bin/env python3
"""Check that PyPI serves exactly the wheel and sdist the release build made.

After the upload, read the release's file list from PyPI's JSON API
(``GET https://pypi.org/pypi/<project>/<version>/json``), download every file
it lists, and compare each file's SHA-256 with the digests the build job
recorded (``write_checksums.py --digests``), which reach this job as a job
output rather than inside the artifact. PyPI's CDN can briefly serve a stale
listing right after an upload, so the listing is re-read until it names the
expected files.

An upload cannot be undone, so a failure here cannot stop what PyPI already
serves; the release workflow runs it before creating the GitHub release so a
mismatch stops the release there and the maintainer can yank the PyPI files.

Pure standard library so it runs with any ``python3``.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeVar

sys.path.insert(0, str(Path(__file__).resolve().parent))

import write_checksums  # noqa: E402

PROJECT = "skilldeck"
API_URL = "https://pypi.org/pypi/{project}/{version}/json"
FILES_HOST = "files.pythonhosted.org"
MAX_LISTING_BYTES = 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
USER_AGENT = "skilldeck-release-verifier (+https://github.com/IcebergAI/skilldeck)"

Fetch = Callable[[str, int], bytes]
T = TypeVar("T")


class PyPIError(ValueError):
    """PyPI does not serve exactly the distributions the build job made."""


class NotYetListed(PyPIError):
    """PyPI does not list every expected file yet (worth retrying)."""


def fetch(url: str, limit: int) -> bytes:
    """GET ``url``, refusing a body larger than ``limit`` bytes."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        body: bytes = response.read(limit + 1)
    if len(body) > limit:
        raise PyPIError(f"response from {url} exceeds {limit} bytes")
    return body


def expected_distributions(digests: Mapping[str, str]) -> dict[str, str]:
    """The wheel and sdist entries of the build job's bundle digests."""
    wheels = [name for name in digests if name.endswith(".whl")]
    sdists = [name for name in digests if name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise PyPIError("build digests must name exactly one wheel and one sdist")
    return {name: digests[name] for name in (*wheels, *sdists)}


def read_listing(
    version: str, expected: Mapping[str, str], get: Fetch
) -> dict[str, dict[str, object]]:
    """PyPI's file entries for ``version``; raise if they aren't ``expected``."""
    url = API_URL.format(project=PROJECT, version=urllib.parse.quote(version))
    try:
        data = json.loads(get(url, MAX_LISTING_BYTES))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NotYetListed(f"PyPI has no {PROJECT} {version} yet") from exc
        raise
    except json.JSONDecodeError as exc:
        raise PyPIError(f"PyPI returned invalid JSON for {url}") from exc
    entries = data.get("urls") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not all(
        isinstance(entry, dict) and isinstance(entry.get("filename"), str)
        for entry in entries
    ):
        raise PyPIError(f"unexpected PyPI JSON API response for {url}")
    files = {str(entry["filename"]): entry for entry in entries}
    if len(files) != len(entries):
        raise PyPIError("PyPI lists a file name more than once")
    unexpected = sorted(set(files) - set(expected))
    if unexpected:
        raise PyPIError(f"PyPI lists unexpected file(s): {', '.join(unexpected)}")
    missing = sorted(set(expected) - set(files))
    if missing:
        raise NotYetListed(f"PyPI does not list {', '.join(missing)} yet")
    return files


def _retrying(
    action: Callable[[], T], attempts: int, delay: float, sleep: Callable[[float], None]
) -> T:
    """Run ``action``, retrying while PyPI lags or the network hiccups."""
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except (NotYetListed, urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts:
                raise PyPIError(f"gave up after {attempts} attempts: {exc}") from exc
            print(f"waiting for PyPI ({exc}); retrying in {delay:g}s", file=sys.stderr)
            sleep(delay)
    raise PyPIError("no attempts made")


def verify(
    version: str,
    digests: Mapping[str, str],
    *,
    get: Fetch = fetch,
    attempts: int = 10,
    delay: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Compare PyPI's files with ``digests``; return one line per verified file."""
    expected = expected_distributions(digests)
    files = _retrying(
        lambda: read_listing(version, expected, get), attempts, delay, sleep
    )
    report = []
    for name, digest in sorted(expected.items()):
        entry = files[name]
        listed = entry.get("digests")
        if not isinstance(listed, dict) or not hmac.compare_digest(
            str(listed.get("sha256", "")), digest
        ):
            raise PyPIError(f"PyPI lists a different SHA-256 for {name}")
        url = urllib.parse.urlsplit(str(entry.get("url", "")))
        if url.scheme != "https" or url.hostname != FILES_HOST:
            raise PyPIError(f"PyPI serves {name} from unexpected URL {url.geturl()}")
        payload = _retrying(
            functools.partial(get, url.geturl(), MAX_FILE_BYTES),
            attempts,
            delay,
            sleep,
        )
        if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), digest):
            raise PyPIError(f"the bytes PyPI serves for {name} differ from the build")
        report.append(f"{name}  sha256:{digest}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="the released version")
    parser.add_argument(
        "--expected-digests",
        required=True,
        metavar="JSON",
        help="the build job's write_checksums.py --digests output",
    )
    parser.add_argument("--attempts", type=int, default=10)
    parser.add_argument("--delay", type=float, default=30.0, help="seconds")
    args = parser.parse_args()
    try:
        digests = write_checksums.parse_digests(args.expected_digests)
        lines = verify(args.version, digests, attempts=args.attempts, delay=args.delay)
    except (OSError, PyPIError, write_checksums.ChecksumError) as exc:
        parser.error(str(exc))
    for line in lines:
        print(f"ok: PyPI serves {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
