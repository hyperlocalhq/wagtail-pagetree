"""Branch coverage for get_page_status — status semantics."""

from wagtail_pagetree.services.tree import (
    STATUS_ALIAS,
    STATUS_CHANGED,
    STATUS_DRAFT,
    STATUS_EMPTY,
    STATUS_PUBLISHED,
    get_page_status,
)


PRIMARY_PARENT = "00000000-0000-0000-0000-000000000001"
SAME_PARENT = PRIMARY_PARENT
OTHER_PARENT = "00000000-0000-0000-0000-000000000002"


def _row(**overrides):
    base = {
        "id": 1,
        "live": True,
        "has_unpublished_changes": False,
        "alias_of_id": None,
        "translation_key": "tk-1",
        "parent_translation_key": SAME_PARENT,
    }
    base.update(overrides)
    return base


def test_empty_when_no_translation():
    status, aligned = get_page_status(None, PRIMARY_PARENT)
    assert status == STATUS_EMPTY
    assert aligned is True  # vacuously aligned


def test_published_when_live_and_unchanged():
    status, aligned = get_page_status(
        _row(live=True, has_unpublished_changes=False), PRIMARY_PARENT
    )
    assert status == STATUS_PUBLISHED
    assert aligned is True


def test_changed_when_live_with_unpublished_changes():
    status, _ = get_page_status(
        _row(live=True, has_unpublished_changes=True), PRIMARY_PARENT
    )
    assert status == STATUS_CHANGED


def test_draft_when_not_live():
    status, _ = get_page_status(
        _row(live=False, has_unpublished_changes=False), PRIMARY_PARENT
    )
    assert status == STATUS_DRAFT


def test_draft_when_not_live_and_changed():
    # Drafts can be in any has_unpublished_changes state; not_live wins.
    status, _ = get_page_status(
        _row(live=False, has_unpublished_changes=True), PRIMARY_PARENT
    )
    assert status == STATUS_DRAFT


def test_alias_overrides_published():
    status, _ = get_page_status(_row(live=True, alias_of_id=42), PRIMARY_PARENT)
    assert status == STATUS_ALIAS


def test_alias_overrides_draft():
    status, _ = get_page_status(_row(live=False, alias_of_id=42), PRIMARY_PARENT)
    assert status == STATUS_ALIAS


def test_aligned_when_parent_keys_match():
    _, aligned = get_page_status(
        _row(parent_translation_key=SAME_PARENT), PRIMARY_PARENT
    )
    assert aligned is True


def test_diverged_when_parent_keys_differ():
    _, aligned = get_page_status(
        _row(parent_translation_key=OTHER_PARENT), PRIMARY_PARENT
    )
    assert aligned is False


def test_aligned_when_no_primary_parent_known():
    # Root nodes have no parent — alignment is vacuously true.
    _, aligned = get_page_status(_row(parent_translation_key=OTHER_PARENT), None)
    assert aligned is True


def test_aligned_when_translation_parent_key_missing():
    row = _row()
    del row["parent_translation_key"]
    _, aligned = get_page_status(row, PRIMARY_PARENT)
    assert aligned is True
