import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Toolbar from "./Toolbar.jsx";
import Header from "./Header.jsx";
import NodeList from "./NodeList.jsx";
import Orphans from "./Orphans.jsx";
import Legend from "./Legend.jsx";
import BulkToolbar from "./BulkToolbar.jsx";
import { ApiError, getJson, postJson } from "../api.js";
import { childrenUrl } from "../urls.js";
import { ancestorIds, defaultExpansion, groupByParent } from "../tree.js";
import { handleTreeKeyDown } from "../keyboard.js";
import { loadExpanded, loadViewState, saveExpanded, saveViewState } from "../state.js";
import { COMPACT_QUERY, useMatchMedia } from "../responsive.js";
import { gettext, interpolate, ngettext, t } from "../i18n.js";

// Top-level state container. 5 useState hooks per the plan:
//   loadedNodes, expandedIds, loadingIds, searchQuery, primaryLocale
// We also track `locales`, `orphans`, `error`, `loading` (initial fetch).

const SEARCH_DEBOUNCE_MS = 250;

function dedupeNodesById(existing, incoming) {
  const seen = new Set(existing.map((n) => n.id));
  const out = existing.slice();
  for (const n of incoming) {
    if (!seen.has(n.id)) {
      out.push(n);
      seen.add(n.id);
    }
  }
  return out;
}

