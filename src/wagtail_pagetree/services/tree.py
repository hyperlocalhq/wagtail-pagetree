"""Tree assembly, status calculation, permissions, and visible_numchild."""

from collections import Counter
from typing import Iterable, Optional, TypedDict


class PageRow(TypedDict, total=False):
    """Subset of Page row fields used for status computation."""

    id: int
    live: bool
    has_unpublished_changes: bool
    alias_of_id: Optional[int]
    translation_key: str
    parent_translation_key: str  # derived, not from DB


# Five statuses, plus an `aligned` flag carried separately.
STATUS_PUBLISHED = "published"
STATUS_CHANGED = "changed"
STATUS_DRAFT = "draft"
STATUS_ALIAS = "alias"
STATUS_EMPTY = "empty"


def get_page_status(
    page_data: Optional[PageRow],
    primary_parent_translation_key: Optional[str],
) -> tuple[str, bool]:
    """Resolve (status, aligned) for one translation row.

    `page_data` is the Page row dict for the translation in this locale, or
    None if no Page exists. `primary_parent_translation_key` is the
    translation_key of the primary-locale parent, used to compute alignment.

    Alignment is True when the translation lives at the structurally
    equivalent position in its own locale tree (parent's translation_key
    matches the primary parent). Empty rows are vacuously aligned.
    """
    if page_data is None:
        return STATUS_EMPTY, True

    if page_data.get("alias_of_id") is not None:
        status = STATUS_ALIAS
    elif page_data.get("live") and page_data.get("has_unpublished_changes"):
        status = STATUS_CHANGED
    elif page_data.get("live"):
        status = STATUS_PUBLISHED
    else:
        status = STATUS_DRAFT

    parent_key = page_data.get("parent_translation_key")
    aligned = (
        parent_key is None
        or primary_parent_translation_key is None
        or parent_key == primary_parent_translation_key
    )
    return status, aligned


PRIMARY_FIELDS = (
    "id",
    "title",
    "slug",
    "path",
    "depth",
    "numchild",
    "live",
    "has_unpublished_changes",
    "show_in_menus",
    "translation_key",
    "content_type_id",
    "alias_of_id",
    "url_path",
)

MATRIX_FIELDS = (
    "id",
    "title",
    "translation_key",
    "locale_id",
    "live",
    "has_unpublished_changes",
    "alias_of_id",
    "path",
    "depth",
    "url_path",
)


def fetch_primary_rows(locale, permitted: set[int]) -> list[dict]:
    """Fetch primary-locale Page rows the user is allowed to see.

    Returns a list of plain dicts ordered by ``path``. Uses ``values()`` for
    ORM-overhead-free access.
    """
    from wagtail.models import Page

    return list(
        Page.objects.filter(locale=locale, id__in=permitted)
        .values(*PRIMARY_FIELDS)
        .order_by("path")
    )


def fetch_translation_matrix(
    translation_keys: set[str],
    primary_locale_id: int,
    permitted: set[int],
) -> list[dict]:
    """Fetch non-primary translations for the given translation_keys.

    Permission filter: translations the user has no rights on are
    excluded. Their absence in the response means ``status="empty"`` for
    that cell — the user cannot distinguish "no translation" from
    "permission denied", which is the intended behavior.
    """
    if not translation_keys:
        return []
    from wagtail.models import Page

    return list(
        Page.objects.filter(
            translation_key__in=translation_keys,
            id__in=permitted,
        )
        .exclude(locale_id=primary_locale_id)
        .values(*MATRIX_FIELDS)
    )


def annotate_parent_translation_keys(rows: list[dict], steplen: int = 4) -> None:
    """Add ``parent_translation_key`` and ``parent_id`` to each row in-place.

    Resolves the parent by ``path``-prefix lookup within the same row set.
    Used to compute alignment downstream and to let the frontend tree-build
    without seeing raw treebeard paths. Rows whose parent is not in the row
    set (root or permission-denied parent) get ``None`` for both fields.
    """
    by_path = {row["path"]: row for row in rows}
    for row in rows:
        parent_path = row["path"][:-steplen]
        parent = by_path.get(parent_path)
        row["parent_translation_key"] = parent["translation_key"] if parent else None
        row["parent_id"] = parent["id"] if parent else None
        row["parent_title"] = parent["title"] if parent else None


