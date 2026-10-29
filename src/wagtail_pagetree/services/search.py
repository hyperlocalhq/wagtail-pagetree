"""Search with permission-pre-filter and ancestor expansion."""

from typing import Optional

from .tree import (
    PRIMARY_FIELDS,
    STATUS_CHANGED,
    STATUS_EMPTY,
    STATUS_PUBLISHED,
    annotate_matrix_alignment,
    annotate_parent_translation_keys,
    fetch_primary_rows,
    fetch_translation_matrix,
    get_page_status,
)
from .translations import outdated_pairs

QUERY_LENGTH_CAP = 200
ANCESTOR_EXPANSION_CAP = 200

# Statuses the locale×status tree filter accepts: the five base statuses plus
# the two orthogonal flags (a translation can be e.g. published *and* outdated).
BASE_STATUSES = (
    "published",
    "changed",
    "draft",
    "alias",
    "empty",
)
FLAG_STATUSES = (
    "outdated",  # source changed since last sync (published/changed cells)
    "diverged",  # translation lives at a different tree position
)
FILTER_STATUSES = frozenset(BASE_STATUSES + FLAG_STATUSES)


class SearchTooLong(ValueError):
    """Raised when a `?search=` query exceeds QUERY_LENGTH_CAP characters."""


class SearchTooBroad(ValueError):
    """Raised when ancestor expansion would exceed ANCESTOR_EXPANSION_CAP."""


def _ancestor_paths(path: str, steplen: int = 4) -> list[str]:
    """Return all ancestor path prefixes of `path`, longest to shortest."""
    return [path[: i * steplen] for i in range(1, len(path) // steplen)]


def _expansion(matches: list[dict], steplen: int = 4) -> list[str]:
    """Sorted, de-duplicated ancestor paths of every match row."""
    expansion: set[str] = set()
    for row in matches:
        expansion.update(_ancestor_paths(row["path"], steplen))
    return sorted(expansion)


def search_primary(
    locale,
    permitted: set[int],
    query: str,
    steplen: int = 4,
    page_type_id: Optional[int] = None,
) -> tuple[list[dict], list[str]]:
    """Run the primary-locale title search.

    Returns ``(match_rows, ancestor_paths_to_expand)``. The ancestor list
    drives client-side auto-expand. ``page_type_id`` (a content type id)
    narrows the matches to one page type.

    Raises:
        SearchTooLong: query exceeds 200 chars (DoS guard).
        SearchTooBroad: total ancestor expansion exceeds 200 nodes.
    """
    if len(query) > QUERY_LENGTH_CAP:
        raise SearchTooLong(query[:50] + "...")

    from wagtail.models import Page

    qs = Page.objects.filter(
        locale=locale,
        id__in=permitted,
        depth__gt=1,
        title__icontains=query,
    )
    if page_type_id is not None:
        qs = qs.filter(content_type_id=page_type_id)
    matches = list(qs.values(*PRIMARY_FIELDS).order_by("path"))

    expansion: set[str] = set()
    for row in matches:
        for prefix in _ancestor_paths(row["path"], steplen):
            expansion.add(prefix)
        if len(expansion) > ANCESTOR_EXPANSION_CAP:
            raise SearchTooBroad(
                f"{len(expansion)} ancestors > {ANCESTOR_EXPANSION_CAP}"
            )

    return matches, sorted(expansion)


def _cell_matches(
    requested: str,
    cell_status: str,
    aligned: bool,
    translation_key,
    target_locale_id: int,
    outdated: set,
) -> bool:
    """Does this target-locale cell satisfy the requested filter status?"""
    if requested == "diverged":
        # Only meaningful for an existing translation that sits at a divergent
        # tree position. Empty cells are vacuously aligned, never "diverged".
        return cell_status != STATUS_EMPTY and not aligned
    if requested == "outdated":
        # Matches the badge semantics: stale, and only on live content.
        return (translation_key, target_locale_id) in outdated and cell_status in (
            STATUS_PUBLISHED,
            STATUS_CHANGED,
        )
    return cell_status == requested


def filter_primary(
    primary_locale,
    target_locale,
    status: str,
    permitted: set[int],
    steplen: int = 4,
    page_type_id: Optional[int] = None,
) -> tuple[list[dict], list[str]]:
    """Primary rows whose ``target_locale`` cell matches ``status``.

    Generalises the old ``outdated`` filter into a locale×status facet:
    ``status`` is one of ``FILTER_STATUSES``. Mirrors ``search_primary``'s
    ``(match_rows, ancestor_paths)`` contract so the filter reuses the whole
    search render path (flat match list + client-side ancestor auto-expand).

    The match set is a controlled query (bounded by visible pages), so there's
    no DoS surface and no ``TooBroad`` guard. Returns empty results when the
    requested signal can't exist (e.g. ``outdated`` without wagtail-localize).
    ``page_type_id`` narrows the matches to one page type; the full primary set
    is still fetched so parent-alignment (``diverged``) stays correct.
    """
    primary = fetch_primary_rows(primary_locale, permitted)
    annotate_parent_translation_keys(primary, steplen)
    keys = {row["translation_key"] for row in primary}

    same_locale = target_locale.id == primary_locale.id
    if same_locale:
        matrix_index: dict[tuple, dict] = {}
    else:
        matrix = fetch_translation_matrix(keys, primary_locale.id, permitted)
        annotate_matrix_alignment(matrix, steplen)
        matrix_index = {
            (row["translation_key"], row["locale_id"]): row for row in matrix
        }

    outdated = outdated_pairs(keys) if status == "outdated" else set()

    matches: list[dict] = []
    for row in primary:
        if page_type_id is not None and row["content_type_id"] != page_type_id:
            continue
        translation_key = row["translation_key"]
        parent_key = row.get("parent_translation_key")
        if same_locale:
            cell_row = row  # the primary row IS its own translation
        else:
            cell_row = matrix_index.get((translation_key, target_locale.id))
        cell_status, aligned = get_page_status(cell_row, parent_key)
        if _cell_matches(
            status, cell_status, aligned, translation_key, target_locale.id, outdated
        ):
            matches.append(row)

    return matches, _expansion(matches, steplen)


def filter_page_type(
    locale,
    permitted: set[int],
    page_type_id: int,
    steplen: int = 4,
) -> tuple[list[dict], list[str]]:
    """Primary rows of one page type (``content_type_id``), nothing else.

    Same ``(match_rows, ancestor_paths)`` contract as ``search_primary``. Like
    ``filter_primary`` the match set is bounded by visible pages, so there's
    no ``TooBroad`` guard.
    """
    from wagtail.models import Page

    matches = list(
        Page.objects.filter(
            locale=locale,
            id__in=permitted,
            depth__gt=1,
            content_type_id=page_type_id,
        )
        .values(*PRIMARY_FIELDS)
        .order_by("path")
    )
    return matches, _expansion(matches, steplen)
