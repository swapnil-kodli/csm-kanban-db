import { useEffect, useRef, useState } from "react";
import { Search, SlidersHorizontal, Plus, AlertTriangle, X } from "lucide-react";
import type { BoardView, Filters, GroupBy, Metric, SavedView } from "../lib/types";
import { inr } from "../lib/format";

const VIEW_TABS: { key: BoardView; label: string; hint: string }[] = [
  { key: "work", label: "My Work", hint: "1" },
  { key: "health", label: "Health", hint: "2" },
  { key: "lifecycle", label: "Lifecycle", hint: "3" },
];

const GROUP_OPTIONS: { key: GroupBy; label: string }[] = [
  { key: "none", label: "No swimlanes" },
  { key: "priority", label: "Priority" },
  { key: "segment", label: "Account segment" },
  { key: "renewal_month", label: "Renewal month" },
];

interface TopBarProps {
  user: { name: string; initials: string; avatar_color: string } | null;
  source: "live" | "local";
  view: BoardView;
  groupBy: GroupBy;
  filters: Filters;
  searchRef: React.RefObject<HTMLInputElement>;
  onView: (v: BoardView) => void;
  onGroupBy: (g: GroupBy) => void;
  onFilters: (f: Filters) => void;
  onOpenPalette: () => void;
  onNewTask: () => void;
}

