import React, { memo } from "react";
import { gettext, t } from "../i18n.js";

// Locale dropdown + search input + page-type filter + locale×status filter.
// Stateless — parent owns the values and forwards onChange callbacks.
// Memoised so it doesn't repaint on every node toggle.

// The five base statuses plus the two orthogonal flags. Mirrors the backend
// FILTER_STATUSES set; "empty" reads as "Missing" in the UI.
const FILTER_STATUS_OPTIONS = [
  { value: "published", label: gettext("Published") },
  { value: "changed", label: gettext("Changed") },
  { value: "draft", label: gettext("Draft") },
  { value: "alias", label: gettext("Alias") },
  { value: "empty", label: gettext("Missing") },
  { value: "outdated", label: gettext("Needs update") },
  { value: "diverged", label: gettext("Diverged") },
];

function Toolbar({
  locales,
  primaryLocale,
  searchQuery,
  pageTypes,
  filterPageType,
  filterLocale,
  filterStatus,
  onLocaleChange,
  onSearchChange,
  onFilterPageTypeChange,
  onFilterLocaleChange,
  onFilterStatusChange,
}) {
  return (
    <div className="pt-toolbar" role="toolbar" aria-label={t.pageTree}>
      <label className="pt-toolbar__field">
        <span className="pt-toolbar__label">{t.primaryLocale}</span>
        <select
          className="pt-toolbar__select"
          value={primaryLocale}
          onChange={(e) => onLocaleChange(e.target.value)}
        >
          {locales.map((loc) => (
            <option key={loc.code} value={loc.code}>
              {loc.name} ({loc.code.toUpperCase()})
            </option>
          ))}
        </select>
      </label>
      <label className="pt-toolbar__field pt-toolbar__field--grow">
        <span className="pt-toolbar__label pt-toolbar__label--sr-only">
          {t.searchPlaceholder}
        </span>
        <input
          className="pt-toolbar__input"
          type="search"
          placeholder={t.searchPlaceholder}
          value={searchQuery}
          maxLength={200}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </label>
      {/* Page-type filter: combines with the text search or the status
          filter below. "" = all types. */}
      <label className="pt-toolbar__field">
        <span className="pt-toolbar__label">{t.pageTypeLabel}</span>
        <select
          className="pt-toolbar__select"
          value={filterPageType}
          onChange={(e) => onFilterPageTypeChange(e.target.value)}
        >
          <option value="">{t.pageTypeAll}</option>
          {pageTypes.map((pt) => (
            <option key={pt.id} value={String(pt.id)}>
              {pt.name}
            </option>
          ))}
        </select>
      </label>
      {/* Locale×status filter: show only pages whose chosen-locale
          cell has the chosen status. Status "" = off (the locale select is
          then inert). Mutually exclusive with the text search. */}
      <label className="pt-toolbar__field">
        <span className="pt-toolbar__label">{t.filterStatusLabel}</span>
        <select
          className="pt-toolbar__select"
          value={filterStatus}
          onChange={(e) => onFilterStatusChange(e.target.value)}
        >
          <option value="">{t.filterStatusOff}</option>
          {FILTER_STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>
      <label className="pt-toolbar__field">
        <span className="pt-toolbar__label pt-toolbar__label--sr-only">
          {t.filterLocaleLabel}
        </span>
        <select
          className="pt-toolbar__select"
          value={filterLocale}
          disabled={!filterStatus}
          aria-label={t.filterLocaleLabel}
          onChange={(e) => onFilterLocaleChange(e.target.value)}
        >
          {locales.map((loc) => (
            <option key={loc.code} value={loc.code}>
              {t.filterInLocale} {loc.code.toUpperCase()}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

export default memo(Toolbar);
