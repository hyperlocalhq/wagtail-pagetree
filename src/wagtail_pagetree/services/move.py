"""Drag-and-drop reorder / move-to-different-parent service.

Wraps Wagtail's ``Page.move()`` (treebeard MP) with the permission check
that Wagtail's own admin uses (``can_move_to``) plus pre-flight guards
against cycles and root moves so we return a clean 400 instead of a 500.

wagtail-localize follows automatically: it has signal handlers on Page
move that re-anchor translations under the corresponding translated
parent, so the matrix view reflects the move on next refetch.
"""

import logging
from typing import Literal

from django.core.exceptions import ValidationError

from wagtail.models import Page

logger = logging.getLogger("wagtail_pagetree.move")


SUPPORTED_POSITIONS = ("before", "after", "inside")
PositionLiteral = Literal["before", "after", "inside"]


class MoveError(Exception):
    """Base class for caller-facing move failures."""

    code: str = "move_failed"


class MoveNotFound(MoveError):
    code = "not_found"


class MoveDenied(MoveError):
    code = "denied"


class MoveInvalid(MoveError):
    code = "invalid"


# Map our drop-zone semantics → treebeard position strings.
# - "before" / "after" reorder among siblings of the target.
# - "inside"  appends as the LAST child of the target so the new row
#   appears at the bottom of the (possibly long) child list — same as
#   Wagtail's own "Move to a different parent" UI default.
_TREEBEARD_POSITION = {
    "before": "left",
    "after": "right",
    "inside": "last-child",
}


def apply_move(
    *,
    user,
    page_id: int,
    target_id: int,
    position: str,
    cascade_translations: bool = True,
) -> dict:
    """Move ``page_id`` to ``position`` relative to ``target_id``.

    Returns ``{"page_id", "new_parent_id", "position", "noop", "cascade": [...]}``
    on success. ``cascade`` is a list of per-locale outcomes for the page's
    translations (always present; empty list when ``cascade_translations``
    is False or the page has no translations in other locales).

    wagtail-localize does **not** ship a Page-move signal handler, so
    translations stay put unless we move them ourselves. Cascading is the
    right default for our matrix view — without it, every primary-tree
    reorder leaves diverged dots in its wake.

    Raises ``MoveError`` subclass on any failure mode for the *primary*
    move that the caller should surface as a 4xx. Cascade failures are
    recorded in the result, never raised — the primary move already
    succeeded and we don't want to roll it back over a translation.
    """
    if position not in SUPPORTED_POSITIONS:
        raise MoveInvalid(f"position must be one of {SUPPORTED_POSITIONS!r}.")

    try:
        page = Page.objects.get(id=page_id).specific
    except Page.DoesNotExist as exc:
        raise MoveNotFound(f"Page {page_id} not found.") from exc

    try:
        target = Page.objects.get(id=target_id).specific
    except Page.DoesNotExist as exc:
        raise MoveNotFound(f"Target page {target_id} not found.") from exc

    if page.is_root():
        raise MoveInvalid("Cannot move the root page.")

    if page.id == target.id:
        raise MoveInvalid("Cannot drop a page onto itself.")

    # New parent is the target itself for "inside", otherwise the target's
    # parent (sibling reorder). Resolve up front so we can permission-check.
    if position == "inside":
        new_parent = target
    else:
        new_parent = target.get_parent()
        if new_parent is None:
            raise MoveInvalid("Cannot reorder siblings of the root page.")

    # Cycle: cannot move a page into itself or any of its descendants.
    if new_parent.id == page.id or new_parent.path.startswith(page.path):
        raise MoveInvalid("Cannot move a page into its own subtree.")

    # No-op short-circuit: re-dropping a page in its current spot.
    if (
        position == "inside"
        and page.get_parent().id == new_parent.id
        and page.get_next_sibling() is None
    ):
        return {
            "page_id": page.id,
            "new_parent_id": new_parent.id,
            "position": position,
            "noop": True,
            "cascade": [],
        }

    # Wagtail's own permission gate. Covers both source-can-move AND
    # target-can-add-child-of-this-type. Same call the move-page admin
    # view uses (`PageMovePermissionTester`).
    perms = page.permissions_for_user(user)
    if not perms.can_move_to(new_parent):
        raise MoveDenied("You do not have permission to move this page here.")

    treebeard_pos = _TREEBEARD_POSITION[position]
    try:
        page.move(target, pos=treebeard_pos, user=user)
    except ValidationError as exc:
        # Foreseeable, user-actionable rejection (e.g. a sibling under the
        # new parent already uses this slug). Surface the human-readable
        # message as a 400; log at info so it stays out of Sentry's error
        # stream — it's not a code fault.
        logger.info(
            "move rejected: page=%s target=%s pos=%s: %s",
            page_id,
            target_id,
            position,
            "; ".join(str(m) for m in exc.messages),
        )
        raise MoveInvalid("; ".join(str(m) for m in exc.messages) or "Move failed.") from exc
    except Exception as exc:  # noqa: BLE001 — surface treebeard/MP errors as 400
        logger.exception(
            "move failed: page=%s target=%s pos=%s", page_id, target_id, position
        )
        raise MoveInvalid(str(exc) or "Move failed.") from exc

    cascade = (
        _cascade_translations(
            user=user,
            page=page,
            target=target,
            new_parent=new_parent,
            position=position,
            treebeard_pos=treebeard_pos,
        )
        if cascade_translations
        else []
    )

    return {
        "page_id": page.id,
        "new_parent_id": new_parent.id,
        "position": position,
        "noop": False,
        "cascade": cascade,
    }


