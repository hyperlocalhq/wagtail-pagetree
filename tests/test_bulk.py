"""``apply_bulk_action`` — per-page outcomes of bulk publish / unpublish."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from wagtail.models import GroupPagePermission, Page

from wagtail_pagetree.services.bulk import apply_bulk_action

from .test_security_integration import _TreeBuilderMixin, _grant_admin, _make_user

User = get_user_model()


class BulkServiceTest(_TreeBuilderMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._build_tree()
        cls.superuser = User.objects.create_superuser(
            username="pt-bulk-svc", email="b@example.invalid", password="x"
        )
        cls.all_ids = set(Page.objects.values_list("id", flat=True))

    def _apply(self, action, page_ids, **kwargs):
        kwargs.setdefault("user", self.superuser)
        kwargs.setdefault("permitted", self.all_ids)
        return apply_bulk_action(action=action, page_ids=page_ids, **kwargs)

    def test_unsupported_action_raises(self):
        with self.assertRaises(ValueError):
            self._apply("explode", [self.article_a_de.id])

    def test_publish_latest_revision(self):
        page = Page.objects.get(id=self.article_b_de.id)
        page.title = "Article B v2"
        page.save_revision()

        summary = self._apply("publish", [page.id])

        self.assertEqual(summary["success"], [page.id])
        self.assertEqual(Page.objects.get(id=page.id).title, "Article B v2")

    def test_publish_without_revision_is_skipped(self):
        summary = self._apply("publish", [self.article_b_de.id])
        self.assertEqual(summary["skipped"], [self.article_b_de.id])

    def test_publish_alias_is_skipped(self):
        alias = self.article_b_de.create_alias(update_slug="article-b-alias")
        summary = self._apply("publish", [alias.id], permitted={alias.id})
        self.assertEqual(summary["skipped"], [alias.id])

    def test_unpublish_live_page(self):
        summary = self._apply("unpublish", [self.article_b_de.id])
        self.assertEqual(summary["success"], [self.article_b_de.id])
        self.assertFalse(Page.objects.get(id=self.article_b_de.id).live)

    def test_unpublish_draft_is_skipped(self):
        Page.objects.filter(id=self.article_b_de.id).update(live=False)
        summary = self._apply("unpublish", [self.article_b_de.id])
        self.assertEqual(summary["skipped"], [self.article_b_de.id])

    def test_unknown_page_is_skipped(self):
        summary = self._apply("unpublish", [999999])
        self.assertEqual(summary["skipped"], [999999])

    def test_page_outside_permitted_is_denied(self):
        summary = self._apply(
            "unpublish", [self.article_b_de.id], permitted={self.article_a_de.id}
        )
        self.assertEqual(summary["denied"], [self.article_b_de.id])
        self.assertTrue(Page.objects.get(id=self.article_b_de.id).live)

    def test_wagtail_permission_denial_is_denied_not_errored(self):
        # Change perm puts the page in the editable set, but Wagtail's own
        # UnpublishPageAction still refuses without publish perm.
        group = Group.objects.create(name="pt-bulk-change-only")
        _grant_admin(group)
        GroupPagePermission.objects.create(
            group=group, page=self.article_b_de, permission_type="change"
        )
        editor = _make_user("pt-bulk-change-only", group)

        summary = self._apply("unpublish", [self.article_b_de.id], user=editor)

        self.assertEqual(summary["denied"], [self.article_b_de.id])
        self.assertEqual(summary["errored"], [])

    def test_unexpected_failure_is_errored(self):
        page = Page.objects.get(id=self.article_b_de.id)
        page.save_revision()
        # A sibling already uses the slug the revision would publish.
        self.magazin_de.add_child(
            instance=Page(title="Clash", slug="article-b-clash", locale=self.de)
        )
        revision = page.get_latest_revision()
        revision.content["slug"] = "article-b-clash"
        revision.save()

        with self.assertLogs("wagtail_pagetree.bulk", level="ERROR"):
            summary = self._apply("publish", [page.id])

        self.assertEqual(summary["errored"], [page.id])

    # ── per-locale targeting ───────────────────────────────────

    def test_target_locale_acts_on_translation(self):
        summary = self._apply(
            "unpublish", [self.article_a_de.id], target_locale_id=self.en.id
        )
        self.assertEqual(summary["success"], [self.article_a_en.id])
        self.assertFalse(Page.objects.get(id=self.article_a_en.id).live)
        self.assertTrue(Page.objects.get(id=self.article_a_de.id).live)

    def test_target_locale_without_translation_is_skipped(self):
        summary = self._apply(
            "unpublish", [self.article_b_de.id], target_locale_id=self.en.id
        )
        self.assertEqual(summary["skipped"], [self.article_b_de.id])

    def test_target_locale_with_unknown_source_is_skipped(self):
        summary = self._apply("unpublish", [999999], target_locale_id=self.en.id)
        self.assertEqual(summary["skipped"], [999999])

    def test_target_locale_checks_permission_on_translation(self):
        summary = self._apply(
            "unpublish",
            [self.article_a_de.id],
            target_locale_id=self.en.id,
            permitted={self.article_a_de.id},
        )
        self.assertEqual(summary["denied"], [self.article_a_en.id])
