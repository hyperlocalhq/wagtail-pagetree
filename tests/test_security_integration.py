"""DB-backed integration tests for the permission redaction rules.

These tests build a real multi-locale Wagtail page tree, create restricted
users, and assert that ``build_tree_payload`` redacts the right fields.
The pure-Python unit tests in this directory cover the *logic*; this
suite covers the *integration* between presenters, permissions, and
Wagtail's own permission policies.

Run with:
    uv run pytest tests/test_security_integration.py
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse
from wagtail.models import GroupPagePermission, Locale, Page

from wagtail_pagetree.services.permissions import (
    permitted_ids,
    placeholder_ids,
)
from wagtail_pagetree.services.presenters import (
    build_tree_payload,
)

User = get_user_model()


PLACEHOLDER_ALLOWED_KEYS = {
    "id",
    "title",
    "depth",
    "parent_id",
    "visible_numchild",
    "is_placeholder",
}


def _grant_admin(group: Group) -> None:
    """Wagtail admin access permission (otherwise login bounces)."""
    perm = Permission.objects.get(
        content_type__app_label="wagtailadmin",
        codename="access_admin",
    )
    group.permissions.add(perm)


def _make_user(username: str, group: Group) -> object:
    user = User.objects.create_user(  # type: ignore[attr-defined]
        username=username,
        email=f"{username}@example.invalid",
        password="testpass1234!",
    )
    user.is_staff = True
    user.save()
    user.groups.add(group)
    return user


def _make_request(user) -> object:
    """Minimal request stub for permitted_ids/placeholder_ids."""
    from django.http import HttpRequest

    req = HttpRequest()
    req.user = user
    req.method = "GET"
    return req


class _TreeBuilderMixin:
    """Shared helpers to assemble a small multi-locale tree.

    Layout (DE primary, EN secondary):

        depth=1: Wagtail root (auto)
        depth=2: HomeDE (translation_key=K_HOME, locale=de)         | HomeEN
                 └─ MagazinDE (K_MAGAZIN)                            | MagazinEN
                    ├─ ArticleA_DE (K_A)                             | ArticleA_EN (translated, aligned)
                    └─ ArticleB_DE (K_B)                             | (no EN translation → empty)

        Plus an EN-only "orphan" outside any DE counterpart:
        depth=2: NewsEN (locale=en, translation_key=K_NEWS, no DE)
    """

    @classmethod
    def _build_tree(cls):
        cls.de = Locale.objects.get_or_create(language_code="de")[0]
        cls.en = Locale.objects.get_or_create(language_code="en")[0]

        # The treebeard root is created by Wagtail migrations. If the test
        # DB doesn't have one (rare), bootstrap it.
        root = Page.objects.filter(depth=1).first()
        if root is None:
            root = Page.add_root(title="Root", slug="root", locale=cls.de)
        cls.root = root

        # DE primary tree
        cls.home_de = root.add_child(
            instance=Page(title="Home", slug="home-de", locale=cls.de)
        )
        cls.magazin_de = cls.home_de.add_child(
            instance=Page(title="Magazin", slug="magazin-de", locale=cls.de)
        )
        cls.article_a_de = cls.magazin_de.add_child(
            instance=Page(title="Article A", slug="article-a-de", locale=cls.de)
        )
        cls.article_b_de = cls.magazin_de.add_child(
            instance=Page(title="Article B", slug="article-b-de", locale=cls.de)
        )

        # EN translations sharing translation_key with DE counterparts.
        # Wagtail-localize would normally create these via copy_for_translation;
        # we mimic the resulting Page rows.
        cls.home_en = root.add_child(
            instance=Page(
                title="Home (EN)",
                slug="home-en",
                locale=cls.en,
                translation_key=cls.home_de.translation_key,
            )
        )
        cls.magazin_en = cls.home_en.add_child(
            instance=Page(
                title="Magazin (EN)",
                slug="magazin-en",
                locale=cls.en,
                translation_key=cls.magazin_de.translation_key,
            )
        )
        cls.article_a_en = cls.magazin_en.add_child(
            instance=Page(
                title="Article A (EN)",
                slug="article-a-en",
                locale=cls.en,
                translation_key=cls.article_a_de.translation_key,
                live=True,
            )
        )
        # Note: no Article B EN translation → status="empty" in matrix.

        # EN-only orphan: News exists in EN with no DE counterpart (its own
        # translation_key, distinct from any DE page).
        cls.news_en = cls.home_en.add_child(
            instance=Page(title="News (EN orphan)", slug="news-en", locale=cls.en)
        )


class PermissionFilterTest(_TreeBuilderMixin, TestCase):
    """Restricted user with edit on Article B only."""

    @classmethod
    def setUpTestData(cls):
        cls._build_tree()

        cls.group = Group.objects.create(name="pagetree-restricted")
        _grant_admin(cls.group)
        GroupPagePermission.objects.create(
            group=cls.group, page=cls.article_b_de, permission_type="change"
        )
        cls.user = _make_user("pt-restricted", cls.group)

    def _payload(self):
        request = _make_request(self.user)
        permitted = permitted_ids(request)
        placeholder = placeholder_ids(request)
        return build_tree_payload(
            primary_locale=self.de,
            all_locales=list(Locale.objects.all()),
            permitted=permitted,
            placeholder=placeholder,
        )

    # ── placeholders expose minimal fields ──────────────────────

    def test_placeholder_rows_only_expose_allowed_keys(self):
        payload = self._payload()
        placeholders = [p for p in payload["pages"] if p.get("is_placeholder")]
        self.assertGreater(
            len(placeholders), 0, "expected at least one placeholder ancestor"
        )
        for p in placeholders:
            extra = set(p.keys()) - PLACEHOLDER_ALLOWED_KEYS
            self.assertEqual(
                extra,
                set(),
                f"placeholder leaked extra keys: {extra} on row {p}",
            )
            for forbidden in ("slug", "translation_key", "translations", "edit_url"):
                self.assertNotIn(forbidden, p)

    def test_permitted_page_rendered_in_full(self):
        payload = self._payload()
        editable = [
            p
            for p in payload["pages"]
            if not p.get("is_placeholder") and p["title"] == "Article B"
        ]
        self.assertEqual(len(editable), 1)
        row = editable[0]
        self.assertIn("edit_url", row)
        self.assertIn("translations", row)

    # ── denied translations are redacted ────────────────────────

    def test_translation_cell_for_denied_locale_redacts_ids(self):
        payload = self._payload()
        article_b = next(
            p
            for p in payload["pages"]
            if not p.get("is_placeholder") and p["title"] == "Article B"
        )
        # Article B has no EN translation in our fixture, so the cell is "empty";
        # but Article A does — and the user has no perm on either DE *or* EN
        # of Article A. So Article A doesn't appear at all (a placeholder
        # for the magazin path is enough).
        # For redaction we need: page where the user has DE perm but NOT EN perm.
        # That's Article B. Even though no EN exists, the cell shape must
        # still be redacted-safe: status='empty', no page_id, no edit_url.
        en_cell = article_b["translations"]["en"]
        self.assertEqual(en_cell["status"], "empty")
        self.assertNotIn("page_id", en_cell)
        self.assertNotIn("edit_url", en_cell)

    def test_translation_cell_for_permitted_locale_carries_edit_url(self):
        payload = self._payload()
        article_b = next(
            p
            for p in payload["pages"]
            if not p.get("is_placeholder") and p["title"] == "Article B"
        )
        de_cell = article_b["translations"]["de"]
        # The user has change perm on Article B DE → edit_url + page_id present.
        self.assertIn("page_id", de_cell)
        self.assertIn("edit_url", de_cell)
        self.assertEqual(de_cell["page_id"], self.article_b_de.id)

    # ── orphans use the editable set ────────────────────────────

    def test_orphan_section_excludes_pages_outside_permitted(self):
        payload = self._payload()
        orphan_ids = {o["id"] for o in payload["orphans"]}
        self.assertNotIn(
            self.news_en.id,
            orphan_ids,
            "News (EN orphan) leaked into orphan section "
            "even though the user has no permission on it",
        )


class OrphanNavigationAncestorRegressionTest(_TreeBuilderMixin, TestCase):
    """Regression for the alias/ancestor leak.

    Wagtail's ``explorable_instances`` unions in ``page.get_ancestors()`` for
    every permitted page so deep editors can navigate down. Those ancestors
    are explorable but not editable. ``fetch_orphans`` must filter by the
    *editable* set, not the broader ``permitted`` set, otherwise an EN
    ancestor of a permitted EN page would leak into "Pages without [DE]".
    """

    @classmethod
    def setUpTestData(cls):
        cls._build_tree()
        # Grant change perm on Article A *EN* only — its DE counterpart is
        # outside permitted. Magazin EN is its ancestor and will be folded
        # into explorable_instances by Wagtail. We must NOT see Magazin EN
        # in the orphan section (user can't edit it).
        cls.group = Group.objects.create(name="pagetree-en-leaf")
        _grant_admin(cls.group)
        GroupPagePermission.objects.create(
            group=cls.group, page=cls.article_a_en, permission_type="change"
        )
        cls.user = _make_user("pt-en-leaf", cls.group)

    def test_navigation_ancestors_do_not_leak_into_orphans(self):
        request = _make_request(self.user)
        payload = build_tree_payload(
            primary_locale=self.de,
            all_locales=list(Locale.objects.all()),
            permitted=permitted_ids(request),
            placeholder=placeholder_ids(request),
        )
        orphan_ids = {o["id"] for o in payload["orphans"]}

        # The actual orphan: Article A EN — user can edit it, no DE counterpart
        # in permitted, not in primary locale → legitimate orphan.
        self.assertIn(self.article_a_en.id, orphan_ids)

        # The leak we're guarding against: Magazin EN is an ancestor of
        # Article A EN. Wagtail's explorable_instances pulls it into the
        # permitted set so the user can navigate to Article A EN, but the
        # user has no edit perm on Magazin EN. It must NOT appear as an
        # orphan.
        self.assertNotIn(
            self.magazin_en.id,
            orphan_ids,
            "Regression: navigation-only ancestor (Magazin EN) leaked into "
            "orphan section. fetch_orphans must filter by editable_ids, "
            "not permitted_ids.",
        )
        # Likewise the EN home node.
        self.assertNotIn(self.home_en.id, orphan_ids)


class DeniedTranslationRedactionTest(_TreeBuilderMixin, TestCase):
    """Explicit fixture where user has DE perm but a real EN translation
    exists outside permitted set. Asserts the EN cell has *no* page_id/edit_url
    even though the translation is live in the DB.
    """

    @classmethod
    def setUpTestData(cls):
        cls._build_tree()
        # Permit the DE Article A only (its EN translation exists but is denied).
        cls.group = Group.objects.create(name="pagetree-de-only")
        _grant_admin(cls.group)
        GroupPagePermission.objects.create(
            group=cls.group, page=cls.article_a_de, permission_type="change"
        )
        cls.user = _make_user("pt-de-only", cls.group)

    def test_existing_en_translation_redacted_when_denied(self):
        request = _make_request(self.user)
        payload = build_tree_payload(
            primary_locale=self.de,
            all_locales=list(Locale.objects.all()),
            permitted=permitted_ids(request),
            placeholder=placeholder_ids(request),
        )
        article_a = next(
            p
            for p in payload["pages"]
            if not p.get("is_placeholder") and p["title"] == "Article A"
        )
        en_cell = article_a["translations"]["en"]
        # The EN page exists and is live in our fixture, but the user has no
        # perm on it. The cell must read as if it doesn't exist.
        self.assertEqual(en_cell["status"], "empty")
        self.assertNotIn(
            "page_id",
            en_cell,
            "Denied EN translation leaked its page_id",
        )
        self.assertNotIn(
            "edit_url",
            en_cell,
            "Denied EN translation leaked its edit_url",
        )


@override_settings(ALLOWED_HOSTS=["*"])
class APIEndpointTest(_TreeBuilderMixin, TestCase):
    """End-to-end check: the JSON API returns the expected envelope shape
    and HTTP semantics under the same restricted user.
    """

    @classmethod
    def setUpTestData(cls):
        cls._build_tree()
        cls.group = Group.objects.create(name="pagetree-api")
        _grant_admin(cls.group)
        GroupPagePermission.objects.create(
            group=cls.group, page=cls.article_b_de, permission_type="change"
        )
        cls.user = _make_user("pt-api", cls.group)

    def setUp(self):
        self.client.force_login(self.user)

    def test_invalid_locale_returns_400_envelope(self):
        # SERVER_NAME bypass: testserver isn't in ALLOWED_HOSTS.
        response = self.client.get(
            reverse("pagetree:api-tree") + "?locale=zz", SERVER_NAME="127.0.0.1"
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["error"]["code"], "invalid_locale")

    def test_response_sets_no_store_cache_control(self):
        response = self.client.get(
            reverse("pagetree:api-tree") + "?locale=de", SERVER_NAME="127.0.0.1"
        )
        self.assertEqual(response.status_code, 200)
        cc = response["Cache-Control"]
        self.assertIn("private", cc)
        self.assertIn("no-store", cc)

    def test_post_to_api_returns_405(self):
        response = self.client.post(
            reverse("pagetree:api-tree"), SERVER_NAME="127.0.0.1"
        )
        self.assertEqual(response.status_code, 405)


@override_settings(ALLOWED_HOSTS=["*"])
class BulkActionTest(_TreeBuilderMixin, TestCase):
    """Bulk publish/unpublish endpoint — input validation +
    permission gate. The Wagtail action classes do their own checks; this
    just verifies our envelope and the editable-set filter."""

    @classmethod
    def setUpTestData(cls):
        cls._build_tree()
        cls.group = Group.objects.create(name="pagetree-bulk")
        _grant_admin(cls.group)
        # Permit only Article B (DE).
        GroupPagePermission.objects.create(
            group=cls.group, page=cls.article_b_de, permission_type="change"
        )
        # Need publish permission too for the publish action to fly through
        # Wagtail's own check. We grant it on the same page.
        GroupPagePermission.objects.create(
            group=cls.group, page=cls.article_b_de, permission_type="publish"
        )
        cls.user = _make_user("pt-bulk", cls.group)

    def setUp(self):
        self.client.force_login(self.user)

    def _post(self, body):
        import json as _json

        return self.client.post(
            reverse("pagetree:api-bulk"),
            data=_json.dumps(body),
            content_type="application/json",
            SERVER_NAME="127.0.0.1",
        )

    def test_invalid_action_returns_400(self):
        r = self._post({"action": "explode", "page_ids": [self.article_b_de.id]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "invalid_action")

    def test_missing_page_ids_returns_400(self):
        r = self._post({"action": "publish"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "invalid_page_ids")

    def test_too_many_page_ids_returns_400(self):
        r = self._post({"action": "publish", "page_ids": list(range(1, 250))})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "too_many_page_ids")

    def test_denied_pages_recorded_separately(self):
        # Article A is outside the user's editable set → should land in `denied`.
        r = self._post(
            {
                "action": "publish",
                "page_ids": [self.article_a_de.id, self.article_b_de.id],
            }
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn(self.article_a_de.id, body["denied"])


@override_settings(ALLOWED_HOSTS=["*"])
class MoveActionTest(_TreeBuilderMixin, TestCase):
    """Drag-and-drop move endpoint — input validation, cycle guard,
    permission gate. The actual treebeard reorder is exercised by the
    success path (Article A ↔ Article B sibling swap)."""

    @classmethod
    def setUpTestData(cls):
        cls._build_tree()
        cls.group = Group.objects.create(name="pagetree-move")
        _grant_admin(cls.group)
        # Grant change + add + publish at the Wagtail root so the user can
        # reorder/reparent anywhere in this tree (Wagtail propagates page
        # permissions to descendants). Per-page restrictions belong in the
        # security test classes; this class is about move *mechanics*.
        for codename in ("change", "add", "publish"):
            GroupPagePermission.objects.create(
                group=cls.group, page=cls.root, permission_type=codename
            )
        cls.user = _make_user("pt-move", cls.group)

        # A second user with no edit perms anywhere — for the denial test.
        cls.outsider_group = Group.objects.create(name="pagetree-move-outsider")
        _grant_admin(cls.outsider_group)
        cls.outsider = _make_user("pt-move-outsider", cls.outsider_group)

    def setUp(self):
        self.client.force_login(self.user)

    def _post(self, body):
        import json as _json

        return self.client.post(
            reverse("pagetree:api-move"),
            data=_json.dumps(body),
            content_type="application/json",
            SERVER_NAME="127.0.0.1",
        )

    def test_invalid_position_returns_400(self):
        r = self._post(
            {
                "page_id": self.article_a_de.id,
                "target_id": self.article_b_de.id,
                "position": "diagonally",
            }
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "invalid_position")

    def test_non_integer_ids_returns_400(self):
        r = self._post({"page_id": "not-an-int", "target_id": 1, "position": "before"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "invalid_ids")

    def test_outsider_blocked_by_editable_set(self):
        self.client.logout()
        self.client.force_login(self.outsider)
        r = self._post(
            {
                "page_id": self.article_a_de.id,
                "target_id": self.article_b_de.id,
                "position": "after",
            }
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["code"], "denied")

    def test_cycle_into_descendant_rejected(self):
        # Magazin → Article A is a descendant chain; trying to drop Magazin
        # *inside* Article A would create a cycle.
        r = self._post(
            {
                "page_id": self.magazin_de.id,
                "target_id": self.article_a_de.id,
                "position": "inside",
            }
        )
        # The outer view also rejects via the editable-set check (magazin is
        # editable here, so we should get the cycle 400 from apply_move).
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "invalid")

    def test_cascade_moves_en_translation(self):
        # Move Article A DE *inside* Home DE (reparent away from Magazin).
        # The EN translation Article A EN should follow under Home EN
        # because the cascade resolves the new parent's EN translation.
        r = self._post(
            {
                "page_id": self.article_a_de.id,
                "target_id": self.home_de.id,
                "position": "inside",
                "cascade_translations": True,
            }
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        cascade = body.get("cascade") or []
        en = next((c for c in cascade if c["locale_code"] == "en"), None)
        self.assertIsNotNone(en, f"expected EN cascade entry, got {cascade!r}")
        self.assertEqual(en["status"], "moved")
        self.assertEqual(en["page_id"], self.article_a_en.id)

        # Verify the EN translation actually moved in the DB.
        # Fresh query — treebeard caches get_parent() on _cached_parent_obj
        # and refresh_from_db() doesn't clear that.
        fresh_en = Page.objects.get(id=self.article_a_en.id)
        self.assertEqual(fresh_en.get_parent().id, self.home_en.id)

    def test_cascade_disabled_leaves_translations_put(self):
        r = self._post(
            {
                "page_id": self.article_a_de.id,
                "target_id": self.home_de.id,
                "position": "inside",
                "cascade_translations": False,
            }
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json().get("cascade"), [])
        # EN translation stayed where it was. Same fresh-query rationale.
        fresh_en = Page.objects.get(id=self.article_a_en.id)
        self.assertEqual(fresh_en.get_parent().id, self.magazin_en.id)

    def test_sibling_swap_success(self):
        # Article A is currently before Article B (insertion order).
        # Drop A "after" B → A becomes the second child of magazin.
        r = self._post(
            {
                "page_id": self.article_a_de.id,
                "target_id": self.article_b_de.id,
                "position": "after",
            }
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["page_id"], self.article_a_de.id)
        self.assertEqual(body["new_parent_id"], self.magazin_de.id)
        self.assertFalse(body["noop"])

        # Verify the order actually changed in the DB.
        children = list(
            self.magazin_de.get_children().order_by("path").values_list("id", flat=True)
        )
        self.assertEqual(
            children,
            [self.article_b_de.id, self.article_a_de.id],
            "Article A should now follow Article B",
        )
