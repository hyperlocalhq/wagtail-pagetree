// WAI-ARIA Tree keyboard pattern (subset).
//
// Wired at the .pt-table level via onKeyDown. The DOM is the source of truth
// for focus — we query for `[data-pt-row-id]` elements that are visible
// (i.e. their data-pt-row-id is in the rendered DOM) and route arrow-key
// motions through them. Each row's title link carries the data-pt-row-id
// so default Tab/Enter behaviour still works.
//
// Keys handled here:
//   ArrowDown / ArrowUp  — next / previous visible row's title
//   ArrowRight           — expand current row (if collapsible & collapsed),
//                          else move to first child
//   ArrowLeft            — collapse current row (if expanded),
//                          else move to parent
//   Home / End           — first / last visible row
//
// The expand toggle button is a real <button> so Space/Enter on it still
// triggers expand via native button behaviour — we don't override that.

function focusableRows(treeEl) {
  return Array.from(treeEl.querySelectorAll("[data-pt-row-id]"));
}

function currentIndex(rows) {
  const active = document.activeElement;
  return rows.findIndex((row) => row === active || row.contains(active));
}

function focusRow(rows, index) {
  if (index < 0 || index >= rows.length) return;
  const link = rows[index].querySelector("a") || rows[index];
  link.focus();
}

function rowMeta(row) {
  return {
    id: row.dataset.ptRowId,
    expanded: row.dataset.ptExpanded === "true",
    expandable: row.dataset.ptExpandable === "true",
    parentId: row.dataset.ptParentId || null,
  };
}

export function handleTreeKeyDown(event, { onToggle }) {
  const treeEl = event.currentTarget;
  const rows = focusableRows(treeEl);
  if (rows.length === 0) return;

  const idx = currentIndex(rows);
  const cur = idx >= 0 ? rows[idx] : null;
  const meta = cur ? rowMeta(cur) : null;

  switch (event.key) {
    case "ArrowDown":
      event.preventDefault();
      focusRow(rows, idx + 1);
      return;

    case "ArrowUp":
      event.preventDefault();
      focusRow(rows, Math.max(0, idx - 1));
      return;

    case "Home":
      event.preventDefault();
      focusRow(rows, 0);
      return;

    case "End":
      event.preventDefault();
      focusRow(rows, rows.length - 1);
      return;

    case "ArrowRight": {
      if (!meta || !meta.expandable) return;
      event.preventDefault();
      if (!meta.expanded) {
        onToggle(Number(meta.id));
      } else {
        // Move to first child if visible.
        const childIdx = rows.findIndex(
          (r, i) => i > idx && rowMeta(r).parentId === meta.id,
        );
        if (childIdx !== -1) focusRow(rows, childIdx);
      }
      return;
    }

    case "ArrowLeft": {
      if (!meta) return;
      event.preventDefault();
      if (meta.expandable && meta.expanded) {
        onToggle(Number(meta.id));
      } else if (meta.parentId) {
        // Move focus to parent row.
        const parentIdx = rows.findIndex(
          (r) => rowMeta(r).id === meta.parentId,
        );
        if (parentIdx !== -1) focusRow(rows, parentIdx);
      }
      return;
    }

    default:
      return;
  }
}
