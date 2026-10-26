"""Bulk publish / unpublish service.

Wraps Wagtail's existing ``PublishPageRevisionAction`` and
``UnpublishPageAction`` so the API endpoint can apply them to a list of
page IDs with per-page permission checks. Returns a structured summary
the frontend can flash.
"""

import logging
from typing import Iterable, Literal, TypedDict

from django.core.exceptions import PermissionDenied
from wagtail.actions.publish_page_revision import PublishPageRevisionAction
from wagtail.actions.unpublish_page import UnpublishPageAction
from wagtail.models import Page

logger = logging.getLogger("wagtail_pagetree.bulk")


SUPPORTED_ACTIONS = ("publish", "unpublish")
ActionLiteral = Literal["publish", "unpublish"]


class BulkSummary(TypedDict):
    success: list[int]
    denied: list[int]
    skipped: list[int]
    errored: list[int]


def apply_bulk_action(
    *,
    user,
    action: str,
    page_ids: Iterable[int],
    permitted: set[int],
    target_locale_id: int | None = None,
) -> BulkSummary:
    """Apply ``action`` to each page id, recording per-page outcome.

    - ``permitted`` is the user's editable set (from ``editable_ids``); pages
      outside this set go to ``denied`` without touching the DB.
    - For each in-permission page, Wagtail's own action class is invoked,
      which performs its own ``can_publish`` / ``can_unpublish`` check and
      raises ``PermissionDenied`` on denial — caught and recorded.
    - ``skipped`` covers no-op cases (e.g. trying to publish an alias, or
      unpublish a draft, or no translation exists in the requested locale).
    - ``errored`` covers unexpected exceptions; logged with stack.
    - **Per-locale targeting** (``target_locale_id``): when set, each
      input ``page_id`` is treated as a *primary*-locale row id, and the
      action is applied to its translation in the target locale (resolved
      via ``translation_key``). Permission re-checked against the *resolved*
      page id. The summary keeps the *resolved* page ids so the UI flash
      maps back to the same translation_key/locale cell the user clicked.
    """
    if action not in SUPPORTED_ACTIONS:
        raise ValueError(f"unsupported bulk action: {action!r}")

    summary: BulkSummary = {
        "success": [],
        "denied": [],
        "skipped": [],
        "errored": [],
    }

    ids = [int(pid) for pid in page_ids]

    # Resolve to the target-locale translations when a locale is specified.
    # We do this BEFORE the permission filter so the resolved id is what
    # gets gated against `permitted` (which is per-Page-instance).
    if target_locale_id is not None:
        primary_pages = Page.objects.filter(id__in=ids).values(
            "id", "translation_key", "locale_id"
        )
        primary_to_keys = {p["id"]: p["translation_key"] for p in primary_pages}
        keys = set(primary_to_keys.values())
        translations = Page.objects.filter(
            translation_key__in=keys, locale_id=target_locale_id
        ).values("id", "translation_key")
        key_to_translation = {t["translation_key"]: t["id"] for t in translations}
        resolved: list[tuple[int, int | None]] = []
        for pid in ids:
            key = primary_to_keys.get(pid)
            if key is None:
                # Source primary page doesn't exist (race/concurrent delete).
                resolved.append((pid, None))
                continue
            tid = key_to_translation.get(key)
            resolved.append((pid, tid))
    else:
        resolved = [(pid, pid) for pid in ids]

    target_ids = [tid for (_orig, tid) in resolved if tid is not None]
    pages = {p.id: p for p in Page.objects.filter(id__in=target_ids).specific()}

    for orig_id, tid in resolved:
        if tid is None:
            # No translation in the target locale — nothing to act on.
            summary["skipped"].append(orig_id)
            continue
        page = pages.get(tid)
        if page is None:
            summary["skipped"].append(tid)
            continue
        if tid not in permitted:
            summary["denied"].append(tid)
            continue
        try:
            if action == "publish":
                if page.alias_of_id is not None:
                    # Alias pages have no own content to publish.
                    summary["skipped"].append(tid)
                    continue
                revision = page.get_latest_revision()
                if revision is None:
                    summary["skipped"].append(tid)
                    continue
                PublishPageRevisionAction(revision, user=user).execute()
            elif action == "unpublish":
                if not page.live:
                    summary["skipped"].append(tid)
                    continue
                UnpublishPageAction(page, user=user).execute()
            summary["success"].append(tid)
        except PermissionDenied:
            summary["denied"].append(tid)
        except Exception:  # noqa: BLE001 — bulk endpoint must not 500 on one bad page
            logger.exception("bulk action %s failed on page %s", action, tid)
            summary["errored"].append(tid)

    return summary
