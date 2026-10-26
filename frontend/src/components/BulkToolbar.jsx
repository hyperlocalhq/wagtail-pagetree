import React, { useEffect, useState } from "react";
import { gettext, interpolate, ngettext } from "../i18n.js";

// Sticky toolbar above the tree, only visible when at least one row is
// selected. Exposes a locale picker + Publish/Unpublish buttons so the
// editor explicitly chooses which locale's translations to act on.
//
// Scales to N locales without growing the button count: one <select>
// regardless of locale count.

function BulkToolbar({
  selectedCount,
  busy,
  locales,
  primaryLocale,
  onPublish,   // (localeCode) => void
  onUnpublish, // (localeCode) => void
  onClear,
}) {
  // Default the locale picker to the primary locale of the tree.
  const [localeCode, setLocaleCode] = useState(primaryLocale || "");

  useEffect(() => {
    if (!localeCode && primaryLocale) setLocaleCode(primaryLocale);
  }, [primaryLocale, localeCode]);

  if (selectedCount === 0) return null;

  const effective = localeCode || primaryLocale || (locales[0] && locales[0].code);

  return (
    <div className="pt-bulk" role="region" aria-label={gettext("Bulk actions")}>
      <span className="pt-bulk__count">
        {interpolate(
          ngettext("%s page selected", "%s pages selected", selectedCount),
          [selectedCount],
        )}
      </span>

      <label className="pt-bulk__field">
        <span className="pt-bulk__label">{gettext("Locale:")}</span>
        <select
          className="pt-bulk__select"
          value={effective || ""}
          disabled={busy}
          onChange={(e) => setLocaleCode(e.target.value)}
        >
          {locales.map((loc) => (
            <option key={loc.code} value={loc.code}>
              {loc.name} ({loc.code.toUpperCase()})
            </option>
          ))}
        </select>
      </label>

      <button
        type="button"
        className="pt-bulk__btn pt-bulk__btn--primary"
        disabled={busy || !effective}
        onClick={() => onPublish(effective)}
      >
        {gettext("Publish")}
      </button>
      <button
        type="button"
        className="pt-bulk__btn"
        disabled={busy || !effective}
        onClick={() => onUnpublish(effective)}
      >
        {gettext("Unpublish")}
      </button>
      <button
        type="button"
        className="pt-bulk__btn pt-bulk__btn--ghost"
        disabled={busy}
        onClick={onClear}
      >
        {gettext("Clear")}
      </button>
    </div>
  );
}

export default BulkToolbar;
