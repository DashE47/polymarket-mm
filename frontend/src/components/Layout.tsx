// App shell: fixed sidebar (brand, theme toggle, grouped nav, selection) + the
// routed page content with a subtle fade on each navigation.

import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useSelection } from "../state/SelectionContext";
import { useTheme } from "../state/ThemeContext";
import CommandPalette from "./CommandPalette";
import styles from "./Layout.module.css";

const GROUPS: { label: string; items: [string, string][] }[] = [
  { label: "Markets", items: [["/", "Home & Safety"], ["/explorer", "Market Explorer"], ["/book", "Live Order Book"]] },
  { label: "Strategy", items: [["/lab", "Strategy Lab"], ["/analytics", "Backtest & Analytics"], ["/sweep", "Parameter Sweep"]] },
  { label: "Research", items: [["/hdlab", "HD Lab"], ["/updown", "Up/Down Lab"]] },
  { label: "Data", items: [["/recorder", "Recorder"]] },
  { label: "Learn", items: [["/learn", "Glossary"]] },
  { label: "Trading", items: [["/trading", "Live Trading"]] },
];

export default function Layout() {
  const { market, outcome } = useSelection();
  const { theme, toggle } = useTheme();
  const location = useLocation();

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brandRow}>
          <span className={styles.brand}>Polymarket MM</span>
          <button className={styles.themeBtn} onClick={toggle} title="Toggle theme" aria-label="Toggle light/dark theme">
            {theme === "dark" ? "☀️" : "🌙"}
          </button>
        </div>
        <div className={styles.simBadge}>SIMULATION</div>

        <button className={styles.cmdBtn} onClick={() => window.dispatchEvent(new Event("open-cmdk"))}>
          <span>Search…</span>
          <kbd>⌘K</kbd>
        </button>

        {GROUPS.map((g) => (
          <nav key={g.label} className={styles.group}>
            <div className={styles.groupLabel}>{g.label}</div>
            {g.items.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"}
                className={({ isActive }) => `${styles.link} ${isActive ? styles.active : ""}`}>
                {label}
              </NavLink>
            ))}
          </nav>
        ))}

        <div className={styles.selection}>
          <div className="small muted">Selected market</div>
          {market ? (
            <div className={styles.selText}>{market.question} <span className="muted">[{outcome}]</span></div>
          ) : (
            <div className="small muted">none — pick one in Explorer</div>
          )}
        </div>
      </aside>

      <main className={styles.main}>
        <div className="page" key={location.pathname}>
          <Outlet />
        </div>
      </main>

      <CommandPalette />
    </div>
  );
}
