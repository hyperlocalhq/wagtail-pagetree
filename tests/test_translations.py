"""Out-of-date translation detection.

Exercises ``services.translations.outdated_pairs`` against real
wagtail-localize ``Translation`` / ``StringSegment`` / ``StringTranslation``
rows, plus the presenter + ``?outdated=`` API integration.

A translation is *stale* when its source has a string segment with no
non-errored ``StringTranslation`` in the target locale — the same condition
wagtail-localize's own ``Translation.get_status_display()`` reports as
"Waiting for translations".

Run with:
    uv run pytest tests/test_translations.py
"""

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from wagtail.models import Locale, Page
from wagtail_localize.models import (
    String,
    StringSegment,
    StringTranslation,
    TranslatableObject,
    Translation,
    TranslationContext,
    TranslationSource,
)
from wagtail_localize.strings import StringValue

from wagtail_pagetree.services.permissions import permitted_ids, placeholder_ids
from wagtail_pagetree.services.presenters import build_tree_payload
from wagtail_pagetree.services.translations import outdated_pairs, sync_source_ids

User = get_user_model()


def _request(user):
    from django.http import HttpRequest

    req = HttpRequest()
    req.user = user
    req.method = "GET"
    return req


def _make_source(page):
    """Create a TranslationSource for ``page`` with a single string segment."""
    ct = ContentType.objects.get_for_model(Page)
    obj, _ = TranslatableObject.objects.get_or_create(
        translation_key=page.translation_key, defaults={"content_type": ct}
    )
    source = TranslationSource.objects.create(
        object=obj,
        specific_content_type=ct,
        locale=page.locale,
        object_repr=page.title[:200],
        content_json="{}",
        schema_version="",
        last_updated_at=timezone.now(),
    )
    string = String.from_value(page.locale, StringValue.from_plaintext(page.title))
    context, _ = TranslationContext.objects.get_or_create(
        object_id=source.object_id, path="title"
    )
    StringSegment.objects.create(
        source=source, context=context, order=0, string=string, attrs=""
    )
    return source, string, context


def _make_translation(page, target_locale, *, translate=False, has_error=False, enabled=True):
    """Create a wagtail-localize Translation of ``page`` into ``target_locale``.

    - ``translate=True``  → the source segment gets a clean translation
      (so the translation is up to date).
    - ``has_error=True``  → a translation exists but is flagged ``has_error``
      (so it doesn't count → the translation stays stale).
    - neither             → no StringTranslation at all → stale.
    """
    source, string, context = _make_source(page)
    translation = Translation.objects.create(
        source=source, target_locale=target_locale, enabled=enabled
    )
    if translate or has_error:
        StringTranslation.objects.create(
            translation_of=string,
            context=context,
            locale=target_locale,
            data=page.title + " (t)",
            translation_type="manual",
            has_error=has_error,
        )
    return source, translation


