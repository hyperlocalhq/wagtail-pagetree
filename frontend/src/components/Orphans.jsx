import React, { memo } from "react";
import { gettext, t } from "../i18n.js";

// "Pages without [primary]" section. Renders the orphan_payload list
// from the tree response — translations the user can see whose primary
// counterpart is missing or denied.

const STATUS_LABELS = {
  published: gettext("Published"),
  changed: gettext("Changed"),
  draft: gettext("Draft"),
  alias: gettext("Alias"),
};

function Orphans({ orphans, primaryLocale }) {
  if (!orphans || orphans.length === 0) return null;
  return (
    <section className="pt-orphans">
      <h2 className="pt-orphans__title">
        {t.pagesWithoutPrimary} [{primaryLocale.toUpperCase()}]
      </h2>
      <ul className="pt-orphans__list">
        {orphans.map((o) => (
          <li key={o.id} className="pt-orphans__item">
            <a className="pt-orphans__link" href={o.edit_url}>
              <span className="pt-orphans__lang">{o.locale_code.toUpperCase()}</span>
              <span className="pt-orphans__title-text">{o.title}</span>
              <span className={`pt-orphans__status pt-orphans__status--${o.status}`}>
                {STATUS_LABELS[o.status] || o.status}
              </span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default memo(Orphans);
