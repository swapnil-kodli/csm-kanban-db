import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import type {
  BoardResponse, CompanyContact, CompanyDetail, CompanySummary, CompanyTrashRow,
  DealCard, DealDetail, DealTrashRow, Filters, GroupBy, HealthBand, Metric,
  NewCompanyInput, NewDealInput, Outcome, TaskBucket, TaskPriority, TaskType,
} from "./lib/types";
import { apiDelete, apiGet, apiPatch, apiPost, getSource, onSourceChange, qs } from "./lib/api";
import type { SourceState } from "./lib/api";
import { Board, BoardSkeleton } from "./components/Board";
import { DegradedBanner, MetricsStrip, QuickFilters, TopBar } from "./components/Shell";
import { Drawer } from "./components/Drawer";
import { NewTaskDialog } from "./components/NewTaskDialog";
import { CommandPalette, OverrideDialog } from "./components/Palette";
import { Settings } from "./components/Settings";
import { NewCompanyDialog } from "./components/NewCompanyDialog";
import { NewDealDialog } from "./components/NewDealDialog";
import { CompanyView } from "./components/CompanyView";
import { Trash } from "./components/Trash";

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

/** Where a new client lands, named rather than assumed — columns are configurable. */
function entryColumnLabel(board: BoardResponse): string {
  return board.columns.find((c) => c.is_default_entry)?.title
    ?? board.columns[0]?.title
    ?? "the first column";
}

