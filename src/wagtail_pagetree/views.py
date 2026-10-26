"""Page Tree admin view + JSON API endpoints.

Auth: all viewset URLs are wrapped with ``require_admin_access`` by Wagtail's
``wagtail.admin.urls``. No extra auth decorator needed here.
"""

import json
import logging
from typing import Optional

from django.http import HttpRequest, JsonResponse
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView, View
from wagtail.models import Locale, Page

from .services.bulk import SUPPORTED_ACTIONS, apply_bulk_action
from .services.locale import InvalidLocale, resolve_locale
from .services.move import (
    SUPPORTED_POSITIONS,
    MoveDenied,
    MoveError,
    MoveInvalid,
    MoveNotFound,
    apply_move,
)
from .services.permissions import editable_ids, permitted_ids, placeholder_ids
from .services.presenters import (
    build_search_payload,
    build_tree_payload,
)
from .services.search import (
    FILTER_STATUSES,
    SearchTooBroad,
    SearchTooLong,
    filter_page_type,
    filter_primary,
    search_primary,
)
from .services.translations import outdated_pairs
from .services.tree import (
    annotate_matrix_alignment,
    annotate_parent_translation_keys,
    fetch_translation_matrix,
    visible_numchild,
)
from .services.tree import (
    PRIMARY_FIELDS,
)
from .services.presenters import (
    _node_dict,
    _index_matrix,
    _locale_summary,
    _resolve_page_type_names,
    _site_root_paths_cache,
)  # internal reuse


logger = logging.getLogger("wagtail_pagetree.tree")


class PageTreeView(TemplateView):
    template_name = "wagtail_pagetree/page_tree.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["header_title"] = _("Page Tree")
        context["header_icon"] = "list-ul"
        context["page_title"] = _("Page Tree")
        return context


def _json_error(code: str, message: str, status: int) -> JsonResponse:
    response = JsonResponse(
        {"error": {"code": code, "message": message}}, status=status
    )
    response["Cache-Control"] = "private, no-store"
    return response


def _json_ok(payload: dict) -> JsonResponse:
    response = JsonResponse(payload)
    response["Cache-Control"] = "private, no-store"
    return response


def _resolve_or_400(code: Optional[str]):
    """Return (locale, None) on success or (None, JsonResponse-400) on failure."""
    try:
        return resolve_locale(code), None
    except InvalidLocale:
        error = _json_error(
            code="invalid_locale",
            message=f"Unknown locale: {code!r}",
            status=400,
        )
        return None, error


def _str_param(request: HttpRequest, key: str) -> Optional[str]:
    """Pull a single string query param, ignoring multi-value lists."""
    value = request.GET.get(key)
    return value if isinstance(value, str) else None


