from skilldeck.stamp import Stamp, parse, read, stamp


def test_roundtrip():
    text = stamp("BODY\n", "demo", "1.2.3")
    found = parse(text)
    assert found is not None
    assert found.name == "demo"
    assert found.version == "1.2.3"
    assert not found.modified


def test_missing_trailing_newline_is_normalized():
    assert parse(stamp("BODY", "demo", "1")) == parse(stamp("BODY\n", "demo", "1"))


def test_modified_content_is_detected():
    text = stamp("BODY\n", "demo", "1")
    tampered = text.replace("BODY", "EDITED")
    found = parse(tampered)
    assert found is not None
    assert found.modified


def test_unstamped_text_parses_to_none():
    assert parse("just a document\n") is None
    assert parse("") is None


def test_content_appended_after_the_stamp_counts_as_modified():
    text = stamp("BODY\n", "demo", "1")
    found = parse(text + "postscript\n")
    assert found is not None
    assert found.modified


def test_last_stamp_wins_when_body_contains_a_lookalike():
    # a body that itself quotes a stamp line (e.g. docs about skilldeck) must
    # not shadow the real stamp appended at install time
    body = (
        "the installer appends e.g.\n<!-- skilldeck name=x version=9 hash="
        + ("0" * 64)
        + " -->\nto each file\n"
    )
    found = parse(stamp(body, "demo", "1.0.0"))
    assert found is not None
    assert found.name == "demo"
    assert found.version == "1.0.0"
    assert not found.modified


def test_read_returns_the_stamp_of_a_regular_file(tmp_path):
    path = tmp_path / "skill.md"
    path.write_text(stamp("BODY\n", "demo", "1.0.0"), encoding="utf-8")
    found = read(path)
    assert found is not None and (found.name, found.version) == ("demo", "1.0.0")


def test_read_treats_anything_skilldeck_cannot_have_written_as_unstamped(
    tmp_path, symlink
):
    stamped = tmp_path / "stamped.md"
    stamped.write_text(stamp("BODY\n", "demo", "1.0.0"), encoding="utf-8")
    binary = tmp_path / "binary.md"
    binary.write_bytes(b"\xff\xfe\x00")
    link = tmp_path / "link.md"
    symlink(link, stamped)
    directory = tmp_path / "dir.md"
    directory.mkdir()
    for path in (binary, link, directory, tmp_path / "missing.md"):
        assert read(path) is None, path


# The stamp format every skilldeck release so far has written. It carries no
# format marker, so a later format must be told apart by its shape, and
# docs/lifecycle.md#install-stamps promises the parser keeps reading this one.
# Spelled out byte for byte so a change to it cannot go unnoticed.
V1_STAMPED = (
    "BODY\n<!-- skilldeck name=demo version=1.2.3 "
    "hash=578fe4610847d4812493928762cea185a366979343fc84bf79e6c0564a05c0de -->\n"
)


def test_the_current_stamp_format_is_pinned():
    assert stamp("BODY\n", "demo", "1.2.3") == V1_STAMPED
    assert parse(V1_STAMPED) == Stamp(name="demo", version="1.2.3", modified=False)


def test_a_stamp_in_an_unknown_future_format_reads_as_unstamped():
    # what this version does with a file a newer skilldeck stamped in another
    # format (see docs/lifecycle.md#install-stamps): it is not a skilldeck
    # file here, so install, update and uninstall leave it alone without --force
    future = V1_STAMPED.replace("skilldeck name=", "skilldeck stamp=2 name=")
    assert parse(future) is None
