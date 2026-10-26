"""visible_numchild — pure-Python GROUP BY over tree rows."""

from wagtail_pagetree.services.tree import visible_numchild


def _node(id_: int, path: str) -> dict:
    return {"id": id_, "path": path}


def test_empty_input():
    assert visible_numchild([]) == {}


def test_root_has_no_parent_in_bucket():
    # A single root row has no visible parent and contributes to no bucket.
    rows = [_node(1, "0001")]
    assert visible_numchild(rows) == {}


def test_two_children_under_one_parent():
    rows = [
        _node(1, "0001"),
        _node(2, "00010001"),
        _node(3, "00010002"),
    ]
    assert visible_numchild(rows) == {1: 2}


def test_grandchildren_count_against_their_parent():
    rows = [
        _node(1, "0001"),
        _node(2, "00010001"),
        _node(3, "000100010001"),
        _node(4, "000100010002"),
    ]
    # 1 has 1 child (2); 2 has 2 children (3, 4); 3 and 4 have none.
    assert visible_numchild(rows) == {1: 1, 2: 2}


def test_filtered_out_parent_breaks_chain():
    # Parent of id=2 (path 0001) was permission-filtered. Id=2 has no visible
    # parent in the input, so it contributes to no bucket.
    rows = [
        _node(2, "00010001"),
        _node(3, "00010002"),
    ]
    assert visible_numchild(rows) == {}


def test_filtered_out_child_lowers_parent_count():
    # Parent kept; one child kept, one filtered out.
    rows = [
        _node(1, "0001"),
        _node(2, "00010001"),
    ]
    assert visible_numchild(rows) == {1: 1}


def test_custom_steplen():
    # Demonstrate the steplen knob (treebeard allows non-default values).
    rows = [
        _node(1, "01"),
        _node(2, "0101"),
        _node(3, "0102"),
    ]
    assert visible_numchild(rows, steplen=2) == {1: 2}
