"""Unit tests for hook sentinel helpers: _get_hook_version, _replace_hook_block (T079)."""

from __future__ import annotations

from cerebrofy.hooks.installer import (
    HOOK_SCRIPT_V1,
    HOOK_SCRIPT_V2,
    HOOK_SENTINEL_BEGIN,
    HOOK_SENTINEL_END,
    HOOK_VERSION_MARKER,
    _get_hook_version,
    _replace_hook_block,
)


# ---------------------------------------------------------------------------
# _get_hook_version
# ---------------------------------------------------------------------------


def test_get_hook_version_returns_1_for_v1_block() -> None:
    """Detect version 1 marker in a v1 hook block."""
    content = f"#!/bin/sh\n{HOOK_SCRIPT_V1}"
    assert _get_hook_version(content) == 1


def test_get_hook_version_returns_2_for_v2_block() -> None:
    """Detect version 2 marker in a v2 hook block."""
    content = f"#!/bin/sh\n{HOOK_SCRIPT_V2}"
    assert _get_hook_version(content) == 2


def test_get_hook_version_returns_0_when_no_block() -> None:
    """Return 0 if no sentinel block present."""
    content = "#!/bin/sh\nsome other hook content\n"
    assert _get_hook_version(content) == 0


def test_get_hook_version_returns_0_when_no_version_marker() -> None:
    """Return 0 if sentinel block has no version marker line."""
    content = f"{HOOK_SENTINEL_BEGIN}\ncerebrofy validate\n{HOOK_SENTINEL_END}\n"
    assert _get_hook_version(content) == 0


def test_get_hook_version_ignores_content_outside_block() -> None:
    """Version marker outside sentinel block should not be detected."""
    content = (
        "#!/bin/sh\n"
        f"# {HOOK_VERSION_MARKER} 99\n"  # outside block — ignored
        f"{HOOK_SENTINEL_BEGIN}\n"
        f"{HOOK_VERSION_MARKER} 1\n"
        "cerebrofy validate --hook pre-push\n"
        f"{HOOK_SENTINEL_END}\n"
    )
    assert _get_hook_version(content) == 1


# ---------------------------------------------------------------------------
# _replace_hook_block
# ---------------------------------------------------------------------------


def test_replace_hook_block_replaces_v1_with_v2() -> None:
    """Replacing a v1 block with v2 produces valid v2 content."""
    content = f"#!/bin/sh\n{HOOK_SCRIPT_V1}"
    new_content = _replace_hook_block(content, HOOK_SCRIPT_V2)

    assert HOOK_SENTINEL_BEGIN in new_content
    assert HOOK_SENTINEL_END in new_content
    assert f"{HOOK_VERSION_MARKER} 2" in new_content
    assert f"{HOOK_VERSION_MARKER} 1" not in new_content
    # Shebang preserved
    assert new_content.startswith("#!/bin/sh")


def test_replace_hook_block_appends_when_no_block() -> None:
    """Append new block if no cerebrofy sentinel exists."""
    original = "#!/bin/sh\necho 'existing hook'\n"
    new_content = _replace_hook_block(original, HOOK_SCRIPT_V2)

    assert "existing hook" in new_content
    assert HOOK_SENTINEL_BEGIN in new_content
    assert f"{HOOK_VERSION_MARKER} 2" in new_content


def test_replace_hook_block_preserves_non_cerebrofy_content() -> None:
    """Non-cerebrofy hook content before and after sentinel is preserved."""
    content = (
        "#!/bin/sh\n"
        "echo 'before'\n"
        f"{HOOK_SCRIPT_V1}"
        "echo 'after'\n"
    )
    new_content = _replace_hook_block(content, HOOK_SCRIPT_V2)

    assert "echo 'before'" in new_content
    assert "echo 'after'" in new_content
    assert f"{HOOK_VERSION_MARKER} 2" in new_content


def test_replace_hook_block_exactly_once() -> None:
    """Replacement produces exactly one sentinel block."""
    content = f"#!/bin/sh\n{HOOK_SCRIPT_V1}"
    new_content = _replace_hook_block(content, HOOK_SCRIPT_V2)
    assert new_content.count(HOOK_SENTINEL_BEGIN) == 1
    assert new_content.count(HOOK_SENTINEL_END) == 1
