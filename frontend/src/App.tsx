import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import type {
  AccountCard, AccountDetail, BoardResponse, ColumnConfig, Filters, GroupBy,
  HealthBand, Metric, TaskBucket,
} from "./lib/types";
import { apiDelete, apiGet, apiPatch, apiPost, getSource, onSourceChange, qs } from "./lib/api";
import type { SourceState } from "./lib/api";
import { Board, BoardSkeleton } from "./components/Board";
import { DegradedBanner, MetricsStrip, QuickFilters, TopBar } from "./components/Shell";
import { Drawer } from "./components/Drawer";
import { NewTaskDialog } from "./components/NewTaskDialog";
import { CommandPalette, OverrideDialog } from "./components/Palette";
import { Settings } from "./components/Settings";

const GROUP_KEY = "signal-cs:group-by";

function readStored<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}

/** Active filter set lives in the URL so views are shareable. */
function filtersFromSearch(search: string): Filters {
  const params = new URLSearchParams(search);
  const raw = params.get("f");
  if (!raw) return {};
  try {
    return JSON.parse(raw) as Filters;
  } catch {
    return {};
  }
}

interface Toast { id: number; message: string; error?: boolean }

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();

  const [groupBy, setGroupBy] = useState<GroupBy>(() =>
    readStored(GROUP_KEY, "none", ["none", "priority", "mode", "client_type", "workstream"] as const)
  );
  const [collapsedLanes, setCollapsedLanes] = useState<Set<string>>(new Set());
  const [columnConfig, setColumnConfig] = useState<ColumnConfig[]>([]);
  const onSettings = location.pathname.replace(/\/+$/, "").endsWith("/settings");

  const loadColumns = useCallback(async () => {
    const d = await apiGet<{ columns: ColumnConfig[] }>("/columns");
    setColumnConfig(d.columns);
  }, []);

  /**
   * Keep a trailing slash on the mount path.
   *
   * React Router collapses `basename` + "/" to the bare `/p/{slug}`, and on
   * that URL a relative asset resolves one level up — /p/assets/... — which the
   * SPA fallback answers with 200 text/html, so the browser rejects the module
   * and the page comes back blank. nginx redirects the bare form, so a shared
   * link recovers either way; this keeps the URL in the address bar correct in
   * the first place, so the copied link never depends on that redirect.
   */
  useEffect(() => {
    const { pathname, search, hash } = window.location;
    if (/^\/p\/[^/]+$/.test(pathname)) {
      window.history.replaceState(null, "", `${pathname}/${search}${hash}`);
    }
  });

  const toggleLane = useCallback((key: string) => {
    setCollapsedLanes((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }, []);
  const [filters, setFiltersState] = useState<Filters>(() => filtersFromSearch(location.search));

  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [user, setUser] = useState<{ name: string; initials: string; avatar_color: string } | null>(null);
  const [activeMetric, setActiveMetric] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [fatal, setFatal] = useState<string | null>(null);
  const [source, setSource] = useState<SourceState>(getSource());
  const [toasts, setToasts] = useState<Toast[]>([]);

  const [openAccountId, setOpenAccountId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AccountDetail | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [newTaskFor, setNewTaskFor] = useState<string | null>(null);
  const [overrideFor, setOverrideFor] = useState<{ accountId: string; band: HealthBand | null } | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const searchRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLInputElement>(null);

  useEffect(() => onSourceChange(setSource), []);
  useEffect(() => { try { localStorage.setItem(GROUP_KEY, groupBy); } catch { /* private mode */ } }, [groupBy]);

  const setFilters = useCallback((next: Filters) => {
    setFiltersState(next);
    const params = new URLSearchParams(location.search);
    if (Object.keys(next).length) params.set("f", JSON.stringify(next));
    else params.delete("f");
    navigate({ search: params.toString() }, { replace: true });
  }, [navigate, location.search]);

  function toast(message: string, error = false) {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, error }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3200);
  }

  const filterParam = useMemo(
    () => (Object.keys(filters).length ? JSON.stringify(filters) : undefined),
    [filters]
  );

  const loadBoard = useCallback(async () => {
    const data = await apiGet<BoardResponse>(`/board${qs({ group_by: groupBy, filters: filterParam })}`);
    setBoard(data);
  }, [groupBy, filterParam]);

  const loadMetrics = useCallback(async () => {
    const data = await apiGet<{ metrics: Metric[] }>("/metrics");
    setMetrics(data.metrics);
  }, []);

  const refresh = useCallback(async () => {
    try {
      await Promise.all([loadBoard(), loadMetrics()]);
      setFatal(null);
    } catch (err) {
      setFatal(err instanceof Error ? err.message : "Could not reach the backend");
    }
  }, [loadBoard, loadMetrics]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [, , me] = await Promise.all([
          loadBoard(),
          loadMetrics(),
          apiGet<{ user: typeof user }>("/me"),
        ]);
        if (cancelled) return;
        await loadColumns();
        setUser(me.user);
        setFatal(null);
      } catch (err) {
        if (!cancelled) setFatal(err instanceof Error ? err.message : "Could not reach the backend");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [loadBoard, loadMetrics]);

  // --- drawer ---------------------------------------------------------------
  const loadDetail = useCallback(async (accountId: string) => {
    try {
      setDetail(await apiGet<AccountDetail>(`/accounts/${accountId}`));
    } catch {
      toast("Could not load that account", true);
    }
  }, []);

  useEffect(() => {
    if (!openAccountId) { setDetail(null); return; }
    loadDetail(openAccountId);
  }, [openAccountId, loadDetail]);

  const openAccount = useCallback((accountId: string) => setOpenAccountId(accountId), []);

  // --- writes ---------------------------------------------------------------
  async function patchAccount(accountId: string, patch: Record<string, unknown>) {
    try {
      await apiPatch(`/accounts/${accountId}`, patch);
      await Promise.all([loadBoard(), loadDetail(accountId), loadMetrics()]);
    } catch {
      toast("Could not save that change", true);
    }
  }

  async function handleDrop(cardId: string, columnKey: string) {
    if (!board) return;
    const snapshot = board;

    // Optimistic move. Dragging changes the column and nothing else — the
    // workstream is a separate axis, edited in the drawer only.
    setBoard({
      ...board,
      columns: board.columns.map((col) => {
        const without = col.cards.filter((c) => c.id !== cardId);
        if (col.id !== columnKey) return { ...col, cards: without, count: without.length };
        const moved = board.columns.flatMap((c) => c.cards).find((c) => c.id === cardId);
        if (!moved) return { ...col, cards: without, count: without.length };
        const next: AccountCard = { ...moved, column_id: columnKey };
        return { ...col, cards: [next, ...without], count: without.length + 1 };
      }),
    });

    try {
      // Column only. workstream is a different axis and never moves on drag.
      await apiPatch(`/accounts/${cardId}`, { column_id: columnKey });
      await refresh();
    } catch {
      setBoard(snapshot);
      toast("Could not save that move — put it back", true);
    }
  }

  async function logActivity(payload: { type: string; summary: string; create_task?: { title: string; due_date: string; bucket: TaskBucket } }) {
    if (!openAccountId) return;
    try {
      await apiPost(`/accounts/${openAccountId}/activities`, payload);
      toast(payload.create_task ? "Activity logged, next action created" : "Activity logged");
      await Promise.all([loadDetail(openAccountId), refresh()]);
    } catch {
      toast("Could not log that activity", true);
    }
  }

  async function toggleTask(taskId: string, done: boolean) {
    try {
      await apiPatch(`/tasks/${taskId}`, { status: done ? "done" : "open" });
      if (openAccountId) await loadDetail(openAccountId);
      await refresh();
    } catch {
      toast("Could not update that task", true);
    }
  }

  async function createTask(accountId: string, title: string, bucket: TaskBucket, due?: string) {
    try {
      await apiPost("/tasks", { account_id: accountId, title, bucket, due_date: due });
      toast("Task created");
      if (openAccountId) await loadDetail(openAccountId);
      await refresh();
    } catch {
      toast("Could not create that task", true);
    }
  }

  async function saveOverride(band: HealthBand, reason: string) {
    if (!overrideFor) return;
    try {
      await apiPost(`/accounts/${overrideFor.accountId}/health-override`, { band, reason });
      toast("Health override recorded");
      setOverrideFor(null);
      if (openAccountId) await loadDetail(openAccountId);
      await refresh();
    } catch {
      toast("Could not save the override", true);
    }
  }

  async function clearOverride() {
    if (!openAccountId) return;
    try {
      await apiDelete(`/accounts/${openAccountId}/health-override`);
      toast("Override cleared");
      await Promise.all([loadDetail(openAccountId), refresh()]);
    } catch {
      toast("Could not clear the override", true);
    }
  }



  // --- filters --------------------------------------------------------------
  function applyMetric(m: Metric) {
    if (activeMetric === m.key) { setActiveMetric(null); setFilters({}); return; }
    setActiveMetric(m.key);
    setFilters(m.filters);
  }


  // --- keyboard -------------------------------------------------------------
  const visibleCards = useMemo(() => (board ? board.columns.flatMap((c) => c.cards) : []), [board]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName) || target.isContentEditable;

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen(true);
        return;
      }
      if (typing) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      switch (e.key) {
        case "/":
          e.preventDefault();
          setPaletteOpen(true);
          break;
        case "g":
          setGroupBy((g) =>
            g === "none" ? "workstream" : g === "workstream" ? "mode" : g === "mode" ? "priority" : "none"
          );
          break;
        case "c": {
          const accountId = openAccountId ?? visibleCards[0]?.account_id;
          if (accountId) setNewTaskFor(accountId);
          break;
        }
        case "n":
          if (openAccountId) composerRef.current?.focus();
          break;
        case "Escape":
          if (paletteOpen) setPaletteOpen(false);
          else if (openAccountId) setOpenAccountId(null);
          break;
        case "j":
        case "k": {
          if (!visibleCards.length) break;
          const idx = visibleCards.findIndex((c) => c.id === selectedId);
          const next = e.key === "j"
            ? Math.min(idx + 1, visibleCards.length - 1)
            : Math.max(idx - 1, 0);
          const card = visibleCards[idx === -1 ? 0 : next];
          setSelectedId(card.id);
          document.querySelector<HTMLElement>(`[data-card-id="${card.id}"]`)?.scrollIntoView({ block: "nearest" });
          break;
        }
        case "Enter": {
          const card = visibleCards.find((c) => c.id === selectedId);
          if (card) setOpenAccountId(card.account_id);
          break;
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visibleCards, selectedId, openAccountId, paletteOpen]);

  // --- render ---------------------------------------------------------------
  const degraded = source === "local";

  return (
    <>
      <TopBar
        user={user}
        source={source}
        groupBy={groupBy}
        filters={filters}
        searchRef={searchRef}
        onGroupBy={setGroupBy}
        onFilters={(f) => { setActiveMetric(null); setFilters(f); }}
        onOpenPalette={() => { setPaletteOpen(true); searchRef.current?.blur(); }}
        onNewTask={() => setNewTaskFor(openAccountId ?? visibleCards[0]?.account_id ?? null)}
      />

      {degraded && <DegradedBanner onRetry={() => refresh()} />}

      {onSettings ? (
        <Settings
          onChanged={() => {
            loadColumns();
            refresh();
          }}
        />
      ) : (
        <>
      <MetricsStrip metrics={metrics} activeKey={activeMetric} onApply={applyMetric} />

      <QuickFilters
        filters={filters}
        onFilters={(f) => { setActiveMetric(null); setFilters(f); }}
      />

      {loading && !board && <BoardSkeleton />}

      {!loading && fatal && !board && (
        <div className="board-wrap">
          <div className="empty-state">
            <h2>The board could not load</h2>
            <p>{fatal}. Nothing was cached in this browser yet, so there is nothing to fall back to.</p>
            <button type="button" className="btn" onClick={() => refresh()}>Try again</button>
          </div>
        </div>
      )}

      {board && board.total_cards === 0 && (
        <div className="board-wrap">
          <div className="empty-state">
            <h2>Nothing matches these filters</h2>
            <p>Clear a filter chip or pick a different saved view to bring the book back.</p>
            <button type="button" className="btn" onClick={() => { setFilters({}); setActiveMetric(null); }}>
              Clear filters
            </button>
          </div>
        </div>
      )}

      {board && board.total_cards > 0 && (
        <Board
          board={board}
          groupBy={groupBy}
          selectedId={selectedId}
          collapsedLanes={collapsedLanes}
          onToggleLane={toggleLane}
          onOpen={openAccount}
          onMove={handleDrop}
        />
      )}
        </>
      )}

      {detail && openAccountId && (
        <Drawer
          detail={detail}
          columns={columnConfig}
          onClose={() => setOpenAccountId(null)}
          onPatch={(patch) => patchAccount(openAccountId, patch)}
          onLogActivity={logActivity}
          onToggleTask={(task) => toggleTask(task.id, task.status !== "done")}
          onOverride={(band, reason) => saveOverride(band as HealthBand, reason)}
          onClearOverride={clearOverride}
        />
      )}

      {overrideFor && detail && (
        <OverrideDialog
          accountName={detail.account.name}
          score={detail.health.score}
          computedBand={detail.health.computed_band_label}
          current={overrideFor.band ?? detail.health.override?.band ?? null}
          currentReason={detail.health.override?.reason ?? null}
          onSubmit={saveOverride}
          onClose={() => setOverrideFor(null)}
        />
      )}

      {newTaskFor && (
        <NewTaskDialog
          accountName={
            visibleCards.find((c) => c.account_id === newTaskFor)?.kind === "account"
              ? (visibleCards.find((c) => c.account_id === newTaskFor) as { name: string }).name
              : detail?.account.name ?? "account"
          }
          onSubmit={(title, bucket, due) => { createTask(newTaskFor, title, bucket, due); setNewTaskFor(null); }}
          onClose={() => setNewTaskFor(null)}
        />
      )}

      {paletteOpen && (
        <CommandPalette
            onClose={() => setPaletteOpen(false)}
          onOpenAccount={openAccount}
              onNewTask={() => setNewTaskFor(openAccountId ?? visibleCards[0]?.account_id ?? null)}
          onLogActivity={() => composerRef.current?.focus()}
        />
      )}

      <div className="toasts">
        {toasts.map((t) => (
          <div key={t.id} className={`toast${t.error ? " error" : ""}`} role="status">{t.message}</div>
        ))}
      </div>
    </>
  );
}