def _cascade_translations(
    *,
    user,
    page,
    target,
    new_parent,
    position: str,
    treebeard_pos: str,
) -> list[dict]:
    """Move every other-locale translation of ``page`` to mirror the primary move.

    Per-locale outcomes — ``status`` ∈
    ``moved | skipped_no_translation | skipped_no_target | skipped_diverged_target | denied | errored``.
    Each outcome includes ``locale_code`` and (when present) ``page_id``.

    Skip semantics:
    - ``skipped_no_translation``: this locale has no translation of ``page``.
    - ``skipped_no_target``: the locale-equivalent of the target/new-parent
      doesn't exist, so we can't determine a position.
    - ``skipped_diverged_target``: for "before"/"after", the target's
      translation exists but sits under a parent that doesn't share
      ``translation_key`` with the primary new parent — moving here would
      reproduce or deepen an existing divergence elsewhere in the tree.
    """
    from wagtail.models import Locale

    outcomes: list[dict] = []

    # Find sibling translations (same translation_key, different locale).
    sibling_translations = list(
        Page.objects.filter(translation_key=page.translation_key)
        .exclude(id=page.id)
        .specific()
    )
    if not sibling_translations:
        return outcomes

    # Pre-fetch the new_parent and target translations in every relevant
    # locale in one query each (keyed by locale_id).
    locale_ids = [t.locale_id for t in sibling_translations]
    new_parent_translations = {
        p.locale_id: p
        for p in Page.objects.filter(
            translation_key=new_parent.translation_key, locale_id__in=locale_ids
        ).specific()
    }
    target_translations = {
        p.locale_id: p
        for p in Page.objects.filter(
            translation_key=target.translation_key, locale_id__in=locale_ids
        ).specific()
    }
    locale_codes = {
        loc.id: loc.language_code for loc in Locale.objects.filter(id__in=locale_ids)
    }

    for sibling in sibling_translations:
        outcome: dict = {
            "locale_code": locale_codes.get(sibling.locale_id, str(sibling.locale_id)),
            "page_id": sibling.id,
        }

        # Resolve the per-locale move target.
        if position == "inside":
            sibling_target = new_parent_translations.get(sibling.locale_id)
            if sibling_target is None:
                outcome["status"] = "skipped_no_target"
                outcomes.append(outcome)
                continue
            sibling_new_parent = sibling_target  # "inside" → target IS new parent
        else:
            sibling_target = target_translations.get(sibling.locale_id)
            if sibling_target is None:
                outcome["status"] = "skipped_no_target"
                outcomes.append(outcome)
                continue
            sibling_new_parent = sibling_target.get_parent()
            # Don't reproduce an existing divergence: the per-locale
            # target's parent must share translation_key with the primary
            # new parent. Otherwise mirroring here just moves the EN page
            # under whatever parent the EN tree already has — which may
            # not match the primary at all.
            if (
                sibling_new_parent is None
                or sibling_new_parent.translation_key != new_parent.translation_key
            ):
                outcome["status"] = "skipped_diverged_target"
                outcomes.append(outcome)
                continue

        # No-op short-circuit (already in the right slot).
        sibling_parent = sibling.get_parent()
        if (
            position == "inside"
            and sibling_parent is not None
            and sibling_parent.id == sibling_new_parent.id
            and sibling.get_next_sibling() is None
        ):
            outcome["status"] = "moved"
            outcome["noop"] = True
            outcomes.append(outcome)
            continue

        # Per-translation permission re-check. If the user can't move
        # this specific translation, skip it (don't fail the whole call).
        try:
            perms = sibling.permissions_for_user(user)
            if not perms.can_move_to(sibling_new_parent):
                outcome["status"] = "denied"
                outcomes.append(outcome)
                continue
            sibling.move(sibling_target, pos=treebeard_pos, user=user)
            outcome["status"] = "moved"
        except ValidationError as exc:
            # User-actionable rejection on a translation (e.g. slug clash).
            # Record it, log at info — not a code fault, keep out of Sentry.
            logger.info(
                "cascade move rejected: page=%s sibling=%s pos=%s: %s",
                page.id,
                sibling.id,
                position,
                "; ".join(str(m) for m in exc.messages),
            )
            outcome["status"] = "errored"
        except Exception:  # noqa: BLE001 — never let one bad translation 500 the call
            logger.exception(
                "cascade move failed: page=%s sibling=%s pos=%s",
                page.id,
                sibling.id,
                position,
            )
            outcome["status"] = "errored"

        outcomes.append(outcome)

    return outcomes