interface Toast { id: number; message: string; error?: boolean }

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();

  const [groupBy, setGroupBy] = useState<GroupBy>(() =>
    readStored(GROUP_KEY, "none", ["none", "priority", "mode", "client_type", "workstream"] as const)
  );
  const [collapsedLanes, setCollapsedLanes] = useState<Set<string>>(new Set());
  const path = location.pathname.replace(/\/+$/, "");
  const onSettings = path.endsWith("/settings");
  const onTrash = path.endsWith("/trash");
  // /c/{id} — the company detail view. Matched off the path rather than with
  // <Routes> to stay consistent with how settings and trash already work here.
  const companyRoute = path.match(/\/c\/([^/]+)$/);
  const openCompanyId = companyRoute ? companyRoute[1] : null;


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

  const [openDealId, setOpenDealId] = useState<string | null>(null);
  const [detail, setDetail] = useState<DealDetail | null>(null);
  const [companyDetail, setCompanyDetail] = useState<CompanyDetail | null>(null);
  const [companies, setCompanies] = useState<CompanySummary[]>([]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [newTaskFor, setNewTaskFor] = useState<string | null>(null);
  const [overrideFor, setOverrideFor] = useState<{ dealId: string; band: HealthBand | null } | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [newCompanyOpen, setNewCompanyOpen] = useState(false);
  const [newDealFor, setNewDealFor] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [trashDeals, setTrashDeals] = useState<DealTrashRow[]>([]);
  const [trashCompanies, setTrashCompanies] = useState<CompanyTrashRow[]>([]);

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

  /** Trash is loaded alongside the board so the topbar count is never stale. */
  const loadTrash = useCallback(async () => {
    const [d, c] = await Promise.all([
      apiGet<{ deals: DealTrashRow[] }>("/deals/trash/list"),
      apiGet<{ companies: CompanyTrashRow[] }>("/companies/trash/list"),
    ]);
    setTrashDeals(d.deals);
    setTrashCompanies(c.companies);
  }, []);

  /** The client list, for the New Deal picker and the clients view. */
  const loadCompanies = useCallback(async () => {
    const data = await apiGet<{ companies: CompanySummary[] }>("/companies");
    setCompanies(data.companies);
  }, []);

  const refresh = useCallback(async () => {
    try {
      await Promise.all([loadBoard(), loadMetrics(), loadTrash(), loadCompanies()]);
      setFatal(null);
    } catch (err) {
      setFatal(err instanceof Error ? err.message : "Could not reach the backend");
    }
  }, [loadBoard, loadMetrics, loadTrash, loadCompanies]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [, , , , me] = await Promise.all([
          loadBoard(),
          loadMetrics(),
          loadTrash(),
          loadCompanies(),
          apiGet<{ user: typeof user }>("/me"),
        ]);
        if (cancelled) return;
        setUser(me.user);
        setFatal(null);
      } catch (err) {
        if (!cancelled) setFatal(err instanceof Error ? err.message : "Could not reach the backend");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [loadBoard, loadMetrics, loadTrash, loadCompanies]);

  // --- drawer ---------------------------------------------------------------
  const loadDetail = useCallback(async (dealId: string) => {
    try {
      setDetail(await apiGet<DealDetail>(`/deals/${dealId}`));
    } catch {
      toast("Could not load that deal", true);
    }
  }, []);

  useEffect(() => {
    if (!openDealId) { setDetail(null); return; }
    loadDetail(openDealId);
  }, [openDealId, loadDetail]);

  const loadCompanyDetail = useCallback(async (companyId: string) => {
    try {
      setCompanyDetail(await apiGet<CompanyDetail>(`/companies/${companyId}`));
    } catch {
      toast("Could not load that client", true);
    }
  }, []);

  useEffect(() => {
    if (!openCompanyId) { setCompanyDetail(null); return; }
    loadCompanyDetail(openCompanyId);
  }, [openCompanyId, loadCompanyDetail]);

  const openDeal = useCallback((dealId: string) => setOpenDealId(dealId), []);
  const openCompany = useCallback((companyId: string) => {
    // Closing the drawer first: the company view is a page, and leaving a
    // drawer floating over it would leave two things claiming to be in focus.
    setOpenDealId(null);
    navigate(`c/${companyId}`);
  }, [navigate]);

  /** The New Deal picker asks for a company's contacts only once one is chosen. */
  const contactsFor = useCallback(async (companyId: string) => {
    const data = await apiGet<CompanyDetail>(`/companies/${companyId}`);
    return data.contacts as CompanyContact[];
  }, []);

  // --- writes ---------------------------------------------------------------
  async function addContact(companyId: string) {
    try {
      await apiPost("/contacts", { company_id: companyId, name: "New contact", role: "" });
      await refreshOpen(companyId);
    } catch {
      toast("Could not add that contact", true);
    }
  }

  /** Contacts belong to a company but are edited from both views, so both are
   *  refreshed rather than guessing which one the user is looking at. */
  async function refreshOpen(companyId?: string) {
    await Promise.all([
      openDealId ? loadDetail(openDealId) : Promise.resolve(),
      companyId ?? openCompanyId
        ? loadCompanyDetail((companyId ?? openCompanyId) as string)
        : Promise.resolve(),
    ]);
  }

  async function patchContact(id: string, patch: Record<string, unknown>) {
    try {
      await apiPatch(`/contacts/${id}`, patch);
      await Promise.all([refreshOpen(), refresh()]);
    } catch (e) {
      // A 409 here is the primary-contact guard; show what it said.
      toast(e instanceof Error ? e.message : "Could not save that contact", true);
    }
  }

  async function deleteContact(id: string) {
    try {
      await apiDelete(`/contacts/${id}`);
      await refreshOpen();
    } catch (e) {
      // A 409 here is the POC guard, and it names the deals — show it verbatim
      // rather than replacing it with something vaguer.
      toast(e instanceof Error ? e.message : "Could not delete that contact", true);
    }
  }

  async function patchDeal(dealId: string, patch: Record<string, unknown>) {
    try {
      await apiPatch(`/deals/${dealId}`, patch);
      await Promise.all([loadBoard(), loadDetail(dealId), loadMetrics()]);
    } catch (e) {
      // A 422 here is the POC invariant. It explains itself; do not swallow it.
      toast(e instanceof Error ? e.message : "Could not save that change", true);
    }
  }

  async function setOutcome(dealId: string, outcome: Outcome, reason: string) {
    try {
      await apiPost(`/deals/${dealId}/outcome`, { outcome, reason: reason || undefined });
      toast(
        outcome === "active"
          ? "Deal reopened"
          : `Deal marked ${outcome} — it is off the board and in the client's history`
      );
      if (outcome !== "active") setOpenDealId(null);
      else await loadDetail(dealId);
      await refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not update that deal", true);
    }
  }

  async function createCompany(input: NewCompanyInput) {
    setCreating(true);
    try {
      const res = await apiPost<{ company: CompanySummary }>("/companies", input);
      setNewCompanyOpen(false);
      toast(`${res.company.name} added as ${res.company.key}`);
      await refresh();
      // Straight to the client's own view: a company with no deals shows nothing
      // on the board, so landing back there would look like nothing happened.
      openCompany(res.company.id);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not create that client", true);
    } finally {
      setCreating(false);
    }
  }

  async function createDeal(input: NewDealInput) {
    setCreating(true);
    try {
      const res = await apiPost<{ deal: DealCard }>("/deals", input);
      setNewDealFor(null);
      toast(`${res.deal.name} added as ${res.deal.key}`);
      await refresh();
      // Open it: the four card fields are the minimum, and the drawer is where
      // the rest of the engagement actually gets filled in.
      setOpenDealId(res.deal.deal_id);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not create that deal", true);
    } finally {
      setCreating(false);
    }
  }

  /** Soft delete. Nothing is destroyed; the deal moves to Trash. */
  async function archiveDeal(dealId: string, name: string) {
    try {
      await apiDelete(`/deals/${dealId}`);
      setOpenDealId(null);
      toast(`${name} moved to Trash`);
      await refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not delete that deal", true);
    }
  }

  /** Soft delete, taking the client's deals with it. */
  async function archiveCompany(companyId: string, name: string) {
    try {
      const res = await apiDelete<{ deals_archived: number }>(`/companies/${companyId}`);
      navigate("..");
      const n = res.deals_archived;
      toast(`${name} moved to Trash${n ? ` with ${n} ${n === 1 ? "deal" : "deals"}` : ""}`);
      await refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not delete that client", true);
    }
  }

  type AnyTrashRow =
    | ({ kind: "deal" } & DealTrashRow)
    | ({ kind: "company" } & CompanyTrashRow);

  async function restoreTrashed(row: AnyTrashRow) {
    const base = row.kind === "company" ? "companies" : "deals";
    try {
      const res = await apiPost<{ deals_restored?: number }>(`/${base}/${row.id}/restore`);
      const n = res.deals_restored;
      toast(`${row.name} restored${n ? ` with ${n} ${n === 1 ? "deal" : "deals"}` : ""}`);
      await refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not restore that", true);
    }
  }

  async function hardDeleteTrashed(row: AnyTrashRow, confirmKey: string) {
    const base = row.kind === "company" ? "companies" : "deals";
    try {
      await apiPost(`/${base}/${row.id}/hard-delete`, { confirm_key: confirmKey });
      toast(`${row.name} deleted permanently`);
      await refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not delete that", true);
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
        const next: DealCard = { ...moved, column_id: columnKey };
        return { ...col, cards: [next, ...without], count: without.length + 1 };
      }),
    });

    try {
      // Column only. workstream is a different axis and never moves on drag.
      await apiPatch(`/deals/${cardId}`, { column_id: columnKey });
      await refresh();
    } catch {
      setBoard(snapshot);
      toast("Could not save that move — put it back", true);
    }
  }


  async function toggleTask(taskId: string, done: boolean) {
    try {
      await apiPatch(`/tasks/${taskId}`, { status: done ? "done" : "open" });
      if (openDealId) await loadDetail(openDealId);
      await refresh();
    } catch {
      toast("Could not update that task", true);
    }
  }

  async function createTask(
    dealId: string,
    title: string,
    bucket: TaskBucket,
    due?: string,
    type: TaskType = "checkin",
    priority: TaskPriority = "normal"
  ) {
    try {
      // No provenance: that string means "an alert raised this", and a manual
      // task must not claim it.
      await apiPost("/tasks", {
        deal_id: dealId, title, bucket, due_date: due, type, priority,
      });
      toast("Task created");
      if (openDealId) await loadDetail(openDealId);
      await refresh();
    } catch {
      toast("Could not create that task", true);
    }
  }

  async function saveOverride(band: HealthBand, reason: string) {
    if (!overrideFor) return;
    try {
      await apiPost(`/deals/${overrideFor.dealId}/health-override`, { band, reason });
      toast("Health override recorded");
      setOverrideFor(null);
      if (openDealId) await loadDetail(openDealId);
      await refresh();
    } catch {
      toast("Could not save the override", true);
    }
  }

  async function clearOverride() {
    if (!openDealId) return;
    try {
      await apiDelete(`/deals/${openDealId}/health-override`);
      toast("Override cleared");
      await Promise.all([loadDetail(openDealId), refresh()]);
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
        case "c":
          // Open the picker with no deal preselected when none is open.
          // Silently attaching a task to whatever sorted first is how a board
          // stops being trustworthy.
          setNewTaskFor(openDealId ?? "");
          break;
        case "n":
          if (openDealId) composerRef.current?.focus();
          break;
        case "Escape":
          if (paletteOpen) setPaletteOpen(false);
          else if (openDealId) setOpenDealId(null);
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
          if (card) setOpenDealId(card.deal_id);
          break;
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visibleCards, selectedId, openDealId, paletteOpen]);

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
        onNewTask={() => setNewTaskFor(openDealId ?? "")}
        onNewClient={() => setNewCompanyOpen(true)}
        onNewDeal={() => setNewDealFor("")}
        trashCount={trashDeals.length + trashCompanies.length}
      />

      {degraded && <DegradedBanner onRetry={() => refresh()} />}

      {onSettings ? (
        <Settings
          onChanged={refresh}
        />
      ) : onTrash ? (
        <Trash
          deals={trashDeals}
          companies={trashCompanies}
          onRestore={restoreTrashed}
          onHardDelete={hardDeleteTrashed}
          onBack={() => navigate("..")}
        />
      ) : openCompanyId ? (
        companyDetail ? (
          <CompanyView
            detail={companyDetail}
            onBack={() => navigate("..")}
            onOpenDeal={(id) => { navigate(".."); setOpenDealId(id); }}
            onNewDeal={(id) => setNewDealFor(id)}
            onAddContact={addContact}
            onDeleteContact={deleteContact}
            onArchive={() =>
              archiveCompany(companyDetail.company.id, companyDetail.company.name)
            }
          />
        ) : (
          <BoardSkeleton />
        )
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

      {/* Two different zeroes, two different calls to action. `total_cards` is
          post-filter, so it cannot tell these apart on its own — `book_size` is
          the unfiltered live book. */}
      {board && board.total_cards === 0 && board.book_size === 0 && (
        <div className="board-wrap">
          <div className="empty-state">
            <h2>{companies.length ? "No active deals" : "No clients yet"}</h2>
            <p>
              {companies.length
                ? `${companies.length} ${companies.length === 1 ? "client is" : "clients are"} on file, but nothing is being delivered for them. Open a deal and it lands in ${entryColumnLabel(board)}.`
                : `The board is ready — five columns, health scoring and the attention queue all work as soon as there is something to track. Add a client, then open a deal against them, and it lands in ${entryColumnLabel(board)}.`}
            </p>
            <button
              type="button"
              className="btn primary"
              onClick={() => (companies.length ? setNewDealFor("") : setNewCompanyOpen(true))}
            >
              {companies.length ? "Open the first deal" : "Add the first client"}
            </button>
            {board.archived_count > 0 && (
              <p className="empty-aside">
                <Link to="trash">
                  {board.archived_count} deleted{" "}
                  {board.archived_count === 1 ? "deal is" : "deals are"} in Trash
                </Link>
                {" "}and can be restored.
              </p>
            )}
          </div>
        </div>
      )}

      {board && board.total_cards === 0 && board.book_size > 0 && (
        <div className="board-wrap">
          <div className="empty-state">
            <h2>Nothing matches these filters</h2>
            <p>
              {board.book_size} {board.book_size === 1 ? "deal is" : "deals are"} on the
              board across {board.company_count}{" "}
              {board.company_count === 1 ? "client" : "clients"} — none of them
              match what is selected right now.
            </p>
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
          onOpen={openDeal}
          onMove={handleDrop}
        />
      )}
        </>
      )}

      {detail && openDealId && (
        <Drawer
          detail={detail}
          onClose={() => setOpenDealId(null)}
          onPatch={(patch) => patchDeal(openDealId, patch)}
          onToggleTask={(task) => toggleTask(task.id, task.status !== "done")}
          onOverride={(band, reason) => saveOverride(band as HealthBand, reason)}
          onClearOverride={clearOverride}
          onAddTask={() => setNewTaskFor(openDealId)}
          onAddContact={() => detail.company && addContact(detail.company.id)}
          onPatchContact={(id, patch) => patchContact(id, patch)}
          onDeleteContact={(id) => deleteContact(id)}
          onDeleteDeal={() => archiveDeal(openDealId, detail.deal.name)}
          onOpenCompany={() => detail.company && openCompany(detail.company.id)}
          onSetOutcome={(outcome, reason) => setOutcome(openDealId, outcome, reason)}
        />
      )}

      {overrideFor && detail && (
        <OverrideDialog
          dealName={detail.deal.name}
          score={detail.health.score}
          computedBand={detail.health.computed_band_label}
          current={overrideFor.band ?? detail.health.override?.band ?? null}
          currentReason={detail.health.override?.reason ?? null}
          onSubmit={saveOverride}
          onClose={() => setOverrideFor(null)}
        />
      )}

      {newTaskFor !== null && (
        <NewTaskDialog
          deals={visibleCards.map((c) => ({ id: c.deal_id, name: c.name, key: c.key }))}
          initialDealId={newTaskFor}
          onSubmit={(dealId, title, bucket, due, type, priority) => {
            createTask(dealId, title, bucket, due, type, priority);
            setNewTaskFor(null);
          }}
          onClose={() => setNewTaskFor(null)}
        />
      )}

      {newCompanyOpen && (
        <NewCompanyDialog
          busy={creating}
          onSubmit={createCompany}
          onClose={() => setNewCompanyOpen(false)}
        />
      )}

      {newDealFor !== null && (
        <NewDealDialog
          companies={companies}
          contactsFor={contactsFor}
          initialCompanyId={newDealFor}
          busy={creating}
          onSubmit={createDeal}
          onClose={() => setNewDealFor(null)}
        />
      )}

      {paletteOpen && (
        <CommandPalette
          onClose={() => setPaletteOpen(false)}
          onOpenDeal={openDeal}
          onOpenCompany={openCompany}
          onNewTask={() => setNewTaskFor(openDealId ?? "")}
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
