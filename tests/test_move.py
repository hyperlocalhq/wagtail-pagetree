"""``apply_move`` — guards, permission gate and translation cascade."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from wagtail.models import GroupPagePermission, Page

from wagtail_pagetree.services.move import (
    MoveDenied,
    MoveInvalid,
    MoveNotFound,
    apply_move,
)

from .test_security_integration import _TreeBuilderMixin, _grant_admin, _make_user

User = get_user_model()


def _parent_id(page):
    # Fresh query — treebeard caches get_parent() on the instance.
    return Page.objects.get(id=page.id).get_parent().id


class MoveGuardTest(_TreeBuilderMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._build_tree()
        cls.superuser = User.objects.create_superuser(
            username="pt-move-svc", email="m@example.invalid", password="x"
        )

    def _move(self, page, target, position, **kwargs):
        return apply_move(
            user=self.superuser,
            page_id=page if isinstance(page, int) else page.id,
            target_id=target if isinstance(target, int) else target.id,
            position=position,
            **kwargs,
        )

    def test_unknown_position_is_invalid(self):
        with self.assertRaises(MoveInvalid):
            self._move(self.article_a_de, self.article_b_de, "diagonally")

    def test_unknown_page_is_not_found(self):
        with self.assertRaises(MoveNotFound):
            self._move(999999, self.article_b_de, "after")

    def test_unknown_target_is_not_found(self):
        with self.assertRaises(MoveNotFound):
            self._move(self.article_a_de, 999999, "after")

    def test_root_cannot_move(self):
        with self.assertRaises(MoveInvalid):
            self._move(self.root, self.home_de, "inside")

    def test_page_cannot_drop_onto_itself(self):
        with self.assertRaises(MoveInvalid):
            self._move(self.article_a_de, self.article_a_de, "after")

    def test_cannot_reorder_next_to_root(self):
        with self.assertRaises(MoveInvalid):
            self._move(self.article_a_de, self.root, "before")

    def test_redrop_as_last_child_is_noop(self):
        result = self._move(self.article_b_de, self.magazin_de, "inside")
        self.assertTrue(result["noop"])
        self.assertEqual(result["cascade"], [])

    def test_user_without_move_permission_is_denied(self):
        group = Group.objects.create(name="pt-move-readonly")
        _grant_admin(group)
        GroupPagePermission.objects.create(
            group=group, page=self.article_a_de, permission_type="change"
        )
        editor = _make_user("pt-move-readonly", group)
        with self.assertRaises(MoveDenied):
            apply_move(
                user=editor,
                page_id=self.article_a_de.id,
                target_id=self.home_de.id,
                position="inside",
            )

    def test_validation_error_becomes_invalid(self):
        with (
            mock.patch.object(
                Page, "move", side_effect=ValidationError("slug already in use")
            ),
            self.assertRaisesMessage(MoveInvalid, "slug already in use"),
        ):
            self._move(self.article_a_de, self.home_de, "inside")

    def test_unexpected_error_becomes_invalid_and_is_logged(self):
        with (
            mock.patch.object(Page, "move", side_effect=RuntimeError("boom")),
            self.assertLogs("wagtail_pagetree.move", level="ERROR"),
            self.assertRaisesMessage(MoveInvalid, "boom"),
        ):
            self._move(self.article_a_de, self.home_de, "inside")

    # ── cascade ────────────────────────────────────────────────

    def test_page_without_translations_has_empty_cascade(self):
        result = self._move(self.article_b_de, self.home_de, "inside")
        self.assertFalse(result["noop"])
        self.assertEqual(result["cascade"], [])
        self.assertEqual(_parent_id(self.article_b_de), self.home_de.id)

    def test_sibling_reorder_cascades(self):
        # Give Article B an EN translation next to Article A EN, then swap.
        article_b_en = self.magazin_en.add_child(
            instance=Page(
                title="Article B (EN)",
                slug="article-b-en",
                locale=self.en,
                translation_key=self.article_b_de.translation_key,
            )
        )
        result = self._move(self.article_a_de, self.article_b_de, "after")

        self.assertEqual(
            result["cascade"],
            [{"locale_code": "en", "page_id": self.article_a_en.id, "status": "moved"}],
        )
        en_order = list(
            Page.objects.get(id=self.magazin_en.id)
            .get_children()
            .values_list("id", flat=True)
        )
        self.assertEqual(en_order, [article_b_en.id, self.article_a_en.id])

    def test_cascade_skips_when_target_has_no_translation(self):
        # Article B has no EN translation → nothing to position Article A EN against.
        result = self._move(self.article_a_de, self.article_b_de, "before")
        self.assertEqual(result["cascade"][0]["status"], "skipped_no_target")

    def test_cascade_skips_when_new_parent_has_no_translation(self):
        result = self._move(self.article_a_de, self.article_b_de, "inside")
        self.assertEqual(result["cascade"][0]["status"], "skipped_no_target")
        self.assertEqual(_parent_id(self.article_a_en), self.magazin_en.id)

    def test_cascade_skips_diverged_target(self):
        # Article B EN exists, but under Home EN instead of Magazin EN.
        self.home_en.add_child(
            instance=Page(
                title="Article B (EN, misplaced)",
                slug="article-b-en",
                locale=self.en,
                translation_key=self.article_b_de.translation_key,
            )
        )
        result = self._move(self.article_a_de, self.article_b_de, "after")
        self.assertEqual(result["cascade"][0]["status"], "skipped_diverged_target")

    def test_cascade_noop_when_translation_already_in_place(self):
        # Move DE under Home; EN translation is already Home EN's last child.
        self.article_a_en.move(self.home_en, pos="last-child")
        result = self._move(self.article_a_de, self.home_de, "inside")
        self.assertEqual(
            result["cascade"],
            [
                {
                    "locale_code": "en",
                    "page_id": self.article_a_en.id,
                    "status": "moved",
                    "noop": True,
                }
            ],
        )

    def test_cascade_denied_per_translation(self):
        group = Group.objects.create(name="pt-move-de-tree")
        _grant_admin(group)
        for perm in ("add", "change", "publish"):
            GroupPagePermission.objects.create(
                group=group, page=self.home_de, permission_type=perm
            )
        editor = _make_user("pt-move-de-tree", group)

        result = apply_move(
            user=editor,
            page_id=self.article_a_de.id,
            target_id=self.home_de.id,
            position="inside",
        )

        self.assertEqual(result["cascade"][0]["status"], "denied")
        self.assertEqual(_parent_id(self.article_a_de), self.home_de.id)
        self.assertEqual(_parent_id(self.article_a_en), self.magazin_en.id)

    def test_cascade_records_translation_errors_without_raising(self):
        real_move = Page.move

        def move_primary_only(page, *args, **kwargs):
            if page.locale_id == self.en.id:
                raise ValidationError("slug clash")
            return real_move(page, *args, **kwargs)

        with mock.patch.object(Page, "move", move_primary_only):
            result = self._move(self.article_a_de, self.home_de, "inside")
        self.assertEqual(result["cascade"][0]["status"], "errored")

        def explode_on_translation(page, *args, **kwargs):
            if page.locale_id == self.en.id:
                raise RuntimeError("boom")
            return real_move(page, *args, **kwargs)

        with (
            mock.patch.object(Page, "move", explode_on_translation),
            self.assertLogs("wagtail_pagetree.move", level="ERROR"),
        ):
            result = self._move(self.article_a_de, self.magazin_de, "before")
        self.assertEqual(result["cascade"][0]["status"], "errored")
