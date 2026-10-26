import React, { memo } from "react";
import StatusDot from "./StatusDot.jsx";
import ContextMenu from "./ContextMenu.jsx";
import { highlight } from "../tree.js";
import { gettext, interpolate, t } from "../i18n.js";

// One row in the tree, laid out as columns:
//   [title (flex 1, indented by depth)] [LOC1] [LOC2] ... [Menu]
//
// Memoised — re-renders only when its own props change. Parent passes
// stable callbacks via useCallback so memo holds.

function Title({ value, query }) {
  const chunks = highlight(value || t.noTitle, query);
  return (
    <span className="pt-row__title-text">
      {chunks.map((c, i) =>
        c.kind === "match" ? (
          <mark key={i} className="pt-row__title-match">
            {c.value}
          </mark>
        ) : (
          <React.Fragment key={i}>{c.value}</React.Fragment>
        ),
      )}
    </span>
  );
}

// Six-dot grip glyph rendered before the expand toggle on draggable rows.
// Visible faintly by default and on row hover; the cursor flips to "grab"
// only here so the rest of the title doesn't compete with the title link.
function DragHandle() {
  return (
    <span
      className="pt-row__drag-handle"
      aria-hidden="true"
      title={gettext("Drag to reorder")}
    >
      <svg viewBox="0 0 8 14" width="8" height="14" fill="currentColor">
        <circle cx="2" cy="2" r="1" />
        <circle cx="6" cy="2" r="1" />
        <circle cx="2" cy="7" r="1" />
        <circle cx="6" cy="7" r="1" />
        <circle cx="2" cy="12" r="1" />
        <circle cx="6" cy="12" r="1" />
      </svg>
    </span>
  );
}

function ExpandToggle({ expanded, hasChildren, loading, onClick, nodeId }) {
  if (!hasChildren) return <span className="pt-row__toggle pt-row__toggle--leaf" aria-hidden="true" />;
  if (loading) return <span className="pt-row__toggle pt-row__toggle--loading" aria-hidden="true" />;
  return (
    <button
      type="button"
      className={`pt-row__toggle pt-row__toggle--${expanded ? "expanded" : "collapsed"}`}
      aria-expanded={expanded}
      aria-controls={`pt-children-${nodeId}`}
      aria-label={expanded ? t.collapseRow : t.expandRow}
      onClick={onClick}
    />
  );
}

function MenuCell({ shown }) {
  return (
    <span
      className="pt-row__cell pt-row__cell--menu"
      aria-label={shown ? gettext("Shown in menus") : gettext("Hidden from menus")}
      title={shown ? gettext("Shown in menus") : gettext("Hidden from menus")}
    >
      {shown ? "✓" : ""}
    </span>
  );
}

// Compute drop zone from mouseY relative to the row rect. Top third =
// before, bottom third = after, middle third = inside (nest as last child).
// Returns one of "before" | "after" | "inside".
function computeDropZone(event, rowEl) {
  const rect = rowEl.getBoundingClientRect();
  const offsetY = event.clientY - rect.top;
  const third = rect.height / 3;
  if (offsetY < third) return "before";
  if (offsetY > rect.height - third) return "after";
  return "inside";
}

// MIME type used to ferry the dragged page id through HTML5 DnD.
const DND_MIME = "application/x-pagetree-id";

