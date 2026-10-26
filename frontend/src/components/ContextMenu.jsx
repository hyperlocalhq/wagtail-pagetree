import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { gettext } from "../i18n.js";

// Per-row three-dot popover. Portalled to document.body so it escapes any
// ancestor `overflow: hidden` (notably .pt-table). Position is computed
// from the trigger's bounding rect on open and on scroll/resize.
//
// Menu opens DOWNWARD when there's room below the trigger, otherwise UPWARD
// — so rows near the bottom of the viewport don't clip.
//
// Dismiss: outside click or Escape (same pattern as the legend).

const MENU_GAP = 4;
const MENU_WIDTH = 180;
const MIN_BOTTOM_SPACE = 200; // if less than this below the trigger, flip up

function ContextMenu({ items }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);
  const triggerRef = useRef(null);
  const listRef = useRef(null);

  const recompute = useCallback(() => {
    if (!triggerRef.current) return;
    const r = triggerRef.current.getBoundingClientRect();
    const flipUp =
      window.innerHeight - r.bottom < MIN_BOTTOM_SPACE && r.top > MIN_BOTTOM_SPACE;
    setPos({
      top: flipUp ? r.top - MENU_GAP : r.bottom + MENU_GAP,
      // Right-anchor: place the menu's right edge under the trigger's right edge.
      left: r.right - MENU_WIDTH,
      flipUp,
    });
  }, []);

  // Outside click + Escape + scroll/resize repositioning while open.
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

  // Recompute when the popover content first paints (so flip-up uses the
  // measured height without a visible flash).
  useLayoutEffect(() => {
    if (open) recompute();
  }, [open, recompute]);

  const trigger = (
    <button
      ref={triggerRef}
      type="button"
      className="pt-menu__trigger"
      aria-haspopup="menu"
      aria-expanded={open}
      aria-label={gettext("Page actions")}
      title={gettext("Page actions")}
      onClick={() => setOpen((v) => !v)}
    >
      <svg
        viewBox="0 0 16 16"
        width="14"
        height="14"
        aria-hidden="true"
        fill="currentColor"
      >
        <circle cx="8" cy="3" r="1.4" />
        <circle cx="8" cy="8" r="1.4" />
        <circle cx="8" cy="13" r="1.4" />
      </svg>
    </button>
  );

  if (!open || !pos) return trigger;

  const popover = (
    <ul
      ref={listRef}
      className="pt-menu__list"
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
        // Skip non-divider items whose href is missing — defends against
        // stale payloads served before the backend exposed the URL field.
        // The user sees a smaller menu rather than a no-op click.
        .filter((it) => it.divider || it.href)
        .map((it) =>
          it.divider ? (
            <li key={it.key} className="pt-menu__divider" role="separator" />
          ) : (
            <li key={it.key} role="none">
              <a
                className={`pt-menu__item${it.danger ? " pt-menu__item--danger" : ""}`}
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
      {trigger}
      {ReactDOM.createPortal(popover, document.body)}
    </>
  );
}

export default ContextMenu;