function App({ config }) {
  // View state from the last visit in this tab (state.js). A ?locale= in the
  // URL wins; ?clear_filters=1 drops the stored search and filters.
  const [restored] = useState(() => {
    const stored = loadViewState();
    return config.clearFilters ? { locale: stored.locale } : stored;
  });

  const [loadedNodes, setLoadedNodes] = useState([]);
  const [expandedIds, setExpandedIds] = useState(() => new Set());
  const [loadingIds, setLoadingIds] = useState(() => new Set());
  const [searchQuery, setSearchQuery] = useState(restored.search || "");
  const [primaryLocale, setPrimaryLocale] = useState(
    config.initialLocale || restored.locale || "",
  );

  const [locales, setLocales] = useState([]);
  const [orphans, setOrphans] = useState([]);
  const [error, setError] = useState(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [searchMode, setSearchMode] = useState(false);

  // Locale×status tree filter. `filterStatus` is one of the base
  // statuses or a flag (outdated/diverged), or "" when off. `filterLocale` is
  // the locale the status applies to (defaults to the primary locale).
  // Mutually exclusive with the text search; rendered through the matches path.
  const [filterLocale, setFilterLocale] = useState(restored.filterLocale || "");
  const [filterStatus, setFilterStatus] = useState(restored.filterStatus || "");

  // Page-type filter: a content type id (string) or "" when off. Combines with
  // either the text search or the status filter. `pageTypes` (the choices)
  // comes with the unfiltered tree payload and is kept while filtering.
  const [pageTypes, setPageTypes] = useState([]);
  const [filterPageType, setFilterPageType] = useState(restored.filterPageType || "");

  // Per-locale count of tree rows without a page, from the unfiltered tree
  // payload; kept while filtering. Drives the coverage in the header.
  const [coverage, setCoverage] = useState(null);

  // ?reveal=<id>: expand down to that row and highlight it, once. The ref
  // holds the request until a payload arrives; `revealedId` the row to
  // scroll to once it's rendered.
  const revealRef = useRef(config.revealId);
  const [revealedId, setRevealedId] = useState(null);

  // Bulk selection state. Set of page ids the user has ticked.
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkFlash, setBulkFlash] = useState(null);

  // Drag-and-drop reorder state.
  // - dragSourceId: the page being dragged (null when not dragging).
  // - dragOver: { id, position } where position ∈ "before" | "after" | "inside".
  //   Only one row at a time is the active drop target.
  const [dragSourceId, setDragSourceId] = useState(null);
  const [dragOver, setDragOver] = useState(null);

  // Debounced server search query (decoupled from input value).
  const [debouncedQuery, setDebouncedQuery] = useState(searchQuery.trim());
  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedQuery(searchQuery.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [searchQuery]);

  useEffect(() => {
    saveViewState({
      locale: primaryLocale,
      search: debouncedQuery,
      filterStatus,
      filterLocale,
      filterPageType,
    });
  }, [primaryLocale, debouncedQuery, filterStatus, filterLocale, filterPageType]);

  // The reveal / locale / clear_filters params are consumed on load; drop
  // them so a reload shows the restored state rather than replaying them.
  useEffect(() => {
    const url = new URL(window.location.href);
    ["locale", "reveal", "clear_filters"].forEach((key) => url.searchParams.delete(key));
    window.history.replaceState(window.history.state, "", url);
  }, []);

  // A filter (text search, locale×status and/or page type) is active — all
  // render through the matches path and hide orphans.
  const filterActive =
    Boolean(debouncedQuery) || Boolean(filterStatus) || Boolean(filterPageType);

  // List-fetch params shared by the main effect and post-mutation refetches.
  // Search and the status filter are mutually exclusive (enforced in the
  // change handlers), so at most one of these is set; the page type narrows
  // whichever is.
  const buildListParams = useCallback(() => {
    const params = { locale: primaryLocale || undefined };
    if (debouncedQuery) {
      params.search = debouncedQuery;
    } else if (filterStatus) {
      params.filter_status = filterStatus;
      params.filter_locale = filterLocale || primaryLocale;
    }
    if (filterPageType) params.page_type = filterPageType;
    return params;
  }, [primaryLocale, debouncedQuery, filterLocale, filterStatus, filterPageType]);

  // Apply a freshly fetched payload after a mutation, respecting the current
  // mode (filtered → matches, otherwise the full tree + orphans).
  const applyFresh = useCallback(
    (fresh) => {
      if (filterActive) {
        setLoadedNodes(fresh.matches || []);
      } else {
        setLoadedNodes(fresh.pages || []);
        setOrphans(fresh.orphans || []);
      }
    },
    [filterActive],
  );

  // Initial / locale-change / filter fetch. One effect, two modes.
  useEffect(() => {
    const ctrl = new AbortController();
    const params = buildListParams();

    setError(null);
    if (filterActive) {
      setSearchMode(true);
    } else {
      setInitialLoading(true);
      setSearchMode(false);
    }

    getJson(config.treeUrl, params, ctrl.signal)
      .then((payload) => {
        if (ctrl.signal.aborted) return;
        setLocales(payload.locales || []);
        setPageTypes(payload.page_types || []);
        if (!primaryLocale && payload.primary_locale) {
          setPrimaryLocale(payload.primary_locale);
        }

        let nodes;
        let expand;
        if (filterActive) {
          // Filtered payload: list of matches. Parents not in the match set
          // resolve to parent_id=null server-side, so matches render as a
          // flat list — exactly what "show me the stale pages" wants.
          nodes = payload.matches || [];
          setOrphans([]);
          // Auto-expand any ancestors that *are* within the match set.
          expand = new Set();
          for (const m of nodes) {
            for (const a of ancestorIds(nodes, m.id)) expand.add(a);
          }
        } else {
          nodes = payload.pages || [];
          setOrphans(payload.orphans || []);
          setCoverage(payload.coverage || null);
          // Reopen the branches the user had open in this locale.
          const loaded = new Set(nodes.map((n) => n.id));
          const saved = loadExpanded(payload.primary_locale);
          expand = saved
            ? new Set([...saved].filter((id) => loaded.has(id)))
            : defaultExpansion(nodes);
        }

        if (revealRef.current != null) {
          const target = nodes.find((n) => n.id === revealRef.current);
          revealRef.current = null;
          if (target) {
            for (const a of ancestorIds(nodes, target.id)) expand.add(a);
            // Open the row itself too: after "Add child page" the new
            // page is one of its children.
            expand.add(target.id);
            if (!filterActive) saveExpanded(payload.primary_locale, expand);
            setRevealedId(target.id);
          }
        }
        setLoadedNodes(nodes);
        setExpandedIds(expand);
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        // A remembered locale may have been deleted since: fall back to
        // the server's default instead of failing for good.
        if (err.code === "invalid_locale" && primaryLocale) {
          setPrimaryLocale("");
          return;
        }
        setError(err);
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setInitialLoading(false);
      });

    return () => ctrl.abort();
  }, [config.treeUrl, primaryLocale, debouncedQuery, filterLocale, filterStatus, filterPageType, filterActive, buildListParams]);

  // Lazy expand. If the node isn't already in loadedNodes' parent_id index,
  // fetch its children. Either way flip the expand bit.
  //
  // Stable callback ref so children's React.memo holds. We read the current
  // tree state through a ref to avoid recreating on every state change.
  const stateRef = useRef({ loadedNodes, primaryLocale, loadingIds, searchMode });
  stateRef.current = { loadedNodes, primaryLocale, loadingIds, searchMode };

  const fetchChildren = useCallback(
    async (pageId) => {
      const { primaryLocale: locale, loadingIds: currentLoading } = stateRef.current;
      if (currentLoading.has(pageId)) return;
      const url = childrenUrl(config.childrenUrlTemplate, pageId);
      setLoadingIds((prev) => {
        const next = new Set(prev);
        next.add(pageId);
        return next;
      });
      try {
        const payload = await getJson(url, { locale: locale || undefined });
        setLoadedNodes((existing) => dedupeNodesById(existing, payload.pages || []));
      } catch (err) {
        setError(err);
      } finally {
        setLoadingIds((prev) => {
          if (!prev.has(pageId)) return prev;
          const next = new Set(prev);
          next.delete(pageId);
          return next;
        });
      }
    },
    [config.childrenUrlTemplate],
  );

  const onToggle = useCallback(
    (pageId) => {
      setExpandedIds((prev) => {
        const { loadedNodes: nodes, primaryLocale: locale, searchMode: filtered } =
          stateRef.current;
        const next = new Set(prev);
        if (next.has(pageId)) {
          next.delete(pageId);
        } else {
          next.add(pageId);
          // If this parent has no loaded children, fetch them.
          const hasChildren = nodes.some((n) => n.parent_id === pageId);
          if (!hasChildren) {
            // Fire-and-forget; setLoadingIds inside fetchChildren will trigger spinner.
            fetchChildren(pageId);
          }
        }
        // Filtered views auto-expand their matches; only the full tree's
        // open branches are worth restoring.
        if (!filtered) saveExpanded(locale, next);
        return next;
      });
    },
    [fetchChildren],
  );

  const onSearchChange = useCallback((value) => {
    setSearchQuery(value);
    // Text search and the status filter are mutually exclusive.
    if (value) setFilterStatus("");
  }, []);

  const onFilterLocaleChange = useCallback((code) => {
    setFilterLocale(code);
  }, []);

  const onFilterPageTypeChange = useCallback((pageType) => {
    setFilterPageType(pageType);
    setSelectedIds(new Set());
  }, []);

  const onFilterStatusChange = useCallback((status) => {
    setFilterStatus(status);
    if (status) {
      setSearchQuery("");
      setSelectedIds(new Set());
    }
  }, []);

  // Coverage in the header: list the pages missing in that locale.
  const onShowMissing = useCallback((code) => {
    setSearchQuery("");
    setFilterLocale(code);
    setFilterStatus("empty");
    setSelectedIds(new Set());
  }, []);

  const onLocaleChange = useCallback((value) => {
    setPrimaryLocale(value);
    setSearchQuery("");
    setFilterStatus("");
    setFilterLocale("");
    setFilterPageType("");
    setSelectedIds(new Set());
  }, []);

  // Selection handlers — stable refs so memoised Node doesn't re-render
  // unnecessarily.
  const onSelectToggle = useCallback((pageId) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(pageId)) next.delete(pageId);
      else next.add(pageId);
      return next;
    });
  }, []);

  const onSelectClear = useCallback(() => setSelectedIds(new Set()), []);

  // Trigger /api/bulk/ for the current selection in the given locale.
  // Reloads the tree on success so dot statuses reflect the new state.
  // Surfaces a structured flash showing per-outcome counts.
  const runBulk = useCallback(
    async (action, localeCode) => {
      if (selectedIds.size === 0) return;
      setBulkBusy(true);
      setBulkFlash(null);
      const ids = Array.from(selectedIds);
      try {
        const result = await postJson(config.bulkUrl, {
          action,
          locale_code: localeCode,
          page_ids: ids,
        });
        setBulkFlash({
          action,
          localeCode,
          success: (result.success || []).length,
          denied: (result.denied || []).length,
          skipped: (result.skipped || []).length,
          errored: (result.errored || []).length,
        });
        setSelectedIds(new Set());
        // Refetch the tree so dots reflect the new live / draft state.
        const fresh = await getJson(config.treeUrl, buildListParams());
        applyFresh(fresh);
      } catch (err) {
        setError(err);
      } finally {
        setBulkBusy(false);
      }
    },
    [selectedIds, config.bulkUrl, config.treeUrl, buildListParams, applyFresh],
  );

  // Single-page action used by the per-cell DotMenu's Publish / Unpublish.
  // Hits the same /api/bulk/ endpoint with one explicit page_id (the
  // translation's own id, no locale_code resolution needed). Refetches
  // the tree on success so the dot updates.
  const onSingleAction = useCallback(
    async (pageId, action) => {
      try {
        const result = await postJson(config.bulkUrl, {
          action,
          page_ids: [pageId],
        });
        setBulkFlash({
          action,
          success: (result.success || []).length,
          denied: (result.denied || []).length,
          skipped: (result.skipped || []).length,
          errored: (result.errored || []).length,
        });
        const fresh = await getJson(config.treeUrl, buildListParams());
        applyFresh(fresh);
      } catch (err) {
        setError(err);
      }
    },
    [config.bulkUrl, config.treeUrl, buildListParams, applyFresh],
  );

  // Drag-and-drop callbacks. Stable refs so memoised Node doesn't churn.
  const onDragStart = useCallback((pageId) => {
    setDragSourceId(pageId);
    setDragOver(null);
  }, []);

  const onDragEnd = useCallback(() => {
    setDragSourceId(null);
    setDragOver(null);
  }, []);

  // Throttle by equality: only push setState when the (id, position) pair
  // actually changes. dragover fires on every mouse pixel — without this
  // we'd burn React renders on identical state.
  const dragOverRef = useRef(null);
  dragOverRef.current = dragOver;
  const onDragOver = useCallback((pageId, position) => {
    const cur = dragOverRef.current;
    if (cur && cur.id === pageId && cur.position === position) return;
    setDragOver({ id: pageId, position });
  }, []);

  const onDragLeaveRow = useCallback((pageId) => {
    const cur = dragOverRef.current;
    if (cur && cur.id === pageId) setDragOver(null);
  }, []);

  // POST /api/move/ then refetch the tree (paths can change anywhere on a
  // reparent, so a partial update is too fragile for V1 of DnD).
  // cascade_translations=true is the default — every other-locale
  // translation of the moved page also moves to its locale-equivalent
  // target where one exists. The result includes a per-locale outcome
  // list which we summarise into the flash banner.
  const onMoveDrop = useCallback(
    async (sourceId, targetId, position) => {
      // Drop on self is a no-op; same parent + same position would be too,
      // but that's resolved server-side.
      if (sourceId === targetId) return;
      try {
        const result = await postJson(config.moveUrl, {
          page_id: sourceId,
          target_id: targetId,
          position,
          cascade_translations: true,
        });
        // Summarise cascade outcomes for the user.
        const cascade = result.cascade || [];
        const moved = cascade.filter((c) => c.status === "moved").length;
        const skippedNoTarget = cascade.filter(
          (c) => c.status === "skipped_no_target",
        ).length;
        const skippedDiverged = cascade.filter(
          (c) => c.status === "skipped_diverged_target",
        ).length;
        const denied = cascade.filter((c) => c.status === "denied").length;
        const errored = cascade.filter((c) => c.status === "errored").length;
        const skipped = skippedNoTarget + skippedDiverged;
        setBulkFlash({
          action: "move",
          success: 1 + moved,
          denied,
          skipped,
          errored,
        });
        const fresh = await getJson(config.treeUrl, buildListParams());
        applyFresh(fresh);
      } catch (err) {
        setError(err);
      }
    },
    [config.moveUrl, config.treeUrl, buildListParams, applyFresh],
  );

  const byParent = useMemo(() => groupByParent(loadedNodes), [loadedNodes]);

  // Scroll the revealed row into view once it's rendered. The highlight is
  // a one-off CSS animation, so a class set on the DOM node is enough.
  useEffect(() => {
    if (revealedId == null || initialLoading) return;
    const row = document.querySelector(`.pagetree [data-pt-row-id="${revealedId}"]`);
    if (!row) return;
    row.scrollIntoView({ block: "center" });
    row.classList.add("pt-row--revealed");
    setRevealedId(null);
  }, [revealedId, initialLoading, loadedNodes]);

  // Compact mode hides the Type column on narrow viewports (tablets / split
  // screens) so the title stays readable.
  const compact = useMatchMedia(COMPACT_QUERY);

  return (
    <div className="pagetree">
      <Toolbar
        locales={locales}
        primaryLocale={primaryLocale}
        searchQuery={searchQuery}
        pageTypes={pageTypes}
        filterPageType={filterPageType}
        filterLocale={filterLocale || primaryLocale}
        filterStatus={filterStatus}
        onLocaleChange={onLocaleChange}
        onSearchChange={onSearchChange}
        onFilterPageTypeChange={onFilterPageTypeChange}
        onFilterLocaleChange={onFilterLocaleChange}
        onFilterStatusChange={onFilterStatusChange}
      />
      {error && (
        <div className="pt-error" role="alert">
          {errorMessageFor(error)}
        </div>
      )}
      {bulkFlash && (
        <div
          className="pt-flash"
          role="status"
          onClick={() => setBulkFlash(null)}
        >
          {flashMessageFor(bulkFlash)}
          <span className="pt-flash__dismiss" aria-hidden="true">×</span>
        </div>
      )}
      <BulkToolbar
        selectedCount={selectedIds.size}
        busy={bulkBusy}
        locales={locales}
        primaryLocale={primaryLocale}
        onPublish={(loc) => runBulk("publish", loc)}
        onUnpublish={(loc) => runBulk("unpublish", loc)}
        onClear={onSelectClear}
      />
      {initialLoading ? (
        <div className="pt-loading">{t.loading}</div>
      ) : loadedNodes.length === 0 && searchMode ? (
        <div className="pt-empty">
          {debouncedQuery ? t.searchNoMatches : t.filterNoMatches}
        </div>
      ) : (
        <div
          className="pt-table"
          onKeyDown={(e) => handleTreeKeyDown(e, { onToggle })}
          style={{
            // Select | title (1fr, may shrink for ellipsis) | type
            // (max-content, dropped in compact mode) | one col per locale |
            // menu | actions (⋯). Compact mode shrinks the per-locale and
            // menu columns to claw back horizontal space.
            gridTemplateColumns: [
              "32px",
              "minmax(0, 1fr)",
              ...(compact ? [] : ["max-content"]),
              ...locales.map(() => (compact ? "32px" : "40px")),
              compact ? "44px" : "60px",
              compact ? "32px" : "36px",
            ].join(" "),
          }}
        >
          <Header
            locales={locales}
            compact={compact}
            primaryLocale={primaryLocale}
            coverage={coverage}
            onShowMissing={onShowMissing}
          />
          <NodeList
            parentId={null}
            byParent={byParent}
            locales={locales}
            expanded={expandedIds}
            loading={loadingIds}
            searchQuery={searchMode ? debouncedQuery : ""}
            onToggle={onToggle}
            compact={compact}
            selectedIds={selectedIds}
            onSelectToggle={onSelectToggle}
            onSingleAction={onSingleAction}
            dragSourceId={dragSourceId}
            dragOver={dragOver}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            onDragOver={onDragOver}
            onDragLeaveRow={onDragLeaveRow}
            onMoveDrop={onMoveDrop}
          />
        </div>
      )}
      {!searchMode && <Orphans orphans={orphans} primaryLocale={primaryLocale} />}
      <Legend />
    </div>
  );
}