class TreeAPIView(View):
    def get(self, request: HttpRequest, *args, **kwargs) -> JsonResponse:
        del args, kwargs
        locale, error = _resolve_or_400(_str_param(request, "locale"))
        if error is not None or locale is None:
            return error or _json_error("invalid_locale", "Unknown locale.", 400)
        all_locales = list(Locale.objects.all())
        permitted = permitted_ids(request)
        placeholder = placeholder_ids(request)
        can_submit_translation = request.user.has_perm(
            "wagtail_localize.submit_translation"
        )

        # Page-type filter: narrows the search / status filter below, or is a
        # filter mode of its own when neither is set.
        page_type_raw = (_str_param(request, "page_type") or "").strip()
        page_type_id: Optional[int] = None
        if page_type_raw:
            try:
                page_type_id = int(page_type_raw)
            except ValueError:
                return _json_error(
                    "invalid_page_type",
                    "page_type must be a content type id.",
                    400,
                )

        search_query = (_str_param(request, "search") or "").strip()
        if search_query:
            return self._search(
                request=request,
                locale=locale,
                all_locales=all_locales,
                permitted=permitted,
                placeholder=placeholder,
                query=search_query,
                page_type_id=page_type_id,
                can_submit_translation=can_submit_translation,
            )

        filter_status = (_str_param(request, "filter_status") or "").strip()
        filter_locale_code = (_str_param(request, "filter_locale") or "").strip()
        if filter_status or filter_locale_code:
            if not (filter_status and filter_locale_code):
                return _json_error(
                    "invalid_filter",
                    "filter_locale and filter_status are both required.",
                    400,
                )
            if filter_status not in FILTER_STATUSES:
                return _json_error(
                    "invalid_filter_status",
                    f"filter_status must be one of {sorted(FILTER_STATUSES)!r}.",
                    400,
                )
            target_locale, target_error = _resolve_or_400(filter_locale_code)
            if target_error is not None or target_locale is None:
                return target_error or _json_error(
                    "invalid_locale", "Unknown locale.", 400
                )
            return self._filter(
                request=request,
                locale=locale,
                target_locale=target_locale,
                status=filter_status,
                all_locales=all_locales,
                permitted=permitted,
                placeholder=placeholder,
                page_type_id=page_type_id,
                can_submit_translation=can_submit_translation,
            )

        if page_type_id is not None:
            matches, ancestor_paths = filter_page_type(
                locale=locale, permitted=permitted, page_type_id=page_type_id
            )
            return self._matches_response(
                locale=locale,
                all_locales=all_locales,
                matches=matches,
                ancestor_paths=ancestor_paths,
                permitted=permitted,
                placeholder=placeholder,
                can_submit_translation=can_submit_translation,
                log_event="pagetree.page_type",
                log_extra={"page_type_id": page_type_id},
            )

        payload = build_tree_payload(
            primary_locale=locale,
            all_locales=all_locales,
            permitted=permitted,
            placeholder=placeholder,
            can_submit_translation=can_submit_translation,
        )
        logger.info(
            "pagetree.tree",
            extra={
                "primary_locale": locale.language_code,
                "node_count": len(payload["pages"]),
                "permitted_count": len(permitted),
            },
        )
        return _json_ok(payload)

    def _search(
        self,
        *,
        request,
        locale,
        all_locales,
        permitted,
        placeholder,
        query,
        page_type_id=None,
        can_submit_translation=False,
    ):
        try:
            matches, ancestor_paths = search_primary(
                locale=locale,
                permitted=permitted,
                query=query,
                page_type_id=page_type_id,
            )
        except SearchTooLong:
            return _json_error(
                code="search_too_long",
                message="Search query exceeds 200 characters.",
                status=400,
            )
        except SearchTooBroad:
            return _json_error(
                code="search_too_broad",
                message="Too many matches; please refine the query.",
                status=400,
            )
        return self._matches_response(
            locale=locale,
            all_locales=all_locales,
            matches=matches,
            ancestor_paths=ancestor_paths,
            permitted=permitted,
            placeholder=placeholder,
            can_submit_translation=can_submit_translation,
            log_event="pagetree.search",
            log_extra={"query_len": len(query), "page_type_id": page_type_id},
        )

    def _filter(
        self,
        *,
        request,
        locale,
        target_locale,
        status,
        all_locales,
        permitted,
        placeholder,
        page_type_id=None,
        can_submit_translation=False,
    ):
        """Filter mode: pages whose ``target_locale`` cell matches ``status``.

        Reuses the search payload/render path — returns the same
        ``matches + ancestor_paths`` shape the frontend already auto-expands.
        """
        del request
        matches, ancestor_paths = filter_primary(
            primary_locale=locale,
            target_locale=target_locale,
            status=status,
            permitted=permitted,
            page_type_id=page_type_id,
        )
        return self._matches_response(
            locale=locale,
            all_locales=all_locales,
            matches=matches,
            ancestor_paths=ancestor_paths,
            permitted=permitted,
            placeholder=placeholder,
            can_submit_translation=can_submit_translation,
            log_event="pagetree.filter",
            log_extra={
                "filter_locale": target_locale.language_code,
                "filter_status": status,
                "page_type_id": page_type_id,
            },
        )

    def _matches_response(
        self,
        *,
        locale,
        all_locales,
        matches,
        ancestor_paths,
        permitted,
        placeholder,
        can_submit_translation,
        log_event,
        log_extra,
    ):
        """Render a search / filter match set (flat list + auto-expand)."""
        payload = build_search_payload(
            primary_locale=locale,
            all_locales=all_locales,
            matches=matches,
            ancestor_paths=ancestor_paths,
            permitted=permitted,
            placeholder=placeholder,
            can_submit_translation=can_submit_translation,
        )
        logger.info(
            log_event,
            extra={
                "primary_locale": locale.language_code,
                "match_count": len(payload["matches"]),
                **log_extra,
            },
        )
        return _json_ok(payload)


