"""Plain dict builders for the JSON API response.

Strict allowlist serialization — these functions never accept arbitrary
``Page`` instances or call ``page.specific.*``. Inputs must be the dicts
returned by ``services.tree.fetch_*`` helpers.
"""

from collections import defaultdict
from typing import Iterable, Optional
from urllib.parse import urlencode

from django.contrib.contenttypes.models import ContentType
from django.urls import NoReverseMatch, reverse
from django.utils import translation

from .translations import outdated_pairs, sync_source_ids
from .tree import (
    STATUS_CHANGED,
    STATUS_PUBLISHED,
    annotate_matrix_alignment,
    annotate_parent_translation_keys,
    fetch_orphans,
    fetch_primary_rows,
    fetch_translation_matrix,
    get_page_status,
    resolve_parent_translation_keys_via_db,
    visible_numchild,
)


def _edit_url(page_id: int) -> str:
    return reverse("wagtailadmin_pages:edit", args=[page_id])


def _pagetree_index_url() -> str:
    """Where to come back to after a delete / copy / add-subpage action.

    Wagtail's create / copy / delete views all honour ``?next=<url>`` via
    ``get_valid_next_url_from_request`` and redirect there on success
    instead of bouncing back to the page explorer.
    """
    return reverse("pagetree:index")


def _with_next(url: str) -> str:
    return f"{url}?{urlencode({'next': _pagetree_index_url()})}"


def _add_child_url(parent_id: int) -> str:
    """Wagtail's add-subpage picker (chooses the page type to add)."""
    return _with_next(reverse("wagtailadmin_pages:add_subpage", args=[parent_id]))


def _copy_url(page_id: int) -> str:
    return _with_next(reverse("wagtailadmin_pages:copy", args=[page_id]))


def _delete_url(page_id: int) -> str:
    return _with_next(reverse("wagtailadmin_pages:delete", args=[page_id]))


def _unpublish_url(page_id: int) -> str:
    return _with_next(reverse("wagtailadmin_pages:unpublish", args=[page_id]))


def _convert_alias_url(page_id: int) -> str:
    return _with_next(reverse("wagtailadmin_pages:convert_alias", args=[page_id]))


def _localize_url(viewname: str, arg) -> Optional[str]:
    """Reverse a wagtail-localize admin URL, or None if it can't be resolved.

    Returns None when wagtail-localize isn't installed (its URLs aren't
    registered → ``NoReverseMatch``), so the caller simply omits the link.
    """
    try:
        return _with_next(reverse(viewname, args=[arg]))
    except NoReverseMatch:
        return None


def _translatable_keys(
    primary_rows: list[dict],
    matrix: list[dict],
    *,
    primary_locale_id: int,
    all_locale_ids: set[int],
) -> set:
    """Translation keys that still have at least one locale to translate into.

    Mirrors wagtail-localize's "Translate this page" applicability: a locale
    counts as covered only when it has a *non-alias* page (an alias is an
    untranslated mirror). A key is translatable when some configured locale has
    no such page yet.
    """
    covered: dict = defaultdict(set)
    for row in primary_rows:
        covered[row["translation_key"]].add(primary_locale_id)
    for mrow in matrix:
        if mrow.get("alias_of_id") is None:
            covered[mrow["translation_key"]].add(mrow["locale_id"])
    return {
        row["translation_key"]
        for row in primary_rows
        if all_locale_ids - covered[row["translation_key"]]
    }


def _localize_source_actions(
    primary_rows, matrix, primary_locale, all_locales, can_submit_translation
):
    """Compute the (sync_ids, translatable_keys) for the primary-cell links.

    Returns empty containers when the user lacks the
    ``wagtail_localize.submit_translation`` permission (mirrors the gate on
    wagtail-localize's own listing buttons), so the links never render for
    users who couldn't use them.
    """
    if not can_submit_translation:
        return {}, frozenset()
    keys = {row["translation_key"] for row in primary_rows}
    sync_ids = sync_source_ids(keys, primary_locale.id)
    translatable_keys = frozenset(
        _translatable_keys(
            primary_rows,
            matrix,
            primary_locale_id=primary_locale.id,
            all_locale_ids={loc.id for loc in all_locales},
        )
    )
    return sync_ids, translatable_keys


def _site_root_paths_cache():
    """Resolve the site root paths once per call (Wagtail caches internally)."""
    from wagtail.models import Site

    return Site.get_site_root_paths()


