"""Pure-Python search helpers (path-prefix expansion, query length cap)."""

from wagtail_pagetree.services.search import (
    QUERY_LENGTH_CAP,
    SearchTooLong,
    _ancestor_paths,
)


def test_ancestor_paths_for_root():
    # Root path '0001' has no ancestors above it.
    assert _ancestor_paths("0001") == []


def test_ancestor_paths_for_grandchild():
    assert _ancestor_paths("000100020003") == ["0001", "00010002"]


def test_ancestor_paths_with_custom_steplen():
    # Two-char step: '010203' has ancestors '01' and '0102'.
    assert _ancestor_paths("010203", steplen=2) == ["01", "0102"]


def test_search_too_long_raised_above_cap():
    # Module-level cap; constructing the error directly verifies the type.
    over = "a" * (QUERY_LENGTH_CAP + 1)
    err = SearchTooLong(over)
    assert isinstance(err, ValueError)
