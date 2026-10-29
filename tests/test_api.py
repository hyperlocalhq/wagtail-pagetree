"""HTTP surface: the admin page, the JS catalog and the JSON API error paths."""

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from wagtail.models import GroupPagePermission, Page

from wagtail_pagetree.services.permissions import (
    editable_ids,
    permitted_ids,
    placeholder_ids,
)

from .test_security_integration import (
    _TreeBuilderMixin,
    _grant_admin,
    _make_request,
    _make_user,
)

User = get_user_model()


class _SuperuserClientMixin(_TreeBuilderMixin):
    @classmethod
    def setUpTestData(cls):
        cls._build_tree()
        cls.superuser = User.objects.create_superuser(
            username="pt-api-super", email="a@example.invalid", password="x"
        )

    def setUp(self):
        self.client.force_login(self.superuser)

    def _get(self, name, qs="", **kwargs):
        return self.client.get(f"{reverse(name, kwargs=kwargs)}?{qs}")

    def _post(self, name, body):
        data = body if isinstance(body, str) else json.dumps(body)
        return self.client.post(
            reverse(name), data=data, content_type="application/json"
        )

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response.json()["error"]["code"], code)
        self.assertIn("no-store", response["Cache-Control"])


class AdminPageTest(_SuperuserClientMixin, TestCase):
    def test_index_renders_mount_point_and_assets(self):
        response = self._get("pagetree:index")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="pagetree-root"')
        self.assertContains(response, reverse("pagetree:jsi18n"))
        self.assertContains(response, "wagtail_pagetree/js/bundle.js")

    def test_index_requires_admin_access(self):
        self.client.logout()
        response = self._get("pagetree:index")
        self.assertEqual(response.status_code, 302)

    def test_js_catalog_serves_german_strings(self):
        response = self.client.get(
            reverse("pagetree:jsi18n"), HTTP_ACCEPT_LANGUAGE="de"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Seitenbaum")


class RootHiddenTest(_SuperuserClientMixin, TestCase):
    """Wagtail's tree root never shows up; the homepages are top level."""

    def test_tree_starts_below_the_root(self):
        pages = self._get("pagetree:api-tree", "locale=de").json()["pages"]
        ids = {page["id"] for page in pages}
        self.assertNotIn(self.root.id, ids)
        home = next(page for page in pages if page["id"] == self.home_de.id)
        self.assertIsNone(home["parent_id"])

    def test_root_is_not_an_orphan_of_another_locale(self):
        orphans = self._get("pagetree:api-tree", "locale=en").json()["orphans"]
        self.assertNotIn(self.root.id, {orphan["id"] for orphan in orphans})

    def test_search_never_matches_the_root(self):
        body = self._get(
            "pagetree:api-tree", f"locale={self.root.locale.language_code}"
            f"&search={self.root.title}"
        ).json()
        self.assertNotIn(self.root.id, {page["id"] for page in body["matches"]})

    def test_superuser_gets_add_top_level_button(self):
        response = self._get("pagetree:index")
        self.assertContains(response, self._add_top_level_url())
        self.assertContains(response, "Seite auf oberster Ebene hinzufügen")

    def test_editor_without_root_permission_gets_no_button(self):
        group = Group.objects.create(name="pt-api-no-root")
        _grant_admin(group)
        GroupPagePermission.objects.create(
            group=group, page=self.home_de, permission_type="add"
        )
        self.client.force_login(_make_user("pt-api-no-root", group))
        response = self._get("pagetree:index")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self._add_top_level_url())

    def _add_top_level_url(self):
        return reverse("wagtailadmin_pages:add_subpage", args=[self.root.id])


class TreeAPIErrorTest(_SuperuserClientMixin, TestCase):
    def test_search_too_long(self):
        response = self._get("pagetree:api-tree", "search=" + "x" * 201)
        self.assertError(response, 400, "search_too_long")

    def test_search_too_broad(self):
        with mock.patch("wagtail_pagetree.services.search.ANCESTOR_EXPANSION_CAP", 2):
            response = self._get("pagetree:api-tree", "search=Article")
        self.assertError(response, 400, "search_too_broad")

    def test_filter_requires_both_params(self):
        response = self._get("pagetree:api-tree", "filter_status=draft")
        self.assertError(response, 400, "invalid_filter")

    def test_filter_rejects_unknown_status(self):
        response = self._get(
            "pagetree:api-tree", "filter_status=bogus&filter_locale=en"
        )
        self.assertError(response, 400, "invalid_filter_status")

    def test_filter_rejects_unknown_locale(self):
        response = self._get(
            "pagetree:api-tree", "filter_status=draft&filter_locale=zz"
        )
        self.assertError(response, 400, "invalid_locale")


