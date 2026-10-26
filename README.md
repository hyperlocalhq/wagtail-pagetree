# wagtail-pagetree

Lazy-loaded, virtualised page tree for the [Wagtail](https://wagtail.org) admin.

Ships a single admin viewset (`pagetree:index`) that renders a fast, locale-aware
explorer over `wagtail.models.Page`. The tree loads children on demand via JSON
endpoints, supports drag-and-drop reordering with cascade translations,
context menu and bulk actions, respects `PagePermissionPolicy`, and scales to
large trees (P95 < 200 ms for 500-page corpora).

## Install

```bash
uv add wagtail-pagetree            # or: pip install wagtail-pagetree
uv add "wagtail-pagetree[localize]"  # with wagtail-localize integration
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    # ...
    "wagtail",
    "wagtail_pagetree",
    # ...
]
```

The viewset auto-registers via `wagtail_hooks.py`. Restart your dev server and
look for **Page Tree** in the admin sidebar.

[wagtail-localize](https://github.com/wagtail/wagtail-localize) is optional.
When installed, the tree flags out-of-date translations and links to its
sync / translate views; without it those features are simply absent.

## Requirements

- Python 3.10 – 3.14
- Django 4.2, 5.2, 6.0, 6.1
- Wagtail 6.3, 7.0, 8.0

## Translations

The admin UI ships English and German. Catalogs live in
`src/wagtail_pagetree/locale/<lang>/LC_MESSAGES/`:

- `django.po` — Python and template strings
- `djangojs.po` — the React frontend, served by the viewset's own
  `JavaScriptCatalog` (`pagetree:jsi18n`)

```bash
scripts/makemessages.sh          # re-extract every existing locale
scripts/makemessages.sh fr       # add a new locale
scripts/makemessages.sh --compile
```

## Development

```bash
uv sync                          # dev environment (pytest, tox, wagtail-localize)
uv run pytest                    # test suite against tests/settings.py (SQLite)
uv run pytest --cov              # with coverage
uv run pytest -m bench -s        # opt-in benchmarks
uv run tox run-parallel          # full Python × Django × Wagtail matrix

# rebuild the JS bundle after editing frontend/src/
cd frontend
npm install
npm run build
npm run check                    # drift gate: committed bundle must match source
```

## Release

1. Bump the version in `pyproject.toml` and `src/wagtail_pagetree/__init__.py`.
2. Commit, then tag and push: `git tag v0.1.0 && git push origin v0.1.0`.

The `Release` workflow runs the test matrix, builds, publishes to TestPyPI,
then PyPI (trusted publishing, no stored token) and creates a GitHub release.
It refuses to publish when the tag and the two version strings disagree.

## Layout

```
├── pyproject.toml
├── tox.ini
├── src/wagtail_pagetree/        # the Django app
│   ├── apps.py
│   ├── viewsets.py              # registers the admin viewset + JS catalog
│   ├── views.py                 # tree, children, bulk, move endpoints
│   ├── wagtail_hooks.py         # @hooks.register("register_admin_viewset")
│   ├── services/                # tree, presenters, permissions, locale, search, bulk, move, translations
│   ├── locale/                  # django.po / djangojs.po
│   ├── templates/wagtail_pagetree/page_tree.html
│   └── static/wagtail_pagetree/{css,js}/...
├── frontend/                    # React/JSX source for bundle.js (esbuild)
├── scripts/makemessages.sh
└── tests/                       # settings.py, urls.py, testapp/ + test modules
```

## License

MIT.
