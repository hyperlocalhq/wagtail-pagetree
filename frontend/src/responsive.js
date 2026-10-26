// Tiny matchMedia-based hook. Returns true when the viewport matches the
// given breakpoint query. Used to drop wide-only columns (Type) on
// tablet-sized screens so the title stays readable.

import { useEffect, useState } from "react";

export function useMatchMedia(query) {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return undefined;
    const mq = window.matchMedia(query);
    const onChange = (e) => setMatches(e.matches);
    setMatches(mq.matches);
    // Older Safari uses addListener; newer browsers expose addEventListener.
    if (mq.addEventListener) {
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    }
    mq.addListener(onChange);
    return () => mq.removeListener(onChange);
  }, [query]);

  return matches;
}

// Single breakpoint for the pagetree's compact mode.
export const COMPACT_QUERY = "(max-width: 900px)";