class OutdatedPairsTest(TestCase):
    """Unit coverage for the batched stale-pair query."""

    @classmethod
    def setUpTestData(cls):
        cls.de = Locale.objects.get_or_create(language_code="de")[0]
        cls.en = Locale.objects.get_or_create(language_code="en")[0]
        root = Page.objects.filter(depth=1).first() or Page.add_root(
            title="Root", slug="root-t", locale=cls.de
        )

        cls.stale = root.add_child(
            instance=Page(title="Stale page", slug="stale", locale=cls.de, live=True)
        )
        cls.fresh = root.add_child(
            instance=Page(title="Fresh page", slug="fresh", locale=cls.de, live=True)
        )
        cls.errored = root.add_child(
            instance=Page(title="Errored page", slug="errored", locale=cls.de, live=True)
        )
        cls.disabled = root.add_child(
            instance=Page(title="Disabled tr", slug="disabled", locale=cls.de, live=True)
        )
        cls.no_translation = root.add_child(
            instance=Page(title="No translation", slug="notr", locale=cls.de, live=True)
        )
        cls.drifted = root.add_child(
            instance=Page(title="Drifted page", slug="drifted", locale=cls.de, live=True)
        )

        _make_translation(cls.stale, cls.en)  # untranslated → stale
        _make_translation(cls.fresh, cls.en, translate=True)  # fully translated
        _make_translation(cls.errored, cls.en, has_error=True)  # errored → stale
        _make_translation(cls.disabled, cls.en, enabled=False)  # disabled → ignored
        # no_translation: a source with segments but NO Translation row → can
        # never be a pair (outdated_pairs only considers Translations).
        _make_source(cls.no_translation)
        # drifted: fully translated, BUT the source page was revised after the
        # snapshot was last refreshed → stale via the drift path, even
        # though every segment in the (stale) snapshot has a translation.
        drift_source, _ = _make_translation(cls.drifted, cls.en, translate=True)
        cls.drifted.latest_revision_created_at = timezone.now()
        cls.drifted.save(update_fields=["latest_revision_created_at"])
        drift_source.last_updated_at = (
            cls.drifted.latest_revision_created_at - timedelta(minutes=5)
        )
        drift_source.save(update_fields=["last_updated_at"])

        cls.all_keys = {
            cls.stale.translation_key,
            cls.fresh.translation_key,
            cls.errored.translation_key,
            cls.disabled.translation_key,
            cls.no_translation.translation_key,
            cls.drifted.translation_key,
        }

    def test_source_has_at_least_one_segment(self):
        # Guards the test's own assumption: a title-only page yields a segment,
        # otherwise "stale" could never be reproduced.
        source = TranslationSource.objects.get(object_id=self.stale.translation_key)
        self.assertGreater(StringSegment.objects.filter(source=source).count(), 0)

    def test_stale_translation_flagged(self):
        pairs = outdated_pairs(self.all_keys)
        self.assertIn((self.stale.translation_key, self.en.id), pairs)

    def test_fully_translated_not_flagged(self):
        pairs = outdated_pairs(self.all_keys)
        self.assertNotIn((self.fresh.translation_key, self.en.id), pairs)

    def test_drifted_source_flagged_even_when_fully_translated(self):
        # Source revised after the snapshot → out of date despite every
        # segment in the stale snapshot being translated.
        pairs = outdated_pairs(self.all_keys)
        self.assertIn((self.drifted.translation_key, self.en.id), pairs)

    def test_no_drift_when_snapshot_newer_than_revision(self):
        # Refreshing the snapshot (last_updated_at >= latest_revision_created_at)
        # clears the drift flag — the state right after the publish hook runs.
        source = TranslationSource.objects.get(
            object_id=self.drifted.translation_key
        )
        source.last_updated_at = self.drifted.latest_revision_created_at + timedelta(
            minutes=5
        )
        source.save(update_fields=["last_updated_at"])
        pairs = outdated_pairs(self.all_keys)
        self.assertNotIn((self.drifted.translation_key, self.en.id), pairs)

    def test_errored_translation_counts_as_stale(self):
        pairs = outdated_pairs(self.all_keys)
        self.assertIn((self.errored.translation_key, self.en.id), pairs)

    def test_disabled_translation_excluded(self):
        pairs = outdated_pairs(self.all_keys)
        self.assertNotIn((self.disabled.translation_key, self.en.id), pairs)

    def test_page_without_translation_not_flagged(self):
        pairs = outdated_pairs(self.all_keys)
        self.assertNotIn((self.no_translation.translation_key, self.en.id), pairs)

    def test_empty_keys_short_circuits(self):
        self.assertEqual(outdated_pairs(set()), set())

    def test_sync_source_ids_only_sources_with_enabled_translations(self):
        ids = sync_source_ids(self.all_keys, self.de.id)
        # enabled translations (translated or not) → sync is meaningful
        self.assertIn(self.stale.translation_key, ids)
        self.assertIn(self.fresh.translation_key, ids)
        # disabled translation / source with no Translation row → excluded
        self.assertNotIn(self.disabled.translation_key, ids)
        self.assertNotIn(self.no_translation.translation_key, ids)
        # values are the TranslationSource ids
        src = TranslationSource.objects.get(object_id=self.stale.translation_key)
        self.assertEqual(ids[self.stale.translation_key], src.id)

    def test_query_failure_degrades_to_no_flags(self):
        keys = self.all_keys
        with mock.patch.object(
            Translation.objects, "filter", side_effect=RuntimeError("db down")
        ), self.assertLogs("wagtail_pagetree", level="ERROR"):
            self.assertEqual(outdated_pairs(keys), set())
        with mock.patch.object(
            TranslationSource.objects, "filter", side_effect=RuntimeError("db down")
        ), self.assertLogs("wagtail_pagetree", level="ERROR"):
            self.assertEqual(sync_source_ids(keys, self.de.id), {})

    def test_sync_source_ids_empty_keys(self):
        self.assertEqual(sync_source_ids(set(), self.de.id), {})