class ChildrenAPIView(View):
    """Lazy-load the direct children of a single primary-locale page."""

    def get(self, request: HttpRequest, page_id: int, *args, **kwargs) -> JsonResponse:
        del args, kwargs
        locale, error = _resolve_or_400(_str_param(request, "locale"))
        if error is not None or locale is None:
            return error or _json_error("invalid_locale", "Unknown locale.", 400)

        permitted = permitted_ids(request)
        placeholder = placeholder_ids(request)
        if page_id not in permitted:
            return _json_error(
                code="not_found_or_denied",
                message="Page not found or permission denied.",
                status=403,
            )

        try:
            parent = Page.objects.values("path", "depth", "locale_id").get(
                id=page_id, locale=locale
            )
        except Page.DoesNotExist:
            return _json_error(
                code="not_found",
                message=f"Page {page_id} not found in primary locale.",
                status=404,
            )

        children = list(
            Page.objects.filter(
                locale=locale,
                id__in=permitted,
                path__startswith=parent["path"],
                depth=parent["depth"] + 1,
            )
            .values(*PRIMARY_FIELDS)
            .order_by("path")
        )
        annotate_parent_translation_keys(children)
        for row in children:
            row["primary_locale_id"] = locale.id

        keys = {row["translation_key"] for row in children}
        matrix = fetch_translation_matrix(keys, locale.id, permitted)
        annotate_matrix_alignment(matrix)
        matrix_index = _index_matrix(matrix)
        outdated = frozenset(outdated_pairs(keys))
        counts = visible_numchild(children)
        page_type_names = _resolve_page_type_names(
            row.get("content_type_id") for row in children
        )
        site_roots = _site_root_paths_cache()
        all_locales = list(Locale.objects.all())

        payload = {
            "locales": _locale_summary(all_locales),
            "primary_locale": locale.language_code,
            "parent_id": page_id,
            "pages": [
                _node_dict(
                    row,
                    locales=all_locales,
                    matrix_index=matrix_index,
                    visible_counts=counts,
                    placeholder=row["id"] in placeholder,
                    page_type_names=page_type_names,
                    site_roots=site_roots,
                    outdated=outdated,
                )
                for row in children
            ],
        }
        logger.info(
            "pagetree.children",
            extra={
                "parent_id": page_id,
                "child_count": len(children),
            },
        )
        return _json_ok(payload)


