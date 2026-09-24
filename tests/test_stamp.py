from skilldeck.stamp import parse, read, stamp


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
    path.write_text(stamp("BODY\n", "demo", "1.0.0"))
    found = read(path)
    assert found is not None and (found.name, found.version) == ("demo", "1.0.0")


def test_read_treats_anything_skilldeck_cannot_have_written_as_unstamped(tmp_path):
    stamped = tmp_path / "stamped.md"
    stamped.write_text(stamp("BODY\n", "demo", "1.0.0"))
    binary = tmp_path / "binary.md"
    binary.write_bytes(b"\xff\xfe\x00")
    link = tmp_path / "link.md"
    link.symlink_to(stamped)
    directory = tmp_path / "dir.md"
    directory.mkdir()
    for path in (binary, link, directory, tmp_path / "missing.md"):
        assert read(path) is None, path