def _live_url(url_path: str, site_roots) -> Optional[str]:
    """Convert Wagtail's internal `url_path` into a relative frontend URL.

    Returns None when the page sits outside any known site root (rare —
    happens for pages above any Site.root_page) or when ``wagtail_serve``
    can't be reversed. Otherwise returns the path the public frontend
    serves the page at, including the language prefix when Wagtail i18n
    is enabled (e.g. "/de/about/" rather than "/about/").

    Mirrors Wagtail's own ``Page.get_url_parts`` so the i18n prefix obeys
    the project's URL conf (``i18n_patterns`` / ``prefix_default_language``)
    instead of being assembled by hand. ``SiteRootPath.language_code``
    selects which prefix to activate when reversing.
    """
    if not url_path:
        return None
    for root in site_roots:
        if url_path.startswith(root.root_path):
            tail = url_path[len(root.root_path) :]
            language_code = getattr(root, "language_code", None)
            try:
                if language_code:
                    with translation.override(language_code):
                        return reverse("wagtail_serve", args=(tail,))
                return reverse("wagtail_serve", args=(tail,))
            except NoReverseMatch:
                return None
    return None


def _resolve_page_type_names(content_type_ids) -> dict[int, str]:
    """Resolve content_type_id → human-readable model verbose_name.

    Batched once per payload. ``ContentType.objects.get_for_id`` is cached
    by Django; ``model_class()`` resolves to the Page subclass and we read
    its Meta.verbose_name. Falls back to the bare model name if the class
    can't be resolved (shouldn't happen for live pages).
    """
    out: dict[int, str] = {}
    for cid in {c for c in content_type_ids if c is not None}:
        ct = ContentType.objects.get_for_id(cid)
        cls = ct.model_class()
        if cls is not None:
            out[cid] = str(cls._meta.verbose_name)
        else:
            out[cid] = ct.model
    return out


def _page_type_options(nodes: list[dict]) -> list[dict]:
    """Page-type filter choices: the types of the tree's non-placeholder nodes.

    Placeholder nodes carry no ``page_type_id``, so types that only occur
    on navigation-only ancestors are never offered. Sorted by display name.
    """
    names = {
        node["page_type_id"]: node.get("page_type") or ""
        for node in nodes
        if "page_type_id" in node
    }
    return [
        {"id": type_id, "name": name}
        for type_id, name in sorted(names.items(), key=lambda item: item[1].lower())
    ]


def _locale_summary(locales) -> list[dict]:
    return [
        {"id": loc.id, "code": loc.language_code, "name": loc.get_display_name()}
        for loc in locales
    ]


def _translation_cell(
    matrix_row: Optional[dict],
    *,
    primary_parent_translation_key: Optional[str],
    primary_parent_title: Optional[str] = None,
    site_roots=None,
    outdated: bool = False,
) -> dict:
    """Build one cell of the translation matrix.

    Redaction: when ``matrix_row`` is None the cell is ``status="empty"`` with no
    page_id and no action URLs. The user cannot distinguish "no translation"
    from "permission denied" — by design.

    For non-empty cells, exposes the per-status action URLs the dot-menu
    needs (Edit / View live / Copy / Delete / Unpublish / Convert alias).

    ``outdated``: the source page changed since this translation was
    last synced (from wagtail-localize). Orthogonal to ``status`` — only
    meaningful for live content, so it's surfaced for ``published``/``changed``
    cells and ignored for alias/draft/empty (which can't be "stale").

    ``outdated`` is a *signal only* — no dedicated action URL. wagtail-localize
    renders its segment editor on the translation's own edit view, so
    ``edit_url`` already is the "update the translation" affordance; a second
    menu entry pointing at the same URL only looked like a distinct action.
    Drift caused by unpublished source edits has no remedy on this cell at all
    (the source must be published/synced), which the dot tooltip says instead.
    """
    status, aligned = get_page_status(matrix_row, primary_parent_translation_key)
    cell: dict = {"status": status, "aligned": aligned}
    # Diverged: this translation sits under a structurally different parent than
    # the primary. Surface both titles so the dot tooltip can explain *where*
    # it diverged ("under X, expected under Y") without a DB dig.
    if matrix_row is not None and not aligned:
        cell["diverged_from"] = matrix_row.get("parent_title")
        cell["diverged_expected"] = primary_parent_title
    if matrix_row is not None:
        page_id = matrix_row["id"]
        is_alias = matrix_row.get("alias_of_id") is not None
        is_live = bool(matrix_row.get("live"))
        cell["is_alias"] = is_alias
        cell["page_id"] = page_id
        cell["edit_url"] = _edit_url(page_id)
        cell["copy_url"] = _copy_url(page_id)
        cell["delete_url"] = _delete_url(page_id)
        if is_alias:
            cell["convert_alias_url"] = _convert_alias_url(page_id)
        if is_live:
            cell["unpublish_url"] = _unpublish_url(page_id)
            if site_roots is not None:
                view = _live_url(matrix_row.get("url_path") or "", site_roots)
                if view:
                    cell["view_url"] = view
        if outdated and status in (STATUS_PUBLISHED, STATUS_CHANGED):
            cell["outdated"] = True
    return cell


