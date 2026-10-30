// The tree's view state (locale, search, filters, open branches) kept in
// sessionStorage, so coming back from an edit / add / delete view restores
// what the user was looking at. Per tab, gone when the tab closes.

const KEY = "wagtail_pagetree";

export function loadViewState() {
  try {
    return JSON.parse(window.sessionStorage.getItem(KEY)) || {};
  } catch (_e) {
    return {};
  }
}

export function saveViewState(patch) {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify({ ...loadViewState(), ...patch }));
  } catch (_e) {
    // Storage full or disabled: the tree still works, it just forgets.
  }
}

// Open branches per locale: page ids differ between locale trees.
export function loadExpanded(locale) {
  const ids = (loadViewState().expanded || {})[locale];
  return Array.isArray(ids) ? new Set(ids) : null;
}

export function saveExpanded(locale, ids) {
  if (!locale) return;
  const expanded = loadViewState().expanded || {};
  saveViewState({ expanded: { ...expanded, [locale]: Array.from(ids) } });
}