// One flash, three actions (publish / unpublish / move). Move action's
// `success` includes the primary page + every translation that followed
// via cascade; `skipped` is the count that couldn't follow (no target
// translation or diverged target).
function flashMessageFor(flash) {
  const n = flash.success;
  // Whole sentences per action so translators never stitch fragments.
  const successFormats = {
    publish: flash.localeCode
      ? ngettext("%(count)s %(locale)s page published.", "%(count)s %(locale)s pages published.", n)
      : ngettext("%(count)s page published.", "%(count)s pages published.", n),
    unpublish: flash.localeCode
      ? ngettext("%(count)s %(locale)s page unpublished.", "%(count)s %(locale)s pages unpublished.", n)
      : ngettext("%(count)s page unpublished.", "%(count)s pages unpublished.", n),
    move: ngettext("%(count)s page moved.", "%(count)s pages moved.", n),
  };
  const head =
    n > 0
      ? interpolate(
          successFormats[flash.action] || "%(count)s",
          { count: n, locale: (flash.localeCode || "").toUpperCase() },
          true,
        )
      : gettext("No pages were changed.");
  const tail = [
    flash.denied > 0 && interpolate(gettext("%s denied."), [flash.denied]),
    flash.skipped > 0 &&
      (flash.action === "move"
        ? interpolate(
            ngettext(
              "%s translation not moved (no target or diverged tree).",
              "%s translations not moved (no target or diverged tree).",
              flash.skipped,
            ),
            [flash.skipped],
          )
        : interpolate(
            gettext("%s skipped (no translation or already in target state)."),
            [flash.skipped],
          )),
    flash.errored > 0 && interpolate(gettext("%s errored."), [flash.errored]),
  ].filter(Boolean);
  return [head, ...tail].join(" ");
}

function errorMessageFor(err) {
  if (err instanceof ApiError) {
    if (err.code === "search_too_long") return t.searchTooLong;
    if (err.code === "search_too_broad") return t.searchTooBroad;
    return err.message || t.errorGeneric;
  }
  return t.errorGeneric;
}

export default App;
