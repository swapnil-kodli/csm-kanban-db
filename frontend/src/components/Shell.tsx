import { useEffect, useRef, useState } from "react";
import { Search, SlidersHorizontal, Plus, AlertTriangle, X, Settings as Gear, Trash2, Building2, Briefcase } from "lucide-react";
import { Link } from "react-router-dom";
import type { Filters, GroupBy, Metric } from "../lib/types";
import { formatINR } from "../lib/format";

// One board now. The v1 three-view toggle is gone: health became a card
// indicator and a filter, and tasks moved into the drawer rather than driving
// columns of their own.
const GROUP_OPTIONS: { key: GroupBy; label: string }[] = [
  { key: "none", label: "No swimlanes" },
  { key: "workstream", label: "Workstream" },
  { key: "mode", label: "Pilot / Customer" },
  { key: "client_type", label: "Client type" },
  { key: "priority", label: "Priority" },
];

interface TopBarProps {
  user: { name: string; initials: string; avatar_color: string } | null;
  source: "live" | "local";
  groupBy: GroupBy;
  filters: Filters;
  searchRef: React.RefObject<HTMLInputElement>;
  onGroupBy: (g: GroupBy) => void;
  onFilters: (f: Filters) => void;
  onOpenPalette: () => void;
  onNewTask: () => void;
  onNewClient: () => void;
  onNewDeal: () => void;
  trashCount: number;
}

