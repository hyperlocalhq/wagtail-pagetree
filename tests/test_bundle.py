"""Sanity checks for the committed JS bundle.

These tests do *not* rebuild the bundle (CI doesn't have node). They guard
against the bundle file being lost, truncated, or accidentally replaced
with an empty stub. The byte-exact drift check lives in
``frontend/build.mjs --check`` and must be run by hand or by a local
pre-commit hook.
"""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
STATIC_ROOT = PACKAGE_ROOT / "src" / "wagtail_pagetree" / "static" / "wagtail_pagetree"
BUNDLE = STATIC_ROOT / "js" / "bundle.js"
STYLES = STATIC_ROOT / "css" / "styles.css"


def test_bundle_exists():
    assert BUNDLE.exists(), f"missing committed bundle at {BUNDLE}"


def test_bundle_is_iife_using_window_react():
    text = BUNDLE.read_text(encoding="utf-8")
    assert text.startswith("(()=>{") or text.startswith("(function"), (
        "bundle is not in IIFE form — esbuild config drift"
    )
    assert "window.React" in text, (
        "bundle does not reference window.React — react externalisation broken"
    )
    assert "window.ReactDOM" in text, (
        "bundle does not reference window.ReactDOM — react-dom externalisation broken"
    )


def test_bundle_under_size_budget():
    # M2 acceptance was < 30 KB minified, externalising React; raised to 32 KB
    # for the gettext wrappers and whole-sentence plural msgids (~1.2 KB).
    size = BUNDLE.stat().st_size
    assert size < 32 * 1024, f"bundle is {size} bytes, budget is 32 KB"


def test_styles_exists():
    assert STYLES.exists(), f"missing committed stylesheet at {STYLES}"