function Node({
  node,
  locales,
  expanded,
  hasChildren,
  loading,
  searchQuery,
  onToggle,
  compact = false,
  selected = false,
  onSelectToggle,
  onSingleAction,
  dropZone = null,
  isDragging = false,
  dragSourceId = null,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDragLeaveRow,
  onMoveDrop,
}) {
  const handleToggle = () => onToggle(node.id);

  // Data attributes consumed by ../keyboard.js for arrow-key navigation.
  const dataAttrs = {
    "data-pt-row-id": node.id,
    "data-pt-parent-id": node.parent_id == null ? "" : node.parent_id,
    "data-pt-expandable": hasChildren ? "true" : "false",
    "data-pt-expanded": hasChildren && expanded ? "true" : "false",
  };

  if (node.is_placeholder) {
    return (
      <div
        className="pt-row pt-row--placeholder"
        role="treeitem"
        aria-level={node.depth}
        aria-expanded={hasChildren ? expanded : undefined}
        aria-busy={loading || undefined}
        {...dataAttrs}
      >
        <span className="pt-row__cell pt-row__cell--select" />
        <span className="pt-row__title-cell" style={{ "--pt-depth": node.depth }}>
          <ExpandToggle
            expanded={expanded}
            hasChildren={hasChildren}
            loading={loading}
            onClick={handleToggle}
            nodeId={node.id}
          />
          <span
            className="pt-row__title pt-row__title--placeholder"
            tabIndex={-1}
          >
            <Title value={node.title} query={searchQuery} />
          </span>
        </span>
        {!compact && <span className="pt-row__cell pt-row__cell--type" />}
        {locales.map((loc) => (
          <span key={loc.code} className="pt-row__cell pt-row__cell--locale" />
        ))}
        <span className="pt-row__cell pt-row__cell--menu" />
        <span className="pt-row__cell pt-row__cell--actions" />
      </div>
    );
  }

  const translations = node.translations || {};

  // DnD wiring. Only real (non-placeholder) editable rows are draggable
  // — root rows have parent_id=null (Wagtail root); we still let users
  // drag below depth 2 since reorder among top-level pages is valid.
  const draggable = !!onDragStart;
  const handleDragStart = (e) => {
    if (!onDragStart) return;
    e.dataTransfer.effectAllowed = "move";
    try {
      e.dataTransfer.setData(DND_MIME, String(node.id));
      // Some browsers (Firefox) require *something* on text/plain for
      // drag to actually start.
      e.dataTransfer.setData("text/plain", node.title || String(node.id));
    } catch (_err) {
      // Safari sometimes throws on non-text MIME during dragstart in
      // synthetic test environments; the dnd still proceeds.
    }
    onDragStart(node.id);
  };
  const handleDragOver = (e) => {
    if (dragSourceId == null || dragSourceId === node.id) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const zone = computeDropZone(e, e.currentTarget);
    onDragOver && onDragOver(node.id, zone);
  };
  const handleDragLeave = (e) => {
    // Ignore leaves that just go to a child element of this row.
    if (e.currentTarget.contains(e.relatedTarget)) return;
    onDragLeaveRow && onDragLeaveRow(node.id);
  };
  const handleDrop = (e) => {
    if (dragSourceId == null || dragSourceId === node.id) return;
    e.preventDefault();
    const zone = computeDropZone(e, e.currentTarget);
    onMoveDrop && onMoveDrop(dragSourceId, node.id, zone);
    onDragEnd && onDragEnd();
  };
  const handleDragEnd = () => {
    onDragEnd && onDragEnd();
  };

  const rowClass = [
    "pt-row",
    isDragging ? "pt-row--dragging" : "",
    dropZone ? `pt-row--drop-${dropZone}` : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={rowClass}
      role="treeitem"
      aria-level={node.depth}
      aria-expanded={hasChildren ? expanded : undefined}
      aria-busy={loading || undefined}
      draggable={draggable}
      onDragStart={draggable ? handleDragStart : undefined}
      onDragEnd={draggable ? handleDragEnd : undefined}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      {...dataAttrs}
    >
      <span className="pt-row__cell pt-row__cell--select">
        <input
          type="checkbox"
          className="pt-row__select"
          checked={selected}
          aria-label={interpolate(gettext("Select %s"), [node.title])}
          onChange={() => onSelectToggle && onSelectToggle(node.id)}
        />
      </span>
      <span className="pt-row__title-cell" style={{ "--pt-depth": node.depth }}>
        {draggable && <DragHandle />}
        <ExpandToggle
          expanded={expanded}
          hasChildren={hasChildren}
          loading={loading}
          onClick={handleToggle}
          nodeId={node.id}
        />
        <a
          className="pt-row__title"
          href={node.edit_url}
          title={node.page_type ? `${node.title} — ${node.page_type}` : node.title}
        >
          <Title value={node.title} query={searchQuery} />
        </a>
      </span>
      {!compact && (
        <span className="pt-row__cell pt-row__cell--type" title={node.page_type || ""}>
          {node.page_type || ""}
        </span>
      )}
      {locales.map((loc) => {
        const cell = translations[loc.code];
        return (
          <span key={loc.code} className="pt-row__cell pt-row__cell--locale">
            {cell ? (
              <StatusDot
                localeCode={loc.code}
                cell={cell}
                onSingleAction={onSingleAction}
              />
            ) : null}
          </span>
        );
      })}
      <MenuCell shown={node.show_in_menus} />
      <span className="pt-row__cell pt-row__cell--actions">
        <ContextMenu
          items={[
            { key: "add", label: gettext("Add child page"), href: node.add_child_url },
            { key: "edit", label: gettext("Edit"), href: node.edit_url },
            ...(node.view_url
              ? [{ key: "view", label: gettext("View live"), href: node.view_url, newTab: true }]
              : []),
            { key: "copy", label: gettext("Copy"), href: node.copy_url },
            { key: "div", divider: true },
            { key: "delete", label: gettext("Delete"), href: node.delete_url, danger: true },
          ]}
        />
      </span>
    </div>
  );
}

export default memo(Node);