class BulkActionView(View):
    """Apply a bulk publish/unpublish action to a list of page ids.

    Body: ``{"action": "publish"|"unpublish", "page_ids": [int, ...]}``.
    Response envelope mirrors the per-page outcome so the UI can flash
    a useful summary ("3 published, 1 denied, 1 skipped").

    Permission gate: same ``editable_ids`` set the orphan query uses.
    Wagtail's action classes also enforce their own ``can_publish`` /
    ``can_unpublish`` checks, so this is defence-in-depth.
    """

    http_method_names = ["post", "options"]

    def post(self, request: HttpRequest, *args, **kwargs) -> JsonResponse:
        del args, kwargs
        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return _json_error("invalid_json", "Body must be JSON.", 400)

        action = body.get("action")
        if action not in SUPPORTED_ACTIONS:
            return _json_error(
                "invalid_action",
                f"action must be one of {sorted(SUPPORTED_ACTIONS)!r}.",
                400,
            )

        raw_ids = body.get("page_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            return _json_error(
                "invalid_page_ids",
                "page_ids must be a non-empty list of integers.",
                400,
            )
        try:
            page_ids = [int(pid) for pid in raw_ids]
        except (TypeError, ValueError):
            return _json_error(
                "invalid_page_ids",
                "page_ids entries must be integers.",
                400,
            )
        if len(page_ids) > 200:
            return _json_error(
                "too_many_page_ids",
                "page_ids must contain at most 200 entries.",
                400,
            )

        # Optional per-locale targeting — when set, the action applies to
        # the translation of each input page in the given locale rather
        # than to the input page itself.
        target_locale_id: Optional[int] = None
        target_code = body.get("locale_code")
        if target_code:
            try:
                target_locale_id = Locale.objects.get(language_code=target_code).id
            except Locale.DoesNotExist:
                return _json_error(
                    "invalid_locale",
                    f"Unknown locale_code: {target_code!r}.",
                    400,
                )

        editable = editable_ids(request)
        summary = apply_bulk_action(
            user=request.user,
            action=action,
            page_ids=page_ids,
            permitted=editable,
            target_locale_id=target_locale_id,
        )
        logger.info(
            "pagetree.bulk",
            extra={
                "action": action,
                "locale": target_code,
                "requested": len(page_ids),
                **{k: len(v) for k, v in summary.items()},
            },
        )
        return _json_ok({"action": action, "locale_code": target_code, **summary})


class MoveActionView(View):
    """Move a single page within the tree (drag-and-drop reorder).

    Body: ``{"page_id": int, "target_id": int, "position": "before"|"after"|"inside"}``.

    Permission gate: Wagtail's own ``can_move_to`` runs inside ``apply_move``
    — it covers both source-can-move and target-can-add-child-of-this-type.
    The endpoint is mutating, so we also keep the source within the user's
    editable set as a defence-in-depth pre-check (cheaper than constructing
    the page object before failing).
    """

    http_method_names = ["post", "options"]

    def post(self, request: HttpRequest, *args, **kwargs) -> JsonResponse:
        del args, kwargs
        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return _json_error("invalid_json", "Body must be JSON.", 400)

        try:
            page_id = int(body.get("page_id"))
            target_id = int(body.get("target_id"))
        except (TypeError, ValueError):
            return _json_error(
                "invalid_ids",
                "page_id and target_id must be integers.",
                400,
            )
        position = body.get("position")
        if position not in SUPPORTED_POSITIONS:
            return _json_error(
                "invalid_position",
                f"position must be one of {sorted(SUPPORTED_POSITIONS)!r}.",
                400,
            )

        # Defence-in-depth: source must be in the user's editable set.
        # apply_move re-checks via Wagtail's own permission policy.
        if page_id not in editable_ids(request):
            return _json_error("denied", "Permission denied.", 403)

        # Default ON — cascading translations is the right thing for the
        # matrix view (otherwise primary-tree reorders leave diverged dots
        # everywhere). Clients can opt out with cascade_translations=false.
        cascade = body.get("cascade_translations", True)
        if not isinstance(cascade, bool):
            return _json_error(
                "invalid_cascade",
                "cascade_translations must be a boolean.",
                400,
            )

        try:
            result = apply_move(
                user=request.user,
                page_id=page_id,
                target_id=target_id,
                position=position,
                cascade_translations=cascade,
            )
        except MoveNotFound as exc:
            return _json_error(MoveNotFound.code, str(exc), 404)
        except MoveDenied as exc:
            return _json_error(MoveDenied.code, str(exc), 403)
        except MoveInvalid as exc:
            return _json_error(MoveInvalid.code, str(exc), 400)
        except MoveError as exc:  # safety net
            return _json_error(MoveError.code, str(exc), 400)

        logger.info(
            "pagetree.move",
            extra={
                "page_id": result["page_id"],
                "new_parent_id": result["new_parent_id"],
                "position": result["position"],
                "noop": result["noop"],
            },
        )
        return _json_ok(result)
