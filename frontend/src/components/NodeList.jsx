import React from "react";
import Node from "./Node.jsx";

// Recursively render the tree from a parent_id. We don't render hidden
// branches at all — collapsed parents simply skip the recursion.

function NodeList({
  parentId,
  byParent,
  locales,
  expanded,
  loading,
  searchQuery,
  onToggle,
  compact = false,
  selectedIds,
  onSelectToggle,
  onSingleAction,
  dragSourceId,
  dragOver,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDragLeaveRow,
  onMoveDrop,
}) {
  const children = byParent.get(parentId) || [];
  if (children.length === 0) return null;

  return (
    <div
      className="pt-list"
      id={parentId == null ? "pt-children-root" : `pt-children-${parentId}`}
      role={parentId == null ? "tree" : "group"}
    >
      {children.map((node) => {
        const isExpanded = expanded.has(node.id);
        const isLoading = loading.has(node.id);
        const hasKids =
          (byParent.get(node.id) || []).length > 0 || node.visible_numchild > 0;
        // Per-row dropZone is computed here (outside Node) so memoised
        // Nodes only re-render when their *own* zone toggles.
        const dropZone =
          dragOver && dragOver.id === node.id ? dragOver.position : null;
        const isDragging = dragSourceId === node.id;

        return (
          <React.Fragment key={node.id}>
            <Node
              node={node}
              locales={locales}
              expanded={isExpanded}
              hasChildren={hasKids}
              loading={isLoading}
              searchQuery={searchQuery}
              onToggle={onToggle}
              compact={compact}
              selected={selectedIds ? selectedIds.has(node.id) : false}
              onSelectToggle={onSelectToggle}
              onSingleAction={onSingleAction}
              dropZone={dropZone}
              isDragging={isDragging}
              dragSourceId={dragSourceId}
              onDragStart={onDragStart}
              onDragEnd={onDragEnd}
              onDragOver={onDragOver}
              onDragLeaveRow={onDragLeaveRow}
              onMoveDrop={onMoveDrop}
            />
            {isExpanded && (
              <NodeList
                parentId={node.id}
                byParent={byParent}
                locales={locales}
                expanded={expanded}
                loading={loading}
                searchQuery={searchQuery}
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
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

export default NodeList;
