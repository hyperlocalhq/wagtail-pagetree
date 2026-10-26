import React, { memo, useEffect, useRef, useState } from "react";
import { gettext } from "../i18n.js";

// Collapsible legend explaining what each dot variant means. Floats fixed
// in the bottom-right corner. Default collapsed (small toggle button only)
// so it doesn't hide content; click to expand.

const ITEMS = [
  { status: "published", label: gettext("Published — live, no pending edits") },
  { status: "changed", label: gettext("Changed — live, but has unpublished edits") },
  { status: "draft", label: gettext("Draft — never been published") },
  { status: "alias", label: gettext("Alias — points to another page (no own content)") },
  { status: "empty", label: gettext("Missing — no translation in this locale") },
  { status: "published", label: gettext("Diverged — parent page differs from primary tree"), diverged: true },
  { status: "published", label: gettext("Needs update — source changed since last translation"), outdated: true },
];

function Swatch({ status, diverged, outdated }) {
  const cls = [
    "pt-dot",
    `pt-dot--${status}`,
    diverged ? "pt-dot--diverged" : "",
    outdated ? "pt-dot--outdated" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return <span className={cls} aria-hidden="true" />;
}

function Legend() {
  const [open, setOpen] = useState(false);
  const panelRef = useRef(null);

  // Close on outside click or Escape. Listeners are only attached while
  // the panel is open so the closed state has zero overhead.
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!open) {
    return (
      <button
        type="button"
        className="pt-legend-toggle"
        onClick={() => setOpen(true)}
        aria-label={gettext("Show status legend")}
        aria-expanded={false}
        title={gettext("Show status legend")}
      >
        ?
      </button>
    );
  }

  return (
    <aside className="pt-legend" aria-label={gettext("Status legend")} ref={panelRef}>
      <button
        type="button"
        className="pt-legend__close"
        onClick={() => setOpen(false)}
        aria-label={gettext("Hide status legend")}
        title={gettext("Hide")}
      >
        ×
      </button>
      <ul className="pt-legend__list">
        {ITEMS.map((it, i) => (
          <li key={i} className="pt-legend__item">
            <Swatch status={it.status} diverged={it.diverged} outdated={it.outdated} />
            <span className="pt-legend__label">{it.label}</span>
          </li>
        ))}
      </ul>
    </aside>
  );
}

export default memo(Legend);
