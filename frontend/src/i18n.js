// Thin wrappers over Django's JavaScript catalog, which Wagtail's admin base
// template loads before this (deferred) bundle and exposes as globals
// (`gettext`, `ngettext`, `interpolate`). Outside the admin — tests, a bare
// page — they fall back to English so the UI still renders.
//
// Always call these with literal strings so `makemessages -d djangojs`
// (xgettext) can extract them into locale/*/LC_MESSAGES/djangojs.po.

export function gettext(msgid) {
  return typeof window.gettext === "function" ? window.gettext(msgid) : msgid;
}

export function ngettext(singular, plural, count) {
  if (typeof window.ngettext === "function") {
    return window.ngettext(singular, plural, count);
  }
  return count === 1 ? singular : plural;
}

// `interpolate(fmt, [a, b])` replaces `%s` in order; `interpolate(fmt, obj, true)`
// replaces `%(name)s`. Same contract as Django's JS catalog.
export function interpolate(fmt, values, named = false) {
  if (typeof window.interpolate === "function") {
    return window.interpolate(fmt, values, named);
  }
  if (named) {
    return fmt.replace(/%\((\w+)\)s/g, (_m, key) => String(values[key]));
  }
  const queue = [...values];
  return fmt.replace(/%s/g, () => String(queue.shift()));
}

export const t = {
  pageTree: gettext("Page Tree"),
  loading: gettext("Loading…"),
  searchPlaceholder: gettext("Search pages…"),
  searchTooLong: gettext("Search query is too long."),
  searchTooBroad: gettext("Too many matches; please refine the query."),
  searchNoMatches: gettext("No pages match this query."),
  filterStatusLabel: gettext("Filter status"),
  filterStatusOff: gettext("No filter"),
  filterLocaleLabel: gettext("Filter locale"),
  filterInLocale: gettext("in"),
  filterNoMatches: gettext("No pages match this filter."),
  pageTypeLabel: gettext("Page type"),
  pageTypeAll: gettext("All page types"),
  errorGeneric: gettext("Failed to load pages."),
  retry: gettext("Retry"),
  primaryLocale: gettext("Primary locale"),
  pagesWithoutPrimary: gettext("Pages without"),
  expandRow: gettext("Expand"),
  collapseRow: gettext("Collapse"),
  noTitle: gettext("(untitled)"),
  noEditPermission: gettext("You can't edit this page."),
  createTranslation: gettext("Create translation"),
  divergedTitle: gettext("Translation lives at a different position"),
  alias: gettext("alias"),
  aliasOf: gettext("Alias"),
  loadingChildren: gettext("Loading children…"),
};
