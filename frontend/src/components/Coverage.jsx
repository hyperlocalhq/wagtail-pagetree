import React, { memo } from "react";
import { gettext, interpolate, ngettext } from "../i18n.js";

// Translation coverage per other locale, between the toolbar and the tree:
// the share of tree rows that have a page in that locale, rounded down so
// 100% means nothing is missing. Each figure toggles the "Missing" status
// filter for its locale.

function Coverage({ locales, primaryLocale, coverage, filterLocale, filterStatus, onToggle }) {
  if (!coverage || !coverage.total) return null;
  const others = locales.filter((loc) => coverage.missing[loc.code] !== undefined);
  if (others.length === 0) return null;

  return (
    <div className="pt-coverage" role="group" aria-label={gettext("Translation coverage")}>
      <span className="pt-coverage__label">{gettext("Translated:")}</span>
      {others.map((loc) => {
        const missing = coverage.missing[loc.code];
        const percent = Math.floor((100 * (coverage.total - missing)) / coverage.total);
        const code = loc.code.toUpperCase();
        if (missing === 0) {
          return (
            <span
              key={loc.code}
              className="pt-coverage__item pt-coverage__item--complete"
              style={{ "--pt-percent": "100%" }}
              title={interpolate(gettext("No pages missing in %s"), [loc.name])}
            >
              {code} 100%
            </span>
          );
        }
        const active =
          filterStatus === "empty" && (filterLocale || primaryLocale) === loc.code;
        const title = active
          ? gettext("Show the whole tree again")
          : interpolate(
              ngettext(
                "%(count)s page missing in %(locale)s. Show it.",
                "%(count)s pages missing in %(locale)s. Show them.",
                missing,
              ),
              { count: missing, locale: loc.name },
              true,
            );
        return (
          <button
            key={loc.code}
            type="button"
            className="pt-coverage__item"
            aria-pressed={active}
            // Fills the pill's background up to the percentage.
            style={{ "--pt-percent": `${percent}%` }}
            title={title}
            onClick={() => onToggle(loc.code, !active)}
          >
            {code} {percent}% ·{" "}
            {interpolate(ngettext("%s missing", "%s missing", missing), [missing])}
          </button>
        );
      })}
    </div>
  );
}

export default memo(Coverage);
