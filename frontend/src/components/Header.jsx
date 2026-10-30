import React, { memo } from "react";
import { gettext, interpolate, ngettext } from "../i18n.js";

// Sticky column header above the tree. Mirrors the per-row column shape
// from Node.jsx so locale dots and menu marks line up vertically.

// Share of tree rows that have a page in `code`, under its column code.
// Rounded down, so 100% means nothing is missing. Clicking lists the
// missing pages through the status filter.
function Coverage({ code, name, coverage, onShowMissing }) {
  const missing = coverage.missing[code];
  if (missing === undefined || !coverage.total) return null;
  if (missing === 0) {
    return (
      <span
        className="pt-coverage pt-coverage--complete"
        title={interpolate(gettext("No pages missing in %s"), [name])}
      >
        100%
      </span>
    );
  }
  const percent = Math.floor((100 * (coverage.total - missing)) / coverage.total);
  const label = interpolate(
    ngettext(
      "%(count)s page missing in %(locale)s. Show it.",
      "%(count)s pages missing in %(locale)s. Show them.",
      missing,
    ),
    { count: missing, locale: name },
    true,
  );
  return (
    <button
      type="button"
      className="pt-coverage"
      title={label}
      aria-label={label}
      onClick={() => onShowMissing(code)}
    >
      {percent}%
    </button>
  );
}

function Header({ locales, compact = false, primaryLocale, coverage, onShowMissing }) {
  return (
    <div className="pt-row pt-row--header" role="row">
      <span className="pt-row__cell pt-row__cell--select" aria-hidden="true" />
      <span className="pt-row__title-cell pt-row__title-cell--header">
        <span className="pt-row__title-text">{gettext("Title")}</span>
      </span>
      {!compact && <span className="pt-row__cell pt-row__cell--type">{gettext("Type")}</span>}
      {locales.map((loc) => (
        <span key={loc.code} className="pt-row__cell pt-row__cell--locale">
          <span title={loc.name}>{loc.code.toUpperCase()}</span>
          {coverage && loc.code !== primaryLocale && (
            <Coverage
              code={loc.code}
              name={loc.name}
              coverage={coverage}
              onShowMissing={onShowMissing}
            />
          )}
        </span>
      ))}
      <span className="pt-row__cell pt-row__cell--menu">{gettext("Menu")}</span>
      <span className="pt-row__cell pt-row__cell--actions" aria-hidden="true" />
    </div>
  );
}

export default memo(Header);
