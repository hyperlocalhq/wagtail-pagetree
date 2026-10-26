# wagtail-pagetree frontend

JSX source for the Page Tree admin bundle.

## Build

```bash
cd frontend
npm install
npm run build           # writes ../src/wagtail_pagetree/static/wagtail_pagetree/js/bundle.js
npm run check           # exit 1 if the committed bundle is stale (CI gate)
```

## Why a bundle is committed

- Installing the Python package must not require a JS toolchain.
- The bundle is small (externalises React).
- `npm run check` enforces source/bundle parity so the committed file can't drift silently.

## Constraints

- React/ReactDOM are externalised → consume `window.React` / `window.ReactDOM` from Wagtail's admin bundle.
- No `createRoot`, no `useTransition`, no `use()` — React 16.14 API only.
- IIFE format. Auto-mounts on DOMContentLoaded if `#pagetree-root` is present.
- User-facing strings go through `gettext`/`ngettext` from `src/i18n.js`.
