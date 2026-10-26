import React, { memo } from "react";
import { gettext } from "../i18n.js";

// Sticky column header above the tree. Mirrors the per-row column shape
// from Node.jsx so locale dots and menu marks line up vertically.

function Header({ locales, compact = false }) {
  return (
    <div className="pt-row pt-row--header" role="row">
      <span className="pt-row__cell pt-row__cell--select" aria-hidden="true" />
      <span className="pt-row__title-cell pt-row__title-cell--header">
        <span className="pt-row__title-text">{gettext("Title")}</span>
      </span>
      {!compact && <span className="pt-row__cell pt-row__cell--type">{gettext("Type")}</span>}
      {locales.map((loc) => (
        <span key={loc.code} className="pt-row__cell pt-row__cell--locale" title={loc.name}>
          {loc.code.toUpperCase()}
        </span>
      ))}
      <span className="pt-row__cell pt-row__cell--menu">{gettext("Menu")}</span>
      <span className="pt-row__cell pt-row__cell--actions" aria-hidden="true" />
    </div>
  );
}

export default memo(Header);
