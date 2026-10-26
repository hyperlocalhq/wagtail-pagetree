import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import ReactDOM from "react-dom";

// Per-translation-cell popover. Same portal pattern as ContextMenu so the
// menu escapes the .pt-table's `overflow: hidden` and isn't clipped at
// the viewport edges.
//
// Items can be either plain links (Edit / View live / Copy / Delete /
// Convert alias / Create translation) or async actions (Publish /
// Unpublish — call /api/bulk/ via the parent-supplied callback).

const MENU_GAP = 4;
const MENU_WIDTH = 200;
const MIN_BOTTOM_SPACE = 200;

function DotMenu({ trigger, items, onActionRun }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const [busy, setBusy] = useState(false);
  const triggerRef = useRef(null);
  const listRef = useRef(null);

  const recompute = useCallback(() => {
    if (!triggerRef.current) return;
    const r = triggerRef.current.getBoundingClientRect();
    const flipUp =
      window.innerHeight - r.bottom < MIN_BOTTOM_SPACE && r.top > MIN_BOTTOM_SPACE;
    setPos({
      top: flipUp ? r.top - MENU_GAP : r.bottom + MENU_GAP,
      left: Math.max(8, r.right - MENU_WIDTH),
      flipUp,
    });
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (e) => {
      const t = triggerRef.current;
      const l = listRef.current;
      if (t && t.contains(e.target)) return;
      if (l && l.contains(e.target)) return;
      setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", recompute, true);
    window.addEventListener("resize", recompute);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", recompute, true);
      window.removeEventListener("resize", recompute);
    };
  }, [open, recompute]);

  useLayoutEffect(() => {
    if (open) recompute();
  }, [open, recompute]);

  // Keep the originating row visually "hovered" while the menu is open —
  // the popover is portalled to <body>, so moving the mouse off the row to
  // the menu would otherwise drop the row's :hover background.
  useEffect(() => {
    const row = triggerRef.current && triggerRef.current.closest(".pt-row");
    if (!row) return undefined;
    if (open) row.classList.add("pt-row--menu-active");
    else row.classList.remove("pt-row--menu-active");
    return () => row.classList.remove("pt-row--menu-active");
  }, [open]);

  const handleAction = async (item) => {
    if (item.action && onActionRun) {
      setBusy(true);
      try {
        await onActionRun(item.action);
      } finally {
        setBusy(false);
        setOpen(false);
      }
    } else {
      setOpen(false);
    }
  };

  const triggerEl = React.cloneElement(trigger, {
    ref: triggerRef,
    onClick: (e) => {
      e.preventDefault();
      e.stopPropagation();
      setOpen((v) => !v);
    },
    "aria-haspopup": "menu",
    "aria-expanded": open,
  });

  if (!open || !pos) return triggerEl;

  const menu = (
    <ul
      ref={listRef}
      className="pt-dotmenu"
      role="menu"
      style={{
        position: "fixed",
        top: pos.flipUp ? "auto" : pos.top,
        bottom: pos.flipUp ? window.innerHeight - pos.top : "auto",
        left: pos.left,
        width: MENU_WIDTH,
      }}
    >
      {items
        .filter((it) => it.divider || it.href || it.action)
        .map((it, idx) =>
          it.divider ? (
            <li key={`d-${idx}`} className="pt-dotmenu__divider" role="separator" />
          ) : it.action ? (
            <li key={it.key} role="none">
              <button
                type="button"
                className={`pt-dotmenu__item${it.danger ? " pt-dotmenu__item--danger" : ""}`}
                role="menuitem"
                disabled={busy}
                onClick={() => handleAction(it)}
              >
                {it.label}
              </button>
            </li>
          ) : (
            <li key={it.key} role="none">
              <a
                className={`pt-dotmenu__item${it.danger ? " pt-dotmenu__item--danger" : ""}`}
                href={it.href}
                role="menuitem"
                target={it.newTab ? "_blank" : undefined}
                rel={it.newTab ? "noopener noreferrer" : undefined}
                onClick={() => setOpen(false)}
              >
                {it.label}
              </a>
            </li>
          ),
        )}
    </ul>
  );

  return (
    <>
      {triggerEl}
      {ReactDOM.createPortal(menu, document.body)}
    </>
  );
}

export default DotMenu;
