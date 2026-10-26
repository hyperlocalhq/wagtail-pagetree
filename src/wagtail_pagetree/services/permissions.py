"""Permission set computation — single source of truth for visibility."""

from typing import Any, Optional

from wagtail.models import Page
from wagtail.permission_policies.pages import PagePermissionPolicy

# Actions that grant a user "real" permission to a page (vs. just being able
# to see it as a connective ancestor in the tree).
EDIT_ACTIONS = ("add", "change", "publish", "lock", "unlock", "bulk_delete")

_REQUEST_CACHE_KEY = "_wagtail_pagetree_permitted_ids"
_PLACEHOLDER_CACHE_KEY = "_wagtail_pagetree_placeholder_ids"
_EDITABLE_CACHE_KEY = "_wagtail_pagetree_editable_ids"


def _policy() -> PagePermissionPolicy:
    return PagePermissionPolicy()


def _explorable_ids(user) -> set[int]:
    """IDs visible to user (permitted pages + their ancestors).

    Wraps `PagePermissionPolicy.explorable_instances` and tolerates the
    no-permission case (which raises Page.DoesNotExist via
    `first_common_ancestor_of([])`).
    """
    try:
        qs = _policy().explorable_instances(user)
    except Page.DoesNotExist:
        return set()
    return set(qs.values_list("id", flat=True))


def _editable_ids(user) -> set[int]:
    """IDs the user has any direct edit permission on."""
    qs = _policy().instances_user_has_any_permission_for(user, EDIT_ACTIONS)
    return set(qs.values_list("id", flat=True))


def permitted_ids(request: Any) -> set[int]:
    """All page IDs the user is allowed to see (incl. ancestor placeholders).

    Cached on the request so multiple call sites in one request do not
    re-query. This set covers both directly-editable pages and their
    placeholder ancestors — use ``placeholder_ids`` to distinguish the two.
    """
    cached: Optional[set[int]] = getattr(request, _REQUEST_CACHE_KEY, None)
    if cached is not None:
        return cached
    ids = _explorable_ids(request.user)
    setattr(request, _REQUEST_CACHE_KEY, ids)
    return ids


def placeholder_ids(request: Any) -> set[int]:
    """IDs that are visible but not directly editable — render as placeholders.

    These are ancestor pages of permitted children; the user has no rights
    on them but they need to render as connective tissue. Render with title
    + depth only (no slug, no edit_url, no per-locale data).
    """
    cached: Optional[set[int]] = getattr(request, _PLACEHOLDER_CACHE_KEY, None)
    if cached is not None:
        return cached
    ids = permitted_ids(request) - editable_ids(request)
    setattr(request, _PLACEHOLDER_CACHE_KEY, ids)
    return ids


def editable_ids(request: Any) -> set[int]:
    """IDs the user has direct edit permission on (no navigation ancestors).

    Distinct from ``permitted_ids`` which also includes the user's
    *navigation-only* ancestors (Wagtail's ``explorable_instances`` unions
    in ``page.get_ancestors()`` so deep editors can drill down). For the
    orphan section in particular we must filter by this set, not by the
    broader explorable set — otherwise an EN ancestor of a permitted EN
    page leaks into "Pages without DE" even though the user can't actually
    edit it.
    """
    cached: Optional[set[int]] = getattr(request, _EDITABLE_CACHE_KEY, None)
    if cached is not None:
        return cached
    ids = _editable_ids(request.user)
    setattr(request, _EDITABLE_CACHE_KEY, ids)
    return ids
