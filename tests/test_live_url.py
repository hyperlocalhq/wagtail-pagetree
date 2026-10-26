"""Locale-prefix behaviour for the "View live" URL builder.

`_live_url` strips the site root path from a Wagtail ``url_path`` and then
reverses ``wagtail_serve`` under the SiteRootPath's language code so the
project's ``i18n_patterns`` injects the right locale prefix
(``/de/about/`` rather than ``/about/``). The previous string-only
implementation skipped the prefix, producing 404s on i18n-enabled sites.
"""

from collections import namedtuple

import pytest

from wagtail_pagetree.services.presenters import _live_url


SiteRootPath = namedtuple(
    "SiteRootPath", ["site_id", "root_path", "root_url", "language_code"]
)


@pytest.fixture
def site_roots_i18n():
    # Mirrors what Wagtail returns with WAGTAIL_I18N_ENABLED + 2 root translations.
    return [
        SiteRootPath(2, "/willkommen/", "https://example.test", "de"),
        SiteRootPath(2, "/welcome/", "https://example.test", "en"),
    ]


def test_returns_none_for_empty_url_path(site_roots_i18n):
    assert _live_url("", site_roots_i18n) is None


def test_returns_none_when_no_root_matches(site_roots_i18n):
    assert _live_url("/unrooted/page/", site_roots_i18n) is None


@pytest.mark.django_db
def test_de_url_path_resolves_with_de_prefix(site_roots_i18n):
    # /willkommen/ueber-uns/  →  /de/ueber-uns/
    url = _live_url("/willkommen/ueber-uns/", site_roots_i18n)
    assert url == "/de/ueber-uns/"


@pytest.mark.django_db
def test_en_url_path_resolves_with_en_prefix(site_roots_i18n):
    # /welcome/about-us/  →  /en/about-us/
    url = _live_url("/welcome/about-us/", site_roots_i18n)
    assert url == "/en/about-us/"


@pytest.mark.django_db
def test_root_page_url_path(site_roots_i18n):
    # The root page itself has url_path equal to its own root_path.
    assert _live_url("/willkommen/", site_roots_i18n) == "/de/"
    assert _live_url("/welcome/", site_roots_i18n) == "/en/"


@pytest.mark.django_db
def test_falls_back_when_site_root_has_no_language_code():
    # Pre-i18n Wagtail / non-translated sites: language_code is None. Result
    # is whatever ``reverse("wagtail_serve", ...)`` produces without override.
    legacy = [SiteRootPath(1, "/willkommen/", "https://example.test", None)]
    url = _live_url("/willkommen/about/", legacy)
    # Could be "/about/" (no i18n) or "/<active>/about/" (i18n_patterns
    # picks up the test runner's default language) — but it must at least
    # end with "/about/" and not be None.
    assert url is not None
    assert url.endswith("/about/")