class OutdatedPresenterTest(TestCase):
    """The stale flag surfaces on the right tree cells (and only those)."""

    @classmethod
    def setUpTestData(cls):
        cls.de = Locale.objects.get_or_create(language_code="de")[0]
        cls.en = Locale.objects.get_or_create(language_code="en")[0]
        root = Page.objects.filter(depth=1).first() or Page.add_root(
            title="Root", slug="root-p", locale=cls.de
        )

        # Published DE source with a published EN translation → "published"
        # cell that should carry the stale flag.
        cls.live_de = root.add_child(
            instance=Page(title="Live source", slug="live-de", locale=cls.de, live=True)
        )
        cls.live_en = root.add_child(
            instance=Page(
                title="Live source (EN)",
                slug="live-en",
                locale=cls.en,
                translation_key=cls.live_de.translation_key,
                live=True,
            )
        )
        _make_translation(cls.live_de, cls.en)  # stale

        # DE source whose EN translation is a draft (not live) → "draft" cell.
        # Even though the translation is stale, the flag must be suppressed.
        cls.draft_de = root.add_child(
            instance=Page(title="Draft source", slug="draft-de", locale=cls.de, live=True)
        )
        cls.draft_en = root.add_child(
            instance=Page(
                title="Draft source (EN)",
                slug="draft-en",
                locale=cls.en,
                translation_key=cls.draft_de.translation_key,
                live=False,
            )
        )
        _make_translation(cls.draft_de, cls.en)  # stale, but draft cell

        cls.superuser = User.objects.create_superuser(
            username="pt-outdated-super", email="o@example.invalid", password="x"
        )

    def _payload(self):
        request = _request(self.superuser)
        return build_tree_payload(
            primary_locale=self.de,
            all_locales=list(Locale.objects.all()),
            permitted=permitted_ids(request),
            placeholder=placeholder_ids(request),
        )

    def _node(self, payload, title):
        return next(p for p in payload["pages"] if p.get("title") == title)

    def test_published_stale_cell_flagged(self):
        node = self._node(self._payload(), "Live source")
        cell = node["translations"]["en"]
        self.assertEqual(cell["status"], "published")
        self.assertTrue(cell.get("outdated"))
        # Signal only — no dedicated action URL. "Edit" is the update
        # affordance (wagtail-localize serves the segment editor there).
        self.assertNotIn("update_translation_url", cell)

    def test_primary_source_cell_never_flagged(self):
        node = self._node(self._payload(), "Live source")
        de_cell = node["translations"]["de"]
        self.assertNotIn("outdated", de_cell)

    def test_draft_cell_not_flagged_even_when_stale(self):
        node = self._node(self._payload(), "Draft source")
        en_cell = node["translations"]["en"]
        self.assertEqual(en_cell["status"], "draft")
        self.assertNotIn("outdated", en_cell)