def annotate_matrix_alignment(matrix: list[dict], steplen: int = 4) -> None:
    """For each non-primary row, derive ``parent_translation_key`` from its
    own locale's path neighbors within the matrix.

    Because matrix rows are permission-filtered, a translation whose own
    parent is denied gets ``parent_translation_key=None`` and downstream
    ``get_page_status`` treats it as vacuously aligned (we cannot prove
    divergence without seeing the parent's key).
    """
    by_locale_path: dict[tuple[int, str], dict] = {
        (row["locale_id"], row["path"]): row for row in matrix
    }
    for row in matrix:
        parent_path = row["path"][:-steplen]
        parent = by_locale_path.get((row["locale_id"], parent_path))
        row["parent_translation_key"] = parent["translation_key"] if parent else None
        row["parent_title"] = parent["title"] if parent else None


def resolve_parent_translation_keys_via_db(
    rows: list[dict], default_locale_id: Optional[int] = None, steplen: int = 4
) -> None:
    """Set ``parent_translation_key`` on each row from a DB lookup, in-place.

    The in-set annotators (``annotate_parent_translation_keys`` /
    ``annotate_matrix_alignment``) resolve parents only within the rows handed
    to them. That's complete for the full tree but not for the *sparse* search /
    filter match set, where a row's parent is usually absent — leaving
    ``parent_translation_key=None`` so alignment (the diverged signal) can't be
    computed and diverged cells render as aligned.

    Resolve the real parent ``translation_key`` by ``path`` against the DB.
    Rows carry ``locale_id`` (matrix rows) or fall back to ``default_locale_id``
    (primary rows are all in the primary locale). ``parent_id`` is left
    untouched — search/filter rendering keeps it resolved within the match set
    on purpose, so results render as a flat list.
    """
    from wagtail.models import Page

    needed: dict[int, set[str]] = {}
    for row in rows:
        if len(row["path"]) <= steplen:
            row["parent_translation_key"] = None
            continue
        locale_id = row.get("locale_id", default_locale_id)
        needed.setdefault(locale_id, set()).add(row["path"][:-steplen])

    parent_map: dict[tuple, dict] = {}
    for locale_id, paths in needed.items():
        for parent in Page.objects.filter(
            locale_id=locale_id, path__in=paths
        ).values("path", "translation_key", "title"):
            parent_map[(locale_id, parent["path"])] = parent

    for row in rows:
        if len(row["path"]) <= steplen:
            row["parent_title"] = None
            continue
        locale_id = row.get("locale_id", default_locale_id)
        parent = parent_map.get((locale_id, row["path"][:-steplen]))
        row["parent_translation_key"] = parent["translation_key"] if parent else None
        row["parent_title"] = parent["title"] if parent else None


def fetch_orphans(
    primary_locale_id: int,
    primary_translation_keys: set[str],
    editable: set[int],
) -> list[dict]:
    """Translations whose primary-locale counterpart is missing or denied.

    Filtered by the *editable* set, not the broader permitted set.
    Wagtail's ``explorable_instances`` unions in ancestor pages of every
    permitted page so deep editors can navigate down — those ancestors are
    explorable but not editable, and they would leak into "Pages without
    [DE]" if we filtered by ``permitted``.
    """
    from wagtail.models import Page

    qs = (
        Page.objects.filter(id__in=editable)
        .exclude(locale_id=primary_locale_id)
        .exclude(translation_key__in=primary_translation_keys)
    )
    fields = MATRIX_FIELDS + ("slug", "locale__language_code")
    return list(qs.values(*fields))


def visible_numchild(rows: Iterable[dict], steplen: int = 4) -> dict[int, int]:
    """Count direct children per parent row, after permission filtering.

    Treebeard `Page.path` is a fixed-step materialized path (default 4 chars
    per depth level). A row's parent has the path `row['path'][:-steplen]`.
    Bucket by parent path, then map back to parent row IDs.

    Args:
        rows: Iterable of dicts with `id` and `path` keys (the same `values()`
            output that drives the tree).
        steplen: Treebeard path step length. `Page.steplen` is 4 in stock
            Wagtail.

    Returns:
        Mapping of parent row id -> visible child count. Rows without a
        visible parent in the input (root or filtered-out parent) do not
        contribute to any bucket; the map only contains parents that *are*
        visible. Use `result.get(row_id, 0)` at render time.
    """
    rows_list = list(rows)
    path_to_id = {row["path"]: row["id"] for row in rows_list}
    counts: Counter[int] = Counter()
    for row in rows_list:
        parent_path = row["path"][:-steplen]
        parent_id = path_to_id.get(parent_path)
        if parent_id is not None:
            counts[parent_id] += 1
    return dict(counts)
