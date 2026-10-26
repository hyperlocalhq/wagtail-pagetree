import React, { memo, forwardRef } from "react";
import DotMenu from "./DotMenu.jsx";
import { gettext, interpolate } from "../i18n.js";

// One translation cell (a coloured dot per locale).
//
// Click → DotMenu with status-conditional actions:
//   Published → Edit / View live / Unpublish / Copy / Delete
//   Changed   → Edit / View live / Publish / Unpublish / Copy / Delete
//   Draft     → Edit / Publish / Copy / Delete
//   Alias     → Edit / View live / Convert to regular page / Delete
//   Empty     → Create translation here
//
// Publish / Unpublish are async — they call the parent-supplied
// `onSingleAction(pageId, action)` which goes through /api/bulk/.
// Other items are plain links to Wagtail admin URLs.
//
// Cells the user has no permission on (no page_id) render as a
// non-interactive span — same shape as before, just no menu.

const STATUS_LABELS = {
  published: gettext("Published"),
  changed: gettext("Changed (unpublished edits)"),
  draft: gettext("Draft"),
  alias: gettext("Alias"),
  empty: gettext("No translation"),
};

function buildTitle(localeCode, cell) {
  const loc = localeCode.toUpperCase();
  let base = `${loc}: ${STATUS_LABELS[cell.status] || cell.status}`;
  if (cell.outdated)
    base += ` — ${gettext("source changed since last sync; publish or sync the source page")}`;
  if (!cell.aligned) {
    // Diverged: name where it sits vs where the primary tree expects it.
    if (cell.diverged_from || cell.diverged_expected) {
      const from = cell.diverged_from || "—";
      const expected = cell.diverged_expected || "—";
      base += ` — ${interpolate(
        gettext("%(locale)s under “%(from)s”, expected under “%(expected)s”"),
        { locale: loc, from, expected },
        true,
      )}`;
    } else {
      base += ` (${gettext("translated parent differs")})`;
    }
  }
  return base;
}

// Menu items in display order; each entry is gated on the cell's status and
// on the backend having sent its URL. The wagtail-localize source actions
// ("Sync translated pages" when the page is a source with enabled
// translations, "Translate this page" when some locale has no translation
// yet) are only ever set on the *primary* (source) cell and sit right after
// Edit so they don't bury the link.
//
// Out-of-date deliberately adds NO menu item. wagtail-localize's
// `before_edit_page` hook renders the segment editor on the translation's own
// edit view, so "Edit" already is the update affordance — a second entry with
// the same href read as a distinct action but wasn't one. And when the
// staleness is snapshot drift (unpublished source edits) nothing on *this*
// cell can fix it; the source has to be published/synced. The amber dot, its
// tooltip, the legend and the "Needs update" filter carry the signal.
function buildMenuItems(cell) {
  const s = cell.status;
  const live = s === "published" || s === "changed";
  const page = live || s === "draft" || s === "alias";
  const item = (show, key, label, rest) => (show ? [{ key, label, ...rest }] : []);
  return [
    ...item(page && cell.edit_url, "edit", gettext("Edit"), { href: cell.edit_url }),
    ...item(cell.sync_translations_url, "sync", gettext("Sync translated pages"), {
      href: cell.sync_translations_url,
    }),
    ...item(cell.translate_page_url, "translate", gettext("Translate this page"), {
      href: cell.translate_page_url,
    }),
    ...item((live || s === "alias") && cell.view_url, "view", gettext("View live"), {
      href: cell.view_url,
      newTab: true,
    }),
    ...item(s === "changed" || s === "draft", "pub", gettext("Publish"), { action: "publish" }),
    ...item(live && cell.unpublish_url, "unpub", gettext("Unpublish"), { action: "unpublish" }),
    ...item(s === "alias" && cell.convert_alias_url, "convert", gettext("Convert to regular page"), {
      href: cell.convert_alias_url,
    }),
    ...item(page && s !== "alias" && cell.copy_url, "copy", gettext("Copy"), { href: cell.copy_url }),
    ...item(page && cell.delete_url, "del", gettext("Delete"), { href: cell.delete_url, danger: true }),
    ...item(s === "empty" && cell.create_translation_url, "create", gettext("Create translation here"), {
      href: cell.create_translation_url,
    }),
  ];
}

// Visual dot. Plain span when there are no actions; <button> when menuable
// so DotMenu can attach refs + onClick.
const DotShell = forwardRef(function DotShell(
  { className, title, onClick, "aria-haspopup": ahp, "aria-expanded": ae, asButton },
  ref,
) {
  if (asButton) {
    return (
      <button
        ref={ref}
        type="button"
        className={className}
        title={title}
        aria-label={title}
        aria-haspopup={ahp}
        aria-expanded={ae}
        onClick={onClick}
      />
    );
  }
  return <span ref={ref} className={className} title={title} aria-label={title} />;
});

function StatusDot({ localeCode, cell, onSingleAction }) {
  const className = [
    "pt-dot",
    `pt-dot--${cell.status}`,
    cell.aligned ? "" : "pt-dot--diverged",
    cell.outdated ? "pt-dot--outdated" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const title = buildTitle(localeCode, cell);
  const items = buildMenuItems(cell);

  // No actionable items (denied translation cell with no urls) → plain span.
  if (items.length === 0) {
    return <DotShell className={className} title={title} />;
  }

  const trigger = <DotShell className={className} title={title} asButton />;

  const handleRun = async (action) => {
    if (!onSingleAction || !cell.page_id) return;
    await onSingleAction(cell.page_id, action);
  };

  return <DotMenu trigger={trigger} items={items} onActionRun={handleRun} />;
}

export default memo(StatusDot);