class SourceActionsPresenterTest(TestCase):
    """Sync / Translate links on the primary (DE) cell's dot menu.

    "Sync translated pages" appears on the source cell when the page is a
    source with enabled translations; "Translate this page" appears when a
    locale has no translation yet. Both are gated on ``can_submit_translation``
    and never appear on a target (EN) cell.
    """

    @classmethod
    def setUpTestData(cls):
        cls.de = Locale.objects.get_or_create(language_code="de")[0]
        cls.en = Locale.objects.get_or_create(language_code="en")[0]
        root = Page.objects.filter(depth=1).first() or Page.add_root(
            title="Root", slug="root-sa", locale=cls.de
        )

        # Translated: DE source with a real EN page + an enabled Translation.
        cls.synced_de = root.add_child(
            instance=Page(title="Synced src", slug="sa-synced-de", locale=cls.de, live=True)
        )
        root.add_child(
            instance=Page(
                title="Synced src EN", slug="sa-synced-en", locale=cls.en,
                translation_key=cls.synced_de.translation_key, live=True,
            )
        )
        _make_translation(cls.synced_de, cls.en, translate=True)

        # Untranslated: DE source, no EN page at all.
        cls.untranslated_de = root.add_child(
            instance=Page(title="Untrans src", slug="sa-untrans-de", locale=cls.de, live=True)
        )

        cls.superuser = User.objects.create_superuser(
            username="pt-sa-super", email="sa@example.invalid", password="x"
        )

    def _payload(self, can_submit_translation=True):
        request = _request(self.superuser)
        return build_tree_payload(
            primary_locale=self.de,
            all_locales=list(Locale.objects.all()),
            permitted=permitted_ids(request),
            placeholder=placeholder_ids(request),
            can_submit_translation=can_submit_translation,
        )

    def _node(self, payload, title):
        return next(p for p in payload["pages"] if p.get("title") == title)

    def test_synced_source_de_cell_has_sync_not_translate(self):
        de_cell = self._node(self._payload(), "Synced src")["translations"]["de"]
        self.assertIn("sync_translations_url", de_cell)
        self.assertNotIn("translate_page_url", de_cell)  # EN already exists

    def test_synced_target_en_cell_has_neither(self):
        en_cell = self._node(self._payload(), "Synced src")["translations"]["en"]
        self.assertNotIn("sync_translations_url", en_cell)
        self.assertNotIn("translate_page_url", en_cell)

    def test_untranslated_source_de_cell_has_translate_not_sync(self):
        de_cell = self._node(self._payload(), "Untrans src")["translations"]["de"]
        self.assertIn("translate_page_url", de_cell)
        self.assertNotIn("sync_translations_url", de_cell)  # no enabled translation

    def test_links_gated_on_permission(self):
        payload = self._payload(can_submit_translation=False)
        synced = self._node(payload, "Synced src")["translations"]["de"]
        untrans = self._node(payload, "Untrans src")["translations"]["de"]
        self.assertNotIn("sync_translations_url", synced)
        self.assertNotIn("translate_page_url", untrans)