def _node_dict(
    row: dict,
    *,
    locales,
    matrix_index: dict[tuple[str, int], dict],
    visible_counts: dict[int, int],
    placeholder: bool,
    page_type_names: Optional[dict[int, str]] = None,
    site_roots=None,
    outdated: frozenset[tuple] = frozenset(),
    sync_ids: Optional[dict] = None,
    translatable_keys: frozenset = frozenset(),
) -> dict:
    """Build one tree node.

    Placeholder rows expose only title + depth + visible_numchild — no
    slug, no translation_key, no per-locale data, no edit_url.

    ``sync_ids`` / ``translatable_keys`` (wagtail-localize): surface the
    "Sync translated pages" / "Translate this page" links on the *primary*
    (source) locale cell only — never on a target cell.
    """
    node: dict = {
        "id": row["id"],
        "title": row["title"],
        "depth": row["depth"],
        "parent_id": row.get("parent_id"),
        "visible_numchild": visible_counts.get(row["id"], 0),
        "is_placeholder": placeholder,
    }
    if placeholder:
        return node

    node["slug"] = row["slug"]
    node["edit_url"] = _edit_url(row["id"])
    node["add_child_url"] = _add_child_url(row["id"])
    node["copy_url"] = _copy_url(row["id"])
    node["delete_url"] = _delete_url(row["id"])
    node["page_type_id"] = row["content_type_id"]
    if page_type_names is not None:
        node["page_type"] = page_type_names.get(row["content_type_id"])
    node["show_in_menus"] = bool(row.get("show_in_menus"))

    # Live frontend URL for the "view" affordance. Only meaningful when
    # the page is actually live; drafts have no public URL.
    if row.get("live") and site_roots is not None:
        url_path = row.get("url_path") or ""
        view_url = _live_url(url_path, site_roots)
        if view_url is not None:
            node["view_url"] = view_url

    primary_parent_key = row.get("parent_translation_key")
    primary_parent_title = row.get("parent_title")
    primary_edit_url = _edit_url(row["id"])
    translation_key = row["translation_key"]
    translations: dict[str, dict] = {}
    for loc in locales:
        loc_code = loc.language_code
        if loc.id == row.get("primary_locale_id"):
            # Primary cell — the row IS the translation (and the source, so
            # never "outdated" against itself).
            cell = _translation_cell(
                row,
                primary_parent_translation_key=primary_parent_key,
                primary_parent_title=primary_parent_title,
                site_roots=site_roots,
            )
            # wagtail-localize source actions live on the primary cell only.
            source_id = (sync_ids or {}).get(translation_key)
            if source_id is not None:
                url = _localize_url(
                    "wagtail_localize:update_translations", source_id
                )
                if url:
                    cell["sync_translations_url"] = url
            if translation_key in translatable_keys:
                url = _localize_url(
                    "wagtail_localize:submit_page_translation", row["id"]
                )
                if url:
                    cell["translate_page_url"] = url
        else:
            cell_row = matrix_index.get((translation_key, loc.id))
            cell = _translation_cell(
                cell_row,
                primary_parent_translation_key=primary_parent_key,
                primary_parent_title=primary_parent_title,
                site_roots=site_roots,
                outdated=(translation_key, loc.id) in outdated,
            )
        # Empty cells get a "create translation" entry pointing at the
        # source page's edit view; user uses Wagtail's "Translate this page"
        # flow from there.
        if cell["status"] == "empty":
            cell["create_translation_url"] = primary_edit_url
        translations[loc_code] = cell
    node["translations"] = translations
    return node


def _index_matrix(matrix: list[dict]) -> dict[tuple[str, int], dict]:
    return {(row["translation_key"], row["locale_id"]): row for row in matrix}


