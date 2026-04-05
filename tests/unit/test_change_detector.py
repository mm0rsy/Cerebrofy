"""Unit tests for cerebrofy.update.change_detector._parse_name_status."""

from cerebrofy.update.change_detector import FileChange, _parse_name_status


def test_modified_file() -> None:
    output = "M\tsrc/foo.py"
    result = _parse_name_status(output)
    assert result == [FileChange(path="src/foo.py", status="M")]


def test_added_file() -> None:
    output = "A\tsrc/new.py"
    result = _parse_name_status(output)
    assert result == [FileChange(path="src/new.py", status="A")]


def test_deleted_file() -> None:
    output = "D\tsrc/old.py"
    result = _parse_name_status(output)
    assert result == [FileChange(path="src/old.py", status="D")]


def test_multiple_files() -> None:
    output = "M\ta.py\nA\tb.py\nD\tc.py"
    result = _parse_name_status(output)
    assert FileChange(path="a.py", status="M") in result
    assert FileChange(path="b.py", status="A") in result
    assert FileChange(path="c.py", status="D") in result


def test_renamed_file() -> None:
    output = "R100\told.py\tnew.py"
    result = _parse_name_status(output)
    assert FileChange(path="old.py", status="D") in result
    assert FileChange(path="new.py", status="A") in result


def test_empty_output() -> None:
    assert _parse_name_status("") == []
    assert _parse_name_status("   ") == []


def test_ls_files_untracked() -> None:
    # git ls-files --others emits just filenames (no tab-separated prefix)
    output = "untracked.py"
    result = _parse_name_status(output)
    assert result == [FileChange(path="untracked.py", status="A")]