@override_settings(ALLOWED_HOSTS=["*"])
@override_settings(ALLOWED_HOSTS=["*"])
class FilterAPITest(TestCase):
    """``?filter_locale=&filter_status=`` — the locale×status tree filter.

    DE-primary tree; each DE page gets an EN translation in a distinct state,
    so a status filter on EN isolates exactly one page.
    """

    @classmethod
    def setUpTestData(cls):
        cls.de = Locale.objects.get_or_create(language_code="de")[0]
        cls.en = Locale.objects.get_or_create(language_code="en")[0]
        root = Page.objects.filter(depth=1).first() or Page.add_root(
            title="Root", slug="root-f", locale=cls.de
        )

        def de(title, slug, **kw):
            return root.add_child(
                instance=Page(title=title, slug=slug, locale=cls.de, live=True, **kw)
            )

        def en(de_page, title, slug, **kw):
            return root.add_child(
                instance=Page(
                    title=title,
                    slug=slug,
                    locale=cls.en,
                    translation_key=de_page.translation_key,
                    **kw,
                )
            )

        # EN published
        cls.pub_de = de("FPub", "f-pub-de")
        en(cls.pub_de, "FPub EN", "f-pub-en", live=True)
        # EN draft
        cls.draft_de = de("FDraft", "f-draft-de")
        en(cls.draft_de, "FDraft EN", "f-draft-en", live=False)
        # EN changed (live + pending edits)
        cls.changed_de = de("FChanged", "f-changed-de")
        en(cls.changed_de, "FChanged EN", "f-changed-en", live=True,
           has_unpublished_changes=True)
        # EN missing (no translation at all)
        cls.missing_de = de("FMissing", "f-missing-de")
        # EN published *and* outdated
        cls.stale_de = de("FStale", "f-stale-de")
        en(cls.stale_de, "FStale EN", "f-stale-en", live=True)
        _make_translation(cls.stale_de, cls.en)  # stale
        # DE-side changed page — exercises the same-locale (target==primary) path
        cls.de_changed = de("FDeChanged", "f-dechanged-de", has_unpublished_changes=True)

        cls.superuser = User.objects.create_superuser(
            username="pt-filter-api", email="f@example.invalid", password="x"
        )

    def setUp(self):
        self.client.force_login(self.superuser)

    def _titles(self, qs):
        r = self.client.get(
            f"{reverse('pagetree:api-tree')}?{qs}", SERVER_NAME="127.0.0.1"
        )
        self.assertEqual(r.status_code, 200, r.content)
        return {m["title"] for m in r.json()["matches"]}

    def _error(self, qs):
        r = self.client.get(
            f"{reverse('pagetree:api-tree')}?{qs}", SERVER_NAME="127.0.0.1"
        )
        self.assertEqual(r.status_code, 400, r.content)
        return r.json()["error"]["code"]

    def test_en_draft_isolates_draft_page(self):
        titles = self._titles("locale=de&filter_locale=en&filter_status=draft")
        self.assertEqual(titles, {"FDraft"})

    def test_en_changed_isolates_changed_page(self):
        titles = self._titles("locale=de&filter_locale=en&filter_status=changed")
        self.assertEqual(titles, {"FChanged"})

    def test_en_missing_includes_untranslated_excludes_translated(self):
        # "Missing" = DE pages with no EN translation. FMissing qualifies;
        # any DE page that *does* have an EN cell must be excluded.
        titles = self._titles("locale=de&filter_locale=en&filter_status=empty")
        self.assertIn("FMissing", titles)
        for translated in ("FPub", "FDraft", "FChanged", "FStale"):
            self.assertNotIn(translated, titles)

    def test_en_outdated_isolates_stale_page(self):
        titles = self._titles("locale=de&filter_locale=en&filter_status=outdated")
        self.assertEqual(titles, {"FStale"})

    def test_en_published_includes_published_excludes_others(self):
        # FStale is published *and* outdated → still matches "published".
        titles = self._titles("locale=de&filter_locale=en&filter_status=published")
        self.assertIn("FPub", titles)
        self.assertIn("FStale", titles)
        self.assertNotIn("FDraft", titles)
        self.assertNotIn("FMissing", titles)

    def test_same_locale_changed_filters_primary_rows(self):
        # filter_locale == primary → filter on the DE row's own status.
        titles = self._titles("locale=de&filter_locale=de&filter_status=changed")
        self.assertEqual(titles, {"FDeChanged"})

    def test_missing_one_param_returns_400(self):
        self.assertEqual(self._error("locale=de&filter_status=draft"), "invalid_filter")
        self.assertEqual(self._error("locale=de&filter_locale=en"), "invalid_filter")

    def test_invalid_status_returns_400(self):
        self.assertEqual(
            self._error("locale=de&filter_locale=en&filter_status=bogus"),
            "invalid_filter_status",
        )

    def test_invalid_filter_locale_returns_400(self):
        self.assertEqual(
            self._error("locale=de&filter_locale=zz&filter_status=draft"),
            "invalid_locale",
        )


