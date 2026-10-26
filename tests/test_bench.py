"""Bench gate for the tree query.

Plan acceptance criterion: 500-page tree, two locales, ``build_tree_payload``
P95 latency < 200 ms. Asserted here against a synthetic fixture so the
gate is reproducible and runs in CI on any clean DB.

Marked ``@pytest.mark.bench`` so the slow setup can be opted into:

    uv run pytest tests/test_bench.py -m bench -v -s
"""

import statistics
import time

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from wagtail.models import Locale, Page

from wagtail_pagetree.services.permissions import (
    permitted_ids,
    placeholder_ids,
)
from wagtail_pagetree.services.presenters import (
    build_tree_payload,
)

User = get_user_model()


def _make_request(user) -> object:
    from django.http import HttpRequest

    req = HttpRequest()
    req.user = user
    req.method = "GET"
    return req


@pytest.mark.bench
@override_settings(ALLOWED_HOSTS=["*"])
class TreeQueryBench(TestCase):
    """500-page synthetic tree, run build_tree_payload and gate the latency."""

    PAGE_COUNT = 500
    BREADTH = 25  # ≈ 25 children per parent at depth 3 → ~500 nodes total
    WARMUP_RUNS = 3
    MEASURED_RUNS = 10
    LATENCY_BUDGET_MS = 200

    @classmethod
    def setUpTestData(cls):
        cls.de = Locale.objects.get_or_create(language_code="de")[0]
        cls.en = Locale.objects.get_or_create(language_code="en")[0]

        root = Page.objects.filter(depth=1).first()
        if root is None:
            root = Page.add_root(title="Root", slug="root", locale=cls.de)
        cls.root = root

        # Synthetic DE tree: 1 home → BREADTH sections → BREADTH children each
        cls.home_de = root.add_child(
            instance=Page(title="Home DE", slug="home-de-bench", locale=cls.de)
        )

        created = 1
        for s in range(cls.BREADTH):
            section = cls.home_de.add_child(
                instance=Page(title=f"Section {s}", slug=f"section-{s}", locale=cls.de)
            )
            created += 1
            for i in range(cls.BREADTH):
                if created >= cls.PAGE_COUNT:
                    break
                section.add_child(
                    instance=Page(
                        title=f"Article {s}-{i}",
                        slug=f"article-{s}-{i}",
                        locale=cls.de,
                        live=True,
                    )
                )
                created += 1
            if created >= cls.PAGE_COUNT:
                break

        cls.actual_count = created
        cls.superuser = User.objects.create_superuser(  # type: ignore[attr-defined]
            username="bench-super",
            email="bench@example.invalid",
            password="x",
        )

    def _measure_one(self) -> float:
        request = _make_request(self.superuser)
        permitted = permitted_ids(request)
        placeholder = placeholder_ids(request)
        all_locales = list(Locale.objects.all())

        t0 = time.perf_counter()
        payload = build_tree_payload(
            primary_locale=self.de,
            all_locales=all_locales,
            permitted=permitted,
            placeholder=placeholder,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        # Sanity: the payload covers the full fixture.
        assert len(payload["pages"]) >= self.PAGE_COUNT - 5, (
            f"payload covered only {len(payload['pages'])} of {self.PAGE_COUNT}"
        )
        return elapsed_ms

    def test_build_tree_payload_under_budget(self):
        # Warm-up: load Page model relations, prime DB plan cache.
        for _ in range(self.WARMUP_RUNS):
            self._measure_one()

        latencies = [self._measure_one() for _ in range(self.MEASURED_RUNS)]
        latencies.sort()
        p50 = statistics.median(latencies)
        p95_index = max(0, int(len(latencies) * 0.95) - 1)
        p95 = latencies[p95_index]

        print(
            f"\n[bench] pages={self.actual_count} "
            f"runs={self.MEASURED_RUNS} "
            f"p50={p50:.1f}ms p95={p95:.1f}ms "
            f"min={latencies[0]:.1f} max={latencies[-1]:.1f}",
        )

        self.assertLess(
            p95,
            self.LATENCY_BUDGET_MS,
            f"build_tree_payload p95 {p95:.1f}ms > budget {self.LATENCY_BUDGET_MS}ms "
            f"(latencies: {[round(x, 1) for x in latencies]})",
        )


@pytest.mark.bench
@override_settings(ALLOWED_HOSTS=["*"])
class TreeQueryExplain(TestCase):
    """Captures EXPLAIN ANALYZE output for the two key queries.

    Always passes — this is documentation, not assertion. Run with -s to see
    the plans:

        pytest -m bench -k explain -s
    """

    @classmethod
    def setUpTestData(cls):
        cls.de = Locale.objects.get_or_create(language_code="de")[0]
        root = Page.objects.filter(depth=1).first() or Page.add_root(
            title="Root", slug="root", locale=cls.de
        )
        home = root.add_child(
            instance=Page(title="Home DE", slug="home-explain", locale=cls.de)
        )
        for i in range(50):
            home.add_child(
                instance=Page(
                    title=f"Page {i}",
                    slug=f"page-{i}",
                    locale=cls.de,
                    live=True,
                )
            )

    def test_explain_primary_rows(self):
        if connection.vendor != "postgresql":
            self.skipTest("EXPLAIN ANALYZE only meaningful on Postgres")

        with connection.cursor() as cur:
            cur.execute(
                "EXPLAIN ANALYZE SELECT id, title, slug, path, depth, numchild, "
                "live, has_unpublished_changes, show_in_menus, translation_key, "
                "content_type_id, alias_of_id, url_path FROM wagtailcore_page "
                "WHERE locale_id = %s ORDER BY path",
                [self.de.id],
            )
            plan = "\n".join(row[0] for row in cur.fetchall())
        print("\n[bench/explain] fetch_primary_rows:\n" + plan)

    def test_explain_translation_matrix(self):
        if connection.vendor != "postgresql":
            self.skipTest("EXPLAIN ANALYZE only meaningful on Postgres")

        keys = list(
            Page.objects.filter(locale=self.de).values_list(
                "translation_key", flat=True
            )[:20]
        )
        if not keys:
            self.skipTest("no fixture pages in DE locale")

        with connection.cursor() as cur:
            cur.execute(
                "EXPLAIN ANALYZE SELECT id, translation_key, locale_id, live, "
                "has_unpublished_changes, alias_of_id, path, depth FROM wagtailcore_page "
                "WHERE translation_key = ANY(%s) AND locale_id != %s",
                [keys, self.de.id],
            )
            plan = "\n".join(row[0] for row in cur.fetchall())
        print("\n[bench/explain] fetch_translation_matrix:\n" + plan)
