"""Out-of-date translation detection via wagtail-localize (optional).

Surfaces the "source changed → translation needs update" signal in the tree.
A translation is *out of date* when **either**:

1. **Untranslated segments** — its source has a string segment with no
   (non-errored) ``StringTranslation`` in the target locale, exactly the state
   wagtail-localize's ``Translation.get_status_display()`` calls "Waiting for
   translations". This fires once the source snapshot has been refreshed and a
   newly-added/changed string has no translation yet.

2. **Snapshot drift** — the source page has a revision newer than the
   ``TranslationSource`` snapshot the segments were last extracted from
   (``latest_revision_created_at > last_updated_at``). This catches a source
   that was edited but whose snapshot hasn't been re-synced — the exact gap
   condition (1) alone misses, because the *stale* snapshot's segments are all
   still translated. Where the host project re-syncs the snapshot on publish,
   this path in practice flags source pages with **unpublished draft edits**
   (and any snapshot left stale before such a hook existed). This path is
   **pages only** — it joins ``Page`` for the revision timestamp; snippet
   sources get their snapshot refreshed on publish but aren't drift-checked
   here, which is moot since the tree only renders pages.

wagtail-localize is an **optional** integration: the package declares only
Django + Wagtail as dependencies and must stay installable without it. When it
is absent (or no Translations exist), ``outdated_pairs`` returns an empty set
and no cell is ever flagged.

The returned pairs are keyed by ``(translation_key, target_locale_id)`` because
``TranslationSource.object_id`` is the source page's ``translation_key`` — the
same key the tree's translation matrix is indexed by.
"""

import logging

logger = logging.getLogger("wagtail_pagetree.translations")


def outdated_pairs(translation_keys: set) -> set[tuple]:
    """Return the stale ``(translation_key, target_locale_id)`` pairs.

    A pair is stale when an *enabled* ``Translation`` exists for the source
    (``source.object_id`` ∈ ``translation_keys``) and **either** at least one of
    the source's string segments has no non-errored translation in the target
    locale, **or** the source page has been revised since its snapshot was last
    refreshed (see the module docstring).

    Two queries (untranslated-segments + snapshot-drift), unioned. Returns an
    empty set when wagtail-localize is not installed or no translation keys are
    given.
    """
    if not translation_keys:
        return set()

    try:
        from django.db.models import Exists, F, OuterRef, Subquery
        from wagtail.models import Page
        from wagtail_localize.models import (
            StringSegment,
            StringTranslation,
            Translation,
        )
    except ImportError:
        # wagtail-localize not installed — feature simply absent.
        return set()

    # A source segment that has NO non-errored translation in the target
    # locale. Correlated to the outer Translation row via:
    #   - source_id            (this segment belongs to the Translation's source)
    #   - target_locale_id     (two levels out, hence the nested OuterRef)
    untranslated_segment = (
        StringSegment.objects.filter(source_id=OuterRef("source_id"))
        .annotate(
            has_translation=Exists(
                StringTranslation.objects.filter(
                    translation_of_id=OuterRef("string_id"),
                    context_id=OuterRef("context_id"),
                    locale_id=OuterRef(OuterRef("target_locale_id")),
                    has_error=False,
                )
            )
        )
        .filter(has_translation=False)
    )

    # The newest revision timestamp of the source page (matched by the source's
    # own translation_key + locale). NULL when the source has no revisions (e.g.
    # never edited) or isn't a Page — in which case the ``> last_updated_at``
    # comparison is NULL and the drift path simply doesn't fire.
    source_revised_at = Subquery(
        Page.objects.filter(
            translation_key=OuterRef("source__object_id"),
            locale_id=OuterRef("source__locale_id"),
        ).values("latest_revision_created_at")[:1]
    )

    try:
        enabled = Translation.objects.filter(
            source__object_id__in=translation_keys,
            enabled=True,
        )
        stale_segments = (
            enabled.annotate(is_stale=Exists(untranslated_segment))
            .filter(is_stale=True)
            .values_list("source__object_id", "target_locale_id")
        )
        drifted = (
            enabled.annotate(source_revised_at=source_revised_at)
            .filter(source_revised_at__gt=F("source__last_updated_at"))
            .values_list("source__object_id", "target_locale_id")
        )
        return set(stale_segments) | set(drifted)
    except Exception:  # noqa: BLE001 — never let a staleness probe break the tree
        logger.exception("outdated_pairs query failed; treating all as up to date")
        return set()


def sync_source_ids(translation_keys: set, source_locale_id: int) -> dict:
    """Map source ``translation_key`` → ``TranslationSource.id`` for sources that
    have at least one *enabled* translation.

    These are the sources for which wagtail-localize's "Sync translated pages"
    action is meaningful (it pushes the source's current content to the enabled
    translations). Used to surface that link on the primary-locale dot menu.

    One query. Empty dict when wagtail-localize is not installed or no keys are
    given. ``source_locale_id`` scopes to the source's own locale so a target
    page that is *also* a source for a third locale isn't matched here.
    """
    if not translation_keys:
        return {}

    try:
        from django.db.models import Exists, OuterRef
        from wagtail_localize.models import Translation, TranslationSource
    except ImportError:
        # wagtail-localize not installed — feature simply absent.
        return {}

    try:
        rows = (
            TranslationSource.objects.filter(
                object_id__in=translation_keys,
                locale_id=source_locale_id,
            )
            .annotate(
                has_enabled=Exists(
                    Translation.objects.filter(
                        source_id=OuterRef("id"), enabled=True
                    )
                )
            )
            .filter(has_enabled=True)
            .values_list("object_id", "id")
        )
        return {key: source_id for key, source_id in rows}
    except Exception:  # noqa: BLE001 — never let a link probe break the tree
        logger.exception("sync_source_ids query failed; omitting sync links")
        return {}
