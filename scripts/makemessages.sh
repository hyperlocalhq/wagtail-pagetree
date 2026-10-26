#!/usr/bin/env bash
# Re-extract translatable strings into src/wagtail_pagetree/locale/<lang>/.
#
# - django.po:   Python + templates, via Django's makemessages.
# - djangojs.po: frontend/src. xgettext can't parse JSX, so each file is
#   first transformed to plain JS with esbuild, then extracted and merged.
#
# Usage: scripts/makemessages.sh [lang ...]   (default: every existing locale)
# Afterwards: translate the new msgids, then run with --compile.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/src/wagtail_pagetree"
LOCALE="$APP/locale"

compile() {
    for po in "$LOCALE"/*/LC_MESSAGES/*.po; do
        msgfmt -c --statistics -o "${po%.po}.mo" "$po"
    done
}

main() {
    if [[ "${1:-}" == "--compile" ]]; then
        compile
        return
    fi

    local langs=("$@")
    if [[ ${#langs[@]} -eq 0 ]]; then
        mapfile -t langs < <(find "$LOCALE" -mindepth 1 -maxdepth 1 -type d -printf '%f\n')
    fi

    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT

    (
        cd "$APP"
        for lang in "${langs[@]}"; do
            uv run --project "$ROOT" django-admin makemessages \
                --settings=tests.settings --pythonpath="$ROOT" \
                -l "$lang" -d django --ignore='static/*' --no-obsolete
        done
    )

    (
        cd "$ROOT"
        find frontend/src -name '*.js' -o -name '*.jsx' | while read -r src; do
            mkdir -p "$tmp/$(dirname "$src")"
            npx --prefix frontend esbuild "$src" --jsx=transform --log-level=warning \
                --outfile="$tmp/$src"
        done
        cd "$tmp"
        find frontend/src -name '*.js' -o -name '*.jsx' | sort | xargs xgettext \
            --language=JavaScript --from-code=UTF-8 --add-location=file \
            --keyword=gettext --keyword=ngettext:1,2 --keyword=pgettext:1c,2 \
            -o "$tmp/djangojs.pot"
    )

    for lang in "${langs[@]}"; do
        local po="$LOCALE/$lang/LC_MESSAGES/djangojs.po"
        if [[ -f "$po" ]]; then
            msgmerge --quiet --update --backup=none --no-fuzzy-matching "$po" "$tmp/djangojs.pot"
        else
            msginit --no-translator -l "$lang" -i "$tmp/djangojs.pot" -o "$po"
        fi
    done
}

main "$@"
