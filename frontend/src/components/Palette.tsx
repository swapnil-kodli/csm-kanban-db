import { useEffect, useMemo, useRef, useState } from "react";
import type { HealthBand } from "../lib/types";
import { apiGet } from "../lib/api";

interface SearchResults {
  /** Companies and deals are separate groups on purpose: searching "Prestige"
   *  should offer both the client and its engagements, because which one you
   *  want depends on what you are about to do. */
  companies: { id: string; key: string; name: string; city: string | null; deal_count: number }[];
  deals: { id: string; key: string; name: string; company_name: string; mode_label: string;
           workstream_label: string; outcome: string; health_score: number }[];
  contacts: { id: string; name: string; role: string; company_id: string; company_name: string }[];
  tasks: { id: string; title: string; type_label: string; deal_id: string; deal_name: string }[];
}

interface Command {
  id: string;
  group: string;
  title: string;
  sub?: string;
  run: () => void;
}

interface Props {
  onClose: () => void;
  onOpenDeal: (dealId: string) => void;
  onOpenCompany: (companyId: string) => void;
  onNewTask: () => void;
}

export function CommandPalette({ onClose, onOpenDeal, onOpenCompany, onNewTask }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  useEffect(() => {
    const q = query.trim();
    if (!q) { setResults(null); return; }
    let cancelled = false;
    const handle = setTimeout(() => {
      apiGet<SearchResults>(`/search?q=${encodeURIComponent(q)}`)
        .then((r) => { if (!cancelled) setResults(r); })
        .catch(() => { if (!cancelled) setResults(null); });
    }, 120);
    return () => { cancelled = true; clearTimeout(handle); };
  }, [query]);

  const commands = useMemo<Command[]>(() => {
    const q = query.trim().toLowerCase();
    const out: Command[] = [];

    results?.companies.forEach((c) =>
      out.push({
        id: `co-${c.id}`,
        group: "Clients",
        title: c.name,
        sub: `${c.key}${c.city ? ` · ${c.city}` : ""} · ${c.deal_count} active ${
          c.deal_count === 1 ? "deal" : "deals"
        }`,
        run: () => { onOpenCompany(c.id); onClose(); },
      })
    );
    results?.deals.forEach((d) =>
      out.push({
        id: `dl-${d.id}`,
        group: "Deals",
        title: d.name,
        sub: `${d.key} · ${d.company_name} · ${d.mode_label} · ${d.workstream_label}${
          d.outcome === "active" ? ` · ${d.health_score}` : ` · ${d.outcome}`
        }`,
        run: () => { onOpenDeal(d.id); onClose(); },
      })
    );
    results?.contacts.forEach((c) =>
      out.push({
        id: `ct-${c.id}`,
        group: "Contacts",
        title: c.name,
        sub: `${c.role} · ${c.company_name}`,
        // Contacts belong to the company, so a contact hit opens the client,
        // not one of its deals — which deal a person relates to is exactly what
        // the company view is there to show.
        run: () => { onOpenCompany(c.company_id); onClose(); },
      })
    );
    results?.tasks.forEach((t) =>
      out.push({
        id: `tk-${t.id}`,
        group: "Tasks",
        title: t.title,
        sub: `${t.deal_name} · ${t.type_label}`,
        run: () => { onOpenDeal(t.deal_id); onClose(); },
      })
    );

    const actions: Command[] = [
      { id: "cmd-task", group: "Commands", title: "New task", run: () => { onNewTask(); onClose(); } },
    ];

    out.push(...actions.filter((a) => !q || a.title.toLowerCase().includes(q)));
    return out;
  }, [results, query, onOpenDeal, onOpenCompany, onClose, onNewTask]);

  useEffect(() => { setActive(0); }, [query, results]);

  useEffect(() => {
    listRef.current?.querySelector(".palette-row.active")?.scrollIntoView({ block: "nearest" });
  }, [active]);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(i + 1, commands.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); commands[active]?.run(); }
    else if (e.key === "Escape") { e.preventDefault(); onClose(); }
  }

  let lastGroup = "";

  return (
    <div className="palette-scrim" onClick={onClose}>
      <div className="palette" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Command palette">
        <input
          ref={inputRef}
          className="palette-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Search clients, deals, contacts, tasks — or type a command…"
          aria-label="Command palette input"
        />
        <div className="palette-list" ref={listRef}>
          {commands.length === 0 && <div className="palette-empty">No matches.</div>}
          {commands.map((c, i) => {
            const header = c.group !== lastGroup ? c.group : null;
            lastGroup = c.group;
            return (
              <div key={c.id}>
                {header && <div className="palette-group">{header}</div>}
                <button
                  type="button"
                  className={`palette-row${i === active ? " active" : ""}`}
                  onMouseEnter={() => setActive(i)}
                  onClick={c.run}
                >
                  <span className="palette-row-title">{c.title}</span>
                  {c.sub && <span className="palette-row-sub">{c.sub}</span>}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export function OverrideDialog({
  dealName, score, computedBand, current, currentReason, onSubmit, onClose,
}: {
  dealName: string;
  score: number;
  computedBand: string;
  current: HealthBand | null;
  currentReason: string | null;
  onSubmit: (band: HealthBand, reason: string) => void;
  onClose: () => void;
}) {
  const [band, setBand] = useState<HealthBand>(current ?? "at_risk");
  const [reason, setReason] = useState(currentReason ?? "");

  return (
    <div className="dialog-scrim" onClick={onClose}>
      <form
        className="dialog"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => { e.preventDefault(); if (reason.trim().length >= 3) onSubmit(band, reason.trim()); }}
      >
        <h3>Set manual health override</h3>
        <p>
          {dealName} scores <b>{score}</b> ({computedBand}). Your judgement beats the score — but the
          reason is recorded, and the score stays visible underneath.
        </p>
        <div>
          <label htmlFor="ov-band">Band</label>
          <select id="ov-band" value={band} onChange={(e) => setBand(e.target.value as HealthBand)}>
            <option value="healthy">Healthy</option>
            <option value="watch">Watch</option>
            <option value="at_risk">At Risk</option>
            <option value="critical">Critical</option>
          </select>
        </div>
        <div>
          <label htmlFor="ov-reason">Reason (required)</label>
          <textarea
            id="ov-reason"
            autoFocus
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. champion left, budget frozen"
          />
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn subtle" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={reason.trim().length < 3}>Save override</button>
        </div>
      </form>
    </div>
  );
}
