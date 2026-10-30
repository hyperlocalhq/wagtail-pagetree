// Resolve admin URL prefixes. The page template stamps them onto the root
// element so JS doesn't have to hard-code Wagtail's admin URL prefix
// (which is per-project: /cms/, /admin/, etc.).
//
// `data-children-url-template` is rendered with `page_id=0`; the JS replaces
// the trailing "/0/" with the real page id at call time.

export function readConfig(rootEl) {
  const cfg = {
    treeUrl: rootEl.dataset.treeUrl,
    childrenUrlTemplate: rootEl.dataset.childrenUrlTemplate,
    bulkUrl: rootEl.dataset.bulkUrl,
    moveUrl: rootEl.dataset.moveUrl,
    initialLocale: rootEl.dataset.locale || "",
    // ?reveal=<page id>: open the tree at that page (see App's reveal).
    revealId: Number(rootEl.dataset.reveal) || null,
    // ?clear_filters=1: start without the search / filters kept from the
    // last visit ("Show in Page Tree" from a page's edit view).
    clearFilters: Boolean(rootEl.dataset.clearFilters),
  };
  if (
    !cfg.treeUrl ||
    !cfg.childrenUrlTemplate ||
    !cfg.bulkUrl ||
    !cfg.moveUrl
  ) {
    throw new Error(
      "pagetree: missing data-tree-url / data-children-url-template / data-bulk-url / data-move-url on #pagetree-root",
    );
  }
  return cfg;
}

export function childrenUrl(template, pageId) {
  return template.replace(/\/0\/?$/, `/${pageId}/`);
}
