"""Locale resolution and validation."""

from typing import Optional

from wagtail.models import Locale


class InvalidLocale(ValueError):
    """Raised when a request's `?locale=` is not a known Wagtail Locale."""


def resolve_locale(language_code: Optional[str]) -> Locale:
    """Return the Locale matching `language_code`, or the default Locale.

    Raises ``InvalidLocale`` when a non-empty code does not match any
    configured Locale. Empty/None falls back to ``Locale.get_default()``.
    """
    if not language_code:
        return Locale.get_default()
    try:
        return Locale.objects.get(language_code=language_code)
    except Locale.DoesNotExist as exc:
        raise InvalidLocale(language_code) from exc
