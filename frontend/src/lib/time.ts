// Time formatting in the USER's locale + timezone. Passing [] as the locale and
// omitting timeZone makes the browser use the visitor's own settings — so an
// Israeli user sees Israel time, not the "ET" that's baked into market titles.

export function localTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function localDateTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** The user's timezone label, e.g. "Asia/Jerusalem", for a small hint. */
export function tzLabel(): string {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch { return "local"; }
}