export function TopBar({
  user, source, view, groupBy, filters, searchRef, onView, onGroupBy, onFilters, onOpenPalette, onNewTask,
}: TopBarProps) {
  const [panelOpen, setPanelOpen] = useState(false);
  const activeCount = countFilters(filters);

  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">S</span>
        <span className="brand-text">
          <span className="brand-name">Signal CS</span>
          <span className="brand-src">
            <span className={`src-dot ${source}`} aria-hidden="true" />
            {source === "live" ? "Live" : "Local"}
          </span>
        </span>
      </div>

      <div className="search-box">
        <Search size={14} className="search-icon" strokeWidth={2.2} />
        <input
          ref={searchRef}
          type="text"
          placeholder="Search accounts, contacts, tasks…"
          aria-label="Search"
          onFocus={onOpenPalette}
          readOnly
        />
        <kbd>⌘K</kbd>
      </div>

      <div className="tabs" role="group" aria-label="Board view">
        {VIEW_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className="tab"
            aria-pressed={view === tab.key}
            title={`${tab.label} (${tab.hint})`}
            onClick={() => onView(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="topbar-right">
        <select
          className="btn"
          aria-label="Group by"
          value={groupBy}
          onChange={(e) => onGroupBy(e.target.value as GroupBy)}
          title="Swimlanes (g)"
        >
          {GROUP_OPTIONS.map((g) => (
            <option key={g.key} value={g.key}>{g.label}</option>
          ))}
        </select>

        <div style={{ position: "relative" }}>
          <button type="button" className="btn" aria-pressed={panelOpen} onClick={() => setPanelOpen((v) => !v)}>
            <SlidersHorizontal size={14} strokeWidth={2.2} />
            Filters{activeCount ? ` · ${activeCount}` : ""}
          </button>
          {panelOpen && (
            <FilterPanel filters={filters} onFilters={onFilters} onClose={() => setPanelOpen(false)} />
          )}
        </div>

        <button type="button" className="btn primary" onClick={onNewTask} title="New task (c)">
          <Plus size={14} strokeWidth={2.4} />
          Task
        </button>

        {user && (
          <span className="avatar" style={{ background: user.avatar_color }} title={user.name}>
            {user.initials}
          </span>
        )}
      </div>
    </header>
  );
}

function countFilters(f: Filters): number {
  return Object.entries(f).filter(([, v]) =>
    Array.isArray(v) ? v.length > 0 : v !== undefined && v !== false && v !== ""
  ).length;
}

/** Ranked in decision-value order (spec §6). Do not reshuffle alphabetically. */
function FilterPanel({ filters, onFilters, onClose }: { filters: Filters; onFilters: (f: Filters) => void; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [onClose]);

  function toggleIn<K extends keyof Filters>(key: K, value: string) {
    const list = (filters[key] as string[] | undefined) ?? [];
    const next = list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
    onFilters({ ...filters, [key]: next.length ? next : undefined });
  }

  return (
    <div className="popover" ref={ref} role="dialog" aria-label="Filters">
      <Group label="1 · Health band">
        <div className="popover-chips">
          {(["healthy", "watch", "at_risk", "critical"] as const).map((b) => (
            <button key={b} type="button" className="chip" aria-pressed={filters.bands?.includes(b) ?? false} onClick={() => toggleIn("bands", b)}>
              {b.replace("_", " ")}
            </button>
          ))}
        </div>
      </Group>

      <Group label="2 · Renewal window">
        <div className="popover-chips">
          {[30, 60, 90].map((w) => (
            <button key={w} type="button" className="chip" aria-pressed={filters.renewal_window === w}
              onClick={() => onFilters({ ...filters, renewal_window: filters.renewal_window === w ? undefined : w })}>
              {w} days
            </button>
          ))}
          <button type="button" className="chip" aria-pressed={filters.renewal_window === undefined}
            onClick={() => onFilters({ ...filters, renewal_window: undefined })}>
            None
          </button>
        </div>
      </Group>

      <Group label="3 · ARR range">
        <div className="popover-chips">
          {[{ l: "≥ ₹10 L", v: 1000000 }, { l: "≥ ₹5 L", v: 500000 }].map((o) => (
            <button key={o.v} type="button" className="chip" aria-pressed={filters.arr_min === o.v}
              onClick={() => onFilters({ ...filters, arr_min: filters.arr_min === o.v ? undefined : o.v })}>
              {o.l}
            </button>
          ))}
        </div>
      </Group>

      <Group label="4 · Owner">
        <div className="popover-chips">
          <button type="button" className="chip" aria-pressed disabled title="Single-CSM MVP">
            My book
          </button>
        </div>
      </Group>

      <Group label="5 · Lifecycle stage">
        <div className="popover-chips">
          {["ready_for_onboarding", "onboarding", "adopting", "healthy", "renewal", "closed"].map((s) => (
            <button key={s} type="button" className="chip" aria-pressed={filters.stages?.includes(s) ?? false} onClick={() => toggleIn("stages", s)}>
              {s.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      </Group>

      <Group label="6 · Task status">
        <div className="popover-chips">
          {["open", "done"].map((s) => (
            <button key={s} type="button" className="chip" aria-pressed={filters.task_status === s}
              onClick={() => onFilters({ ...filters, task_status: filters.task_status === s ? undefined : s })}>
              {s}
            </button>
          ))}
        </div>
      </Group>

      <Group label="7 · Last contact">
        <div className="popover-chips">
          {[14, 21, 30].map((d) => (
            <button key={d} type="button" className="chip" aria-pressed={filters.last_contact_gt === d}
              onClick={() => onFilters({ ...filters, last_contact_gt: filters.last_contact_gt === d ? undefined : d })}>
              &gt; {d} days
            </button>
          ))}
        </div>
      </Group>

      <Group label="8 · Priority">
        <div className="popover-chips">
          {["critical", "high", "normal"].map((p) => (
            <button key={p} type="button" className="chip" aria-pressed={filters.priorities?.includes(p) ?? false} onClick={() => toggleIn("priorities", p)}>
              {p}
            </button>
          ))}
        </div>
      </Group>

      <Group label="9 · Segment">
        <div className="popover-chips">
          {["enterprise", "mid_market", "smb"].map((s) => (
            <button key={s} type="button" className="chip" aria-pressed={filters.segments?.includes(s) ?? false} onClick={() => toggleIn("segments", s)}>
              {s.replace("_", " ")}
            </button>
          ))}
        </div>
      </Group>

      <Group label="10 · Tags">
        <span style={{ fontSize: 11.5, color: "var(--text-3)" }}>No tags in this book yet.</span>
      </Group>

      <div className="dialog-actions">
        <button type="button" className="btn subtle" onClick={() => onFilters({})}>Clear all</button>
        <button type="button" className="btn" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="popover-group">
      <span className="side-label">{label}</span>
      {children}
    </div>
  );
}

interface MetricsProps {
  metrics: Metric[];
  activeKey: string | null;
  onApply: (m: Metric) => void;
}

export function MetricsStrip({ metrics, activeKey, onApply }: MetricsProps) {
  return (
    <div className="metrics" role="group" aria-label="My book">
      {metrics.map((m) => (
        <button
          key={m.key}
          type="button"
          className="metric"
          aria-pressed={activeKey === m.key}
          onClick={() => onApply(m)}
        >
          <div className="metric-value">{m.format === "inr" ? inr(m.value) : m.value}</div>
          <div className="metric-label">{m.label}</div>
          <div className="metric-sub">
            {m.sub_format === "inr_at_stake" && m.sub_value !== undefined
              ? `${inr(m.sub_value)} ${m.sub}`
              : m.sub}
          </div>
        </button>
      ))}
    </div>
  );
}

const QUICK_FILTERS: { key: string; label: string; patch: Filters }[] = [
  { key: "mine", label: "Only my accounts", patch: {} },
  { key: "at_risk", label: "At risk", patch: { bands: ["at_risk", "critical"] } },
  { key: "renewals_30", label: "Renewals 30d", patch: { renewal_window: 30 } },
  { key: "no_contact", label: "No contact 14d", patch: { last_contact_gt: 14 } },
  { key: "overdue", label: "Overdue", patch: { overdue: true } },
  { key: "onboarding", label: "Onboarding", patch: { stages: ["ready_for_onboarding", "onboarding"] } },
  { key: "expansion", label: "Expansion", patch: { expansion: true } },
  { key: "high_value", label: "High value", patch: { high_value: true } },
];

interface QuickFiltersProps {
  filters: Filters;
  savedViews: SavedView[];
  activeView: string | null;
  onFilters: (f: Filters) => void;
  onSavedView: (v: SavedView | null) => void;
}

export function QuickFilters({ filters, savedViews, activeView, onFilters, onSavedView }: QuickFiltersProps) {
  const pinned = savedViews.filter((v) => v.pinned);
  const rest = savedViews.filter((v) => !v.pinned);
  const [showAll, setShowAll] = useState(false);

  function isActive(patch: Filters): boolean {
    return Object.entries(patch).every(([k, v]) => {
      const current = (filters as Record<string, unknown>)[k];
      if (Array.isArray(v)) return Array.isArray(current) && v.every((x) => (current as string[]).includes(x));
      return current === v;
    }) && Object.keys(patch).length > 0;
  }

  function toggle(patch: Filters) {
    if (isActive(patch)) {
      const next = { ...filters };
      Object.keys(patch).forEach((k) => delete (next as Record<string, unknown>)[k]);
      onFilters(next);
    } else {
      onFilters({ ...filters, ...patch });
    }
  }

  const views = showAll ? savedViews : pinned;

  return (
    <div className="qfilters">
      <span className="qf-label">Views</span>
      {views.map((v) => (
        <button key={v.id} type="button" className="chip" aria-pressed={activeView === v.id} onClick={() => onSavedView(activeView === v.id ? null : v)}>
          {v.name}
        </button>
      ))}
      {rest.length > 0 && (
        <button type="button" className="chip" onClick={() => setShowAll((s) => !s)}>
          {showAll ? "Fewer" : `+${rest.length} more`}
        </button>
      )}

      <span className="qf-divider" />

      {QUICK_FILTERS.map((qf) => (
        <button
          key={qf.key}
          type="button"
          className="chip"
          aria-pressed={qf.key === "mine" ? true : isActive(qf.patch)}
          disabled={qf.key === "mine"}
          title={qf.key === "mine" ? "Single-CSM MVP — every account is yours" : undefined}
          onClick={() => qf.key !== "mine" && toggle(qf.patch)}
        >
          {qf.label}
        </button>
      ))}

      {countFilters(filters) > 0 && (
        <>
          <span className="qf-divider" />
          <button type="button" className="chip" onClick={() => { onFilters({}); onSavedView(null); }}>
            <X size={12} strokeWidth={2.4} /> Clear
          </button>
        </>
      )}
    </div>
  );
}

export function DegradedBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="banner" role="status">
      <AlertTriangle size={14} strokeWidth={2.2} />
      <span>Backend unreachable — showing the last data this browser cached. Changes will not save.</span>
      <button type="button" onClick={onRetry}>Retry</button>
    </div>
  );
}