class ChildrenAPITest(_SuperuserClientMixin, TestCase):
    def test_lists_direct_children_with_translation_cells(self):
        response = self._get(
            "pagetree:api-children", "locale=de", page_id=self.magazin_de.id
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["parent_id"], self.magazin_de.id)
        self.assertEqual(body["primary_locale"], "de")
        self.assertEqual({loc["code"] for loc in body["locales"]}, {"de", "en"})
        self.assertEqual(
            [page["title"] for page in body["pages"]], ["Article A", "Article B"]
        )
        article_a, article_b = body["pages"]
        self.assertEqual(
            article_a["translations"]["en"]["page_id"], self.article_a_en.id
        )
        self.assertEqual(article_b["translations"]["en"]["status"], "empty")

    def test_alias_translation_offers_conversion(self):
        alias = self.article_b_de.create_alias(
            recursive=False,
            parent=self.magazin_en,
            update_locale=self.en,
            reset_translation_key=False,
        )
        response = self._get(
            "pagetree:api-children", "locale=de", page_id=self.magazin_de.id
        )
        cell = response.json()["pages"][1]["translations"]["en"]
        self.assertEqual(cell["status"], "alias")
        self.assertEqual(cell["page_id"], alias.id)
        self.assertIn("convert_alias_url", cell)

    def test_invalid_locale(self):
        response = self._get(
            "pagetree:api-children", "locale=zz", page_id=self.magazin_de.id
        )
        self.assertError(response, 400, "invalid_locale")

    def test_unknown_page_is_indistinguishable_from_denied(self):
        response = self._get("pagetree:api-children", "locale=de", page_id=999999)
        self.assertError(response, 403, "not_found_or_denied")

    def test_page_outside_primary_locale_is_not_found(self):
        response = self._get(
            "pagetree:api-children", "locale=de", page_id=self.magazin_en.id
        )
        self.assertError(response, 404, "not_found")

    def test_restricted_user_cannot_list_children_of_unpermitted_page(self):
        group = Group.objects.create(name="pt-children-restricted")
        _grant_admin(group)
        GroupPagePermission.objects.create(
            group=group, page=self.article_b_de, permission_type="change"
        )
        self.client.force_login(_make_user("pt-children-restricted", group))

        response = self._get(
            "pagetree:api-children", "locale=en", page_id=self.home_en.id
        )
        self.assertError(response, 403, "not_found_or_denied")

        # Navigation ancestor of a permitted page: children are listed, but
        # only the permitted branch.
        response = self._get(
            "pagetree:api-children", "locale=de", page_id=self.magazin_de.id
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [page["title"] for page in response.json()["pages"]], ["Article B"]
        )


class BulkAPIErrorTest(_SuperuserClientMixin, TestCase):
    def test_invalid_json(self):
        response = self._post("pagetree:api-bulk", "{nope")
        self.assertError(response, 400, "invalid_json")

    def test_non_integer_page_ids(self):
        response = self._post(
            "pagetree:api-bulk", {"action": "publish", "page_ids": ["one"]}
        )
        self.assertError(response, 400, "invalid_page_ids")

    def test_unknown_locale_code(self):
        response = self._post(
            "pagetree:api-bulk",
            {
                "action": "unpublish",
                "page_ids": [self.article_a_de.id],
                "locale_code": "zz",
            },
        )
        self.assertError(response, 400, "invalid_locale")

    def test_locale_code_targets_translation(self):
        response = self._post(
            "pagetree:api-bulk",
            {
                "action": "unpublish",
                "page_ids": [self.article_a_de.id],
                "locale_code": "en",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["locale_code"], "en")
        self.assertEqual(body["success"], [self.article_a_en.id])


class MoveAPIErrorTest(_SuperuserClientMixin, TestCase):
    def _move(self, **body):
        body.setdefault("page_id", self.article_a_de.id)
        body.setdefault("target_id", self.home_de.id)
        body.setdefault("position", "inside")
        return self._post("pagetree:api-move", body)

    def test_invalid_json(self):
        response = self._post("pagetree:api-move", "{nope")
        self.assertError(response, 400, "invalid_json")

    def test_cascade_flag_must_be_boolean(self):
        response = self._move(cascade_translations="yes")
        self.assertError(response, 400, "invalid_cascade")

    def test_unknown_target_is_404(self):
        response = self._move(target_id=999999)
        self.assertError(response, 404, "not_found")

    def test_wagtail_move_denial_is_403(self):
        group = Group.objects.create(name="pt-move-api-leaf")
        _grant_admin(group)
        GroupPagePermission.objects.create(
            group=group, page=self.article_a_de, permission_type="change"
        )
        self.client.force_login(_make_user("pt-move-api-leaf", group))
        response = self._move()
        self.assertError(response, 403, "denied")

    def test_root_move_is_rejected(self):
        response = self._move(page_id=self.root.id)
        self.assertError(response, 400, "invalid")


class PermissionSetTest(_TreeBuilderMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls._build_tree()
        group = Group.objects.create(name="pt-perm-none")
        _grant_admin(group)
        cls.nobody = _make_user("pt-perm-none", group)

    def test_user_without_page_permissions_sees_nothing(self):
        request = _make_request(self.nobody)
        self.assertEqual(permitted_ids(request), set())
        self.assertEqual(editable_ids(request), set())
        self.assertEqual(placeholder_ids(request), set())

    def test_sets_are_cached_on_the_request(self):
        request = _make_request(self.nobody)
        first = (
            permitted_ids(request),
            editable_ids(request),
            placeholder_ids(request),
        )
        with self.assertNumQueries(0):
            again = (
                permitted_ids(request),
                editable_ids(request),
                placeholder_ids(request),
            )
        for a, b in zip(first, again):
            self.assertIs(a, b)
