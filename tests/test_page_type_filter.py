"""``?page_type=`` — the page-type tree filter.

On its own it lists the primary pages of one content type; combined with
``?search=`` or ``?filter_status=`` it narrows those match sets. The unfiltered
tree payload carries the ``page_types`` choices.

Run with:
    uv run pytest tests/test_page_type_filter.py
"""

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from wagtail.models import Locale, Page, get_page_models

from wagtail_pagetree.services.presenters import _page_type_options

User = get_user_model()


def _other_page_model():
    """Any concrete Page subclass — keeps the test project-agnostic."""
    return next(model for model in get_page_models() if model is not Page)


class PageTypeFilterAPITest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.de = Locale.objects.get_or_create(language_code="de")[0]
        root = Page.objects.filter(depth=1).first() or Page.add_root(
            title="Root", slug="root-pt", locale=cls.de
        )
        cls.page_ct = ContentType.objects.get_for_model(Page)
        cls.other_ct = ContentType.objects.get_for_model(_other_page_model())

        def de(title, slug, content_type, **kw):
            # Only the content type matters to the filter (it reads
            # ``content_type_id`` via ``values()``), so a plain Page row
            # stamped with the other type stands in for a real subclass.
            return root.add_child(
                instance=Page(
                    title=title,
                    slug=slug,
                    locale=cls.de,
                    content_type=content_type,
                    **kw,
                )
            )

        de("PT Plain Live", "pt-plain-live", cls.page_ct, live=True)
        de("PT Plain Draft", "pt-plain-draft", cls.page_ct, live=False)
        de("PT Other Live", "pt-other-live", cls.other_ct, live=True)
        de("PT Other Draft", "pt-other-draft", cls.other_ct, live=False)

        cls.superuser = User.objects.create_superuser(
            username="pt-page-type", email="pt@example.invalid", password="x"
        )

    def setUp(self):
        self.client.force_login(self.superuser)

    def _get(self, qs):
        return self.client.get(
            f"{reverse('pagetree:api-tree')}?{qs}", SERVER_NAME="127.0.0.1"
        )

    def _titles(self, qs):
        r = self._get(qs)
        self.assertEqual(r.status_code, 200, r.content)
        return {m["title"] for m in r.json()["matches"] if m["title"].startswith("PT ")}

    def test_page_type_alone_lists_that_type(self):
        self.assertEqual(
            self._titles(f"locale=de&page_type={self.other_ct.id}"),
            {"PT Other Live", "PT Other Draft"},
        )

    def test_page_type_narrows_search(self):
        self.assertEqual(
            self._titles(f"locale=de&search=Live&page_type={self.other_ct.id}"),
            {"PT Other Live"},
        )

    def test_page_type_narrows_status_filter(self):
        self.assertEqual(
            self._titles(
                f"locale=de&filter_locale=de&filter_status=draft"
                f"&page_type={self.other_ct.id}"
            ),
            {"PT Other Draft"},
        )

    def test_unused_page_type_matches_nothing(self):
        user_ct = ContentType.objects.get_for_model(User)
        self.assertEqual(self._titles(f"locale=de&page_type={user_ct.id}"), set())

    def test_non_integer_page_type_returns_400(self):
        r = self._get("locale=de&page_type=abc")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(r.json()["error"]["code"], "invalid_page_type")

    def test_tree_payload_lists_page_types(self):
        r = self._get("locale=de")
        self.assertEqual(r.status_code, 200, r.content)
        ids = {pt["id"] for pt in r.json()["page_types"]}
        self.assertIn(self.page_ct.id, ids)
        self.assertIn(self.other_ct.id, ids)


def test_page_type_options_skip_placeholders_and_root_and_sort_by_name():
    nodes = [
        {"id": 1, "depth": 1, "page_type_id": 1, "page_type": "Page"},
        {"id": 5, "depth": 2, "is_placeholder": True},
        {"id": 2, "depth": 3, "page_type_id": 20, "page_type": "news page"},
        {"id": 3, "depth": 3, "page_type_id": 10, "page_type": "Event page"},
        {"id": 4, "depth": 4, "page_type_id": 20, "page_type": "news page"},
    ]
    assert _page_type_options(nodes) == [
        {"id": 10, "name": "Event page"},
        {"id": 20, "name": "news page"},
    ]