export function TopBar({
  user, source, groupBy, filters, searchRef, onGroupBy, onFilters, onOpenPalette, onNewTask,
  onNewClient, onNewDeal, trashCount,
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
          placeholder="Search clients, deals, contacts, tasks…"
          aria-label="Search"
          onFocus={onOpenPalette}
          readOnly
        />
        <kbd>⌘K</kbd>
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

        {/* Trash is only offered once something is in it: an always-visible
            empty bin is a permanent reminder of nothing. */}
        {trashCount > 0 && (
          <Link
            className="btn btn-icon"
            to="trash"
            title={`Trash · ${trashCount} deleted`}
            aria-label={`Trash, ${trashCount} deleted clients`}
          >
            <Trash2 size={14} strokeWidth={2.2} />
            <span className="btn-count">{trashCount}</span>
          </Link>
        )}

        <Link className="btn btn-icon" to="settings" title="Settings" aria-label="Settings">
          <Gear size={14} strokeWidth={2.2} />
        </Link>

        <div style={{ position: "relative" }}>
          <button type="button" className="btn" aria-pressed={panelOpen} onClick={() => setPanelOpen((v) => !v)}>
            <SlidersHorizontal size={14} strokeWidth={2.2} />
            Filters{activeCount ? ` · ${activeCount}` : ""}
          </button>
          {panelOpen && (
            <FilterPanel filters={filters} onFilters={onFilters} onClose={() => setPanelOpen(false)} />
          )}
        </div>

        <button type="button" className="btn" onClick={onNewTask} title="New task (c)">
          <Plus size={14} strokeWidth={2.4} />
          Task
        </button>

        <button type="button" className="btn" onClick={onNewClient} title="New client">
          <Building2 size={14} strokeWidth={2.4} />
          Client
        </button>

        {/* The primary action is a DEAL, not a client. A client with no deal
            shows nothing anywhere, so opening work is the common case and
            adding an organisation is the occasional prerequisite. */}
        <button type="button" className="btn primary" onClick={onNewDeal} title="New deal">
          <Briefcase size={14} strokeWidth={2.4} />
          Deal
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

      <Group label="2 · Mode">
        <div className="popover-chips">
          {(["pilot", "customer"] as const).map((m) => (
            <button key={m} type="button" className="chip" aria-pressed={filters.modes?.includes(m) ?? false} onClick={() => toggleIn("modes", m)}>
              {m}
            </button>
          ))}
        </div>
      </Group>

      <Group label="3 · Client type">
        <div className="popover-chips">
          {(["voice_ai_only", "data_plus_voice_ai"] as const).map((c) => (
            <button key={c} type="button" className="chip" aria-pressed={filters.client_types?.includes(c) ?? false} onClick={() => toggleIn("client_types", c)}>
              {c.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      </Group>

      <Group label="4 · Workstream">
        <div className="popover-chips">
          {(["bot_making", "data_procurement", "voice_ai_calling"] as const).map((w) => (
            <button key={w} type="button" className="chip" aria-pressed={filters.workstreams?.includes(w) ?? false} onClick={() => toggleIn("workstreams", w)}>
              {w.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      </Group>

      <Group label="5 · Column">
        <div className="popover-chips">
          {["ready_for_onboarding", "onboarding", "working", "approval", "launch"].map((c) => (
            <button key={c} type="button" className="chip" aria-pressed={filters.columns?.includes(c) ?? false} onClick={() => toggleIn("columns", c)}>
              {c.replace(/_/g, " ")}
            </button>
          ))}
        </div>
      </Group>

      <Group label="6 · Quoted value">
        <div className="popover-chips">
          {[{ l: "≥ ₹10 L", v: 1000000 }, { l: "≥ ₹5 L", v: 500000 }].map((o) => (
            <button key={o.v} type="button" className="chip" aria-pressed={filters.quoted_min === o.v}
              onClick={() => onFilters({ ...filters, quoted_min: filters.quoted_min === o.v ? undefined : o.v })}>
              {o.l}
            </button>
          ))}
        </div>
      </Group>

      <Group label="7 · Margin">
        <div className="popover-chips">
          <button type="button" className="chip" aria-pressed={filters.negative_margin ?? false}
            onClick={() => onFilters({ ...filters, negative_margin: filters.negative_margin ? undefined : true })}>
            negative
          </button>
          <button type="button" className="chip" aria-pressed={filters.thin_margin ?? false}
            onClick={() => onFilters({ ...filters, thin_margin: filters.thin_margin ? undefined : true })}>
            under 20%
          </button>
        </div>
      </Group>

      <Group label="8 · Last contact">
        <div className="popover-chips">
          <button type="button" className="chip" aria-pressed={filters.no_contact ?? false}
            onClick={() => onFilters({ ...filters, no_contact: filters.no_contact ? undefined : true })}>
            past threshold
          </button>
        </div>
      </Group>

      <Group label="9 · Stalled">
        <div className="popover-chips">
          <button type="button" className="chip" aria-pressed={filters.stalled_handoff ?? false}
            onClick={() => onFilters({ ...filters, stalled_handoff: filters.stalled_handoff ? undefined : true })}>
            handoff
          </button>
          <button type="button" className="chip" aria-pressed={filters.column_stalled ?? false}
            onClick={() => onFilters({ ...filters, column_stalled: filters.column_stalled ? undefined : true })}>
            in column
          </button>
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
          <div className={`metric-value ${m.margin_band ? `text-${m.margin_band}` : ""}`}>
            {m.format === "inr" ? formatINR(m.value) : m.value}
          </div>
          <div className="metric-label">{m.label}</div>
          <div className="metric-sub">{m.sub}</div>
        </button>
      ))}
    </div>
  );
}

const QUICK_FILTERS: { key: string; label: string; patch: Filters }[] = [
  { key: "pilot", label: "Pilot", patch: { modes: ["pilot"] } },
  { key: "customer", label: "Customer", patch: { modes: ["customer"] } },
  { key: "voice_only", label: "Voice AI only", patch: { client_types: ["voice_ai_only"] } },
  { key: "data_voice", label: "Data + Voice AI", patch: { client_types: ["data_plus_voice_ai"] } },
  { key: "bot", label: "Bot-Making", patch: { workstreams: ["bot_making"] } },
  { key: "data_proc", label: "Data Procurement", patch: { workstreams: ["data_procurement"] } },
  { key: "voice_calling", label: "Voice AI Calling", patch: { workstreams: ["voice_ai_calling"] } },
  { key: "at_risk", label: "At risk", patch: { bands: ["at_risk", "critical"] } },
  { key: "negative_margin", label: "Negative margin", patch: { negative_margin: true } },
];

interface QuickFiltersProps {
  filters: Filters;
  onFilters: (f: Filters) => void;
}

export function QuickFilters({ filters, onFilters }: QuickFiltersProps) {

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

  return (
    <div className="qfilters">
      {QUICK_FILTERS.map((qf) => (
        <button
          key={qf.key}
          type="button"
          className="chip"
          aria-pressed={qf.key === "mine" ? true : isActive(qf.patch)}
          disabled={qf.key === "mine"}
          title={qf.key === "mine" ? "Single-CSM MVP — every client is yours" : undefined}
          onClick={() => qf.key !== "mine" && toggle(qf.patch)}
        >
          {qf.label}
        </button>
      ))}

      {countFilters(filters) > 0 && (
        <>
          <button type="button" className="chip" onClick={() => onFilters({})}>
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
