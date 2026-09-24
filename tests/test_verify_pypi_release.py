"""Tests for scripts/verify_pypi_release.py (post-upload PyPI readback, #109)."""

import hashlib
import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "verify_pypi_release.py"
_spec = importlib.util.spec_from_file_location("verify_pypi_release", _SCRIPT)
assert _spec and _spec.loader
pypi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pypi)

VERSION = "1.2.3"
WHEEL = f"skilldeck-{VERSION}-py3-none-any.whl"
SDIST = f"skilldeck-{VERSION}.tar.gz"
BYTES = {WHEEL: b"wheel bytes", SDIST: b"sdist bytes"}
DIGESTS = {name: hashlib.sha256(data).hexdigest() for name, data in BYTES.items()}
# what the build job hands over: the whole bundle, not just PyPI's files
BUNDLE = {**DIGESTS, "SHA256SUMS": "0" * 64, f"skilldeck-{VERSION}.spdx.json": "1" * 64}
API = f"https://pypi.org/pypi/skilldeck/{VERSION}/json"


def _url(name):
    return f"https://files.pythonhosted.org/packages/ab/cd/{name}"


def _listing(names=(WHEEL, SDIST), digests=DIGESTS, urls=None):
    return json.dumps(
        {
            "urls": [
                {
                    "filename": name,
                    "digests": {"sha256": digests[name]},
                    "url": (urls or {}).get(name, _url(name)),
                }
                for name in names
            ]
        }
    ).encode()


class FakePyPI:
    """Serves queued listings for the API URL, then file bytes by URL."""

    def __init__(self, *listings, files=None):
        self.listings = list(listings)
        self.files = {_url(name): data for name, data in (files or BYTES).items()}
        self.requests = []

    def __call__(self, url, limit):
        self.requests.append(url)
        if url == API:
            listing = (
                self.listings.pop(0) if len(self.listings) > 1 else self.listings[0]
            )
            if isinstance(listing, Exception):
                raise listing
            return listing
        return self.files[url]


def _verify(fake, **kwargs):
    kwargs.setdefault("attempts", 3)
    return pypi.verify(
        VERSION, BUNDLE, get=fake, delay=0, sleep=lambda _: None, **kwargs
    )


def _not_found():
    return urllib.error.HTTPError(API, 404, "Not Found", {}, io.BytesIO())


def test_accepts_pypi_serving_the_build_bytes():
    fake = FakePyPI(_listing())
    lines = _verify(fake)
    assert lines == [
        f"{WHEEL}  sha256:{DIGESTS[WHEEL]}",
        f"{SDIST}  sha256:{DIGESTS[SDIST]}",
    ]
    assert set(fake.requests) == {API, _url(WHEEL), _url(SDIST)}


def test_waits_for_the_listing_to_catch_up():
    fake = FakePyPI(_not_found(), _listing(names=(SDIST,)), _listing())
    _verify(fake)
    assert fake.requests.count(API) == 3


def test_gives_up_when_pypi_never_lists_the_release():
    with pytest.raises(pypi.PyPIError, match="gave up after 3 attempts"):
        _verify(FakePyPI(_not_found()))


def test_rejects_bytes_that_differ_from_the_build():
    fake = FakePyPI(_listing(), files={**BYTES, WHEEL: b"swapped"})
    with pytest.raises(pypi.PyPIError, match=f"bytes PyPI serves for {WHEEL}"):
        _verify(fake)


def test_rejects_a_listed_digest_that_differs_from_the_build():
    other = {**DIGESTS, SDIST: "f" * 64}
    with pytest.raises(pypi.PyPIError, match=f"different SHA-256 for {SDIST}"):
        _verify(FakePyPI(_listing(digests=other)))


def test_rejects_extra_files_without_waiting():
    extra = "skilldeck-1.2.3-cp314-cp314-linux_x86_64.whl"
    fake = FakePyPI(
        _listing(names=(WHEEL, SDIST, extra), digests={**DIGESTS, extra: "0" * 64})
    )
    with pytest.raises(pypi.PyPIError, match="unexpected file"):
        _verify(fake)
    assert fake.requests == [API]


def test_rejects_downloads_from_elsewhere():
    fake = FakePyPI(_listing(urls={WHEEL: f"http://files.pythonhosted.org/{WHEEL}"}))
    with pytest.raises(pypi.PyPIError, match="unexpected URL"):
        _verify(fake)
    fake = FakePyPI(_listing(urls={WHEEL: f"https://evil.example/{WHEEL}"}))
    with pytest.raises(pypi.PyPIError, match="unexpected URL"):
        _verify(fake)


def test_requires_one_wheel_and_one_sdist_in_the_build_digests():
    with pytest.raises(pypi.PyPIError, match="exactly one wheel"):
        pypi.verify(VERSION, {SDIST: DIGESTS[SDIST]}, get=FakePyPI(_listing()))


def test_cli_reports_each_verified_file(monkeypatch, capsys):
    fake = FakePyPI(_listing())
    real_verify = pypi.verify
    monkeypatch.setattr(
        pypi, "verify", lambda *args, **kwargs: real_verify(*args, get=fake, **kwargs)
    )
    argv = ["verify_pypi_release.py", "--version", VERSION]
    monkeypatch.setattr(sys, "argv", [*argv, "--expected-digests", json.dumps(BUNDLE)])
    assert pypi.main() == 0
    out = capsys.readouterr().out
    assert f"ok: PyPI serves {WHEEL}  sha256:{DIGESTS[WHEEL]}" in out


def test_cli_rejects_malformed_expected_digests(monkeypatch, capsys):
    argv = ["verify_pypi_release.py", "--version", VERSION]
    monkeypatch.setattr(sys, "argv", [*argv, "--expected-digests", "{}"])
    with pytest.raises(SystemExit) as exc:
        pypi.main()
    assert exc.value.code == 2
    assert "expected digests" in capsys.readouterr().err