def build_tree_payload(
    *,
    primary_locale,
    all_locales,
    permitted: set[int],
    placeholder: set[int],
    editable: set[int] | None = None,
    can_submit_translation: bool = False,
) -> dict:
    """Top-level payload assembler. One function, one transaction worth of work.

    ``editable`` defaults to ``permitted - placeholder`` for callers that
    don't compute it explicitly. The orphan query uses this narrower set
    so navigation-only ancestor pages (which Wagtail's permission policy
    folds into ``explorable_instances``) don't leak into the orphan list.

    ``can_submit_translation`` gates the wagtail-localize source links
    (Sync / Translate) on the primary cell — pass the user's
    ``wagtail_localize.submit_translation`` permission.
    """
    if editable is None:
        editable = permitted - placeholder

    primary = fetch_primary_rows(primary_locale, permitted)
    annotate_parent_translation_keys(primary)
    for row in primary:
        row["primary_locale_id"] = primary_locale.id

    keys = {row["translation_key"] for row in primary}
    matrix = fetch_translation_matrix(keys, primary_locale.id, permitted)
    annotate_matrix_alignment(matrix)
    matrix_index = _index_matrix(matrix)
    outdated = frozenset(outdated_pairs(keys))

    sync_ids, translatable_keys = _localize_source_actions(
        primary, matrix, primary_locale, all_locales, can_submit_translation
    )

    counts = visible_numchild(primary)
    page_type_names = _resolve_page_type_names(
        row.get("content_type_id") for row in primary
    )
    site_roots = _site_root_paths_cache()
    nodes = [
        _node_dict(
            row,
            locales=all_locales,
            matrix_index=matrix_index,
            visible_counts=counts,
            placeholder=row["id"] in placeholder,
            page_type_names=page_type_names,
            site_roots=site_roots,
            outdated=outdated,
            sync_ids=sync_ids,
            translatable_keys=translatable_keys,
        )
        for row in primary
    ]

    orphans = fetch_orphans(primary_locale.id, keys, editable)
    orphan_payload = [
        {
            "id": o["id"],
            "title": o["title"],
            "slug": o["slug"],
            "locale_code": o["locale__language_code"],
            "edit_url": _edit_url(o["id"]),
            "status": "published"
            if o.get("live") and not o.get("has_unpublished_changes")
            else ("changed" if o.get("live") else "draft"),
            "is_alias": o.get("alias_of_id") is not None,
        }
        for o in orphans
    ]

    return {
        "locales": _locale_summary(all_locales),
        "primary_locale": primary_locale.language_code,
        "pages": nodes,
        "orphans": orphan_payload,
        "page_types": _page_type_options(nodes),
    }


def build_search_payload(
    *,
    primary_locale,
    all_locales,
    matches: Iterable[dict],
    ancestor_paths: Iterable[str],
    permitted: set[int],
    placeholder: set[int],
    can_submit_translation: bool = False,
) -> dict:
    """Search response — matches + ancestor IDs the client should expand."""
    matches_list = list(matches)
    ancestor_paths_list = list(ancestor_paths)
    # annotate_* set parent_id (for flat rendering) but only resolve
    # parent_translation_key within this sparse match set — overwrite it with a
    # DB-backed lookup so alignment (the diverged signal) is correct here too.
    annotate_parent_translation_keys(matches_list)
    resolve_parent_translation_keys_via_db(
        matches_list, default_locale_id=primary_locale.id
    )
    for row in matches_list:
        row["primary_locale_id"] = primary_locale.id

    keys = {row["translation_key"] for row in matches_list}
    matrix = fetch_translation_matrix(keys, primary_locale.id, permitted)
    annotate_matrix_alignment(matrix)
    resolve_parent_translation_keys_via_db(matrix)
    matrix_index = _index_matrix(matrix)
    outdated = frozenset(outdated_pairs(keys))
    sync_ids, translatable_keys = _localize_source_actions(
        matches_list, matrix, primary_locale, all_locales, can_submit_translation
    )
    counts = visible_numchild(matches_list)
    page_type_names = _resolve_page_type_names(
        row.get("content_type_id") for row in matches_list
    )
    site_roots = _site_root_paths_cache()

    return {
        "locales": _locale_summary(all_locales),
        "primary_locale": primary_locale.language_code,
        "matches": [
            _node_dict(
                row,
                locales=all_locales,
                matrix_index=matrix_index,
                visible_counts=counts,
                placeholder=row["id"] in placeholder,
                page_type_names=page_type_names,
                site_roots=site_roots,
                outdated=outdated,
                sync_ids=sync_ids,
                translatable_keys=translatable_keys,
            )
            for row in matches_list
        ],
        "ancestor_paths": ancestor_paths_list,
    }