@override_settings(ALLOWED_HOSTS=["*"])
class DivergedFilterTest(TestCase):
    """Diverged filter matches the right rows AND the rendered cell shows it.

    Regression guard: ``build_search_payload`` builds its matrix from only the
    sparse match set, so without a DB-backed parent lookup the EN cell's
    ``aligned`` came back True and the diverged ↗ ring never rendered in
    filtered results — even though the rows were correctly matched.
    """

    @classmethod
    def setUpTestData(cls):
        cls.de = Locale.objects.get_or_create(language_code="de")[0]
        cls.en = Locale.objects.get_or_create(language_code="en")[0]
        root = Page.objects.filter(depth=1).first() or Page.add_root(
            title="Root", slug="root-d", locale=cls.de
        )

        # DE "Sessions" with its EN translation; plus an unrelated EN "Courses".
        sessions_de = root.add_child(
            instance=Page(title="DSessions", slug="d-sessions", locale=cls.de, live=True)
        )
        sessions_en = root.add_child(
            instance=Page(
                title="DSessions EN", slug="d-sessions-en", locale=cls.en,
                translation_key=sessions_de.translation_key, live=True,
            )
        )
        # "Courses" is a separate *translated* section (own translation_key,
        # distinct from Sessions) — e.g. a Sessions/Courses split.
        courses_de = root.add_child(
            instance=Page(title="DCourses", slug="d-courses-de", locale=cls.de, live=True)
        )
        courses_en = root.add_child(
            instance=Page(
                title="DCourses EN", slug="d-courses-en", locale=cls.en,
                translation_key=courses_de.translation_key, live=True,
            )
        )

        # Diverged: DE under Sessions, but its EN translation under Courses.
        cls.diverged_de = sessions_de.add_child(
            instance=Page(title="DivItem", slug="d-divitem", locale=cls.de, live=True)
        )
        courses_en.add_child(
            instance=Page(
                title="DivItem EN", slug="d-divitem-en", locale=cls.en,
                translation_key=cls.diverged_de.translation_key, live=True,
            )
        )

        # Aligned control: DE under Sessions, EN under Sessions-EN.
        cls.aligned_de = sessions_de.add_child(
            instance=Page(title="AlignedItem", slug="d-aligned", locale=cls.de, live=True)
        )
        sessions_en.add_child(
            instance=Page(
                title="AlignedItem EN", slug="d-aligned-en", locale=cls.en,
                translation_key=cls.aligned_de.translation_key, live=True,
            )
        )

        cls.superuser = User.objects.create_superuser(
            username="pt-div", email="d@example.invalid", password="x"
        )

    def setUp(self):
        self.client.force_login(self.superuser)

    def _matches(self):
        r = self.client.get(
            reverse("pagetree:api-tree")
            + "?locale=de&filter_locale=en&filter_status=diverged",
            SERVER_NAME="127.0.0.1",
        )
        self.assertEqual(r.status_code, 200, r.content)
        return {m["title"]: m for m in r.json()["matches"]}

    def test_diverged_page_matched_aligned_page_not(self):
        by_title = self._matches()
        self.assertIn("DivItem", by_title)
        self.assertNotIn("AlignedItem", by_title)

    def test_matched_cell_renders_aligned_false(self):
        # The fix: the rendered EN cell must carry aligned=False so the dot
        # shows the diverged ring.
        en_cell = self._matches()["DivItem"]["translations"]["en"]
        self.assertFalse(en_cell["aligned"])

    def test_matched_cell_carries_diverged_parent_titles(self):
        # Tooltip data: EN sits under "DCourses EN", expected under "DSessions".
        en_cell = self._matches()["DivItem"]["translations"]["en"]
        self.assertEqual(en_cell["diverged_from"], "DCourses EN")
        self.assertEqual(en_cell["diverged_expected"], "DSessions")
