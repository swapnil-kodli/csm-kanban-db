import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, Check, Circle, FileText, Mail, MessageSquare, Phone, Plus,
  PresentationIcon, Users, X,
} from "lucide-react";
import type { AccountDetail, Activity, TaskBucket } from "../lib/types";
import { contactLabel, dayLabel, dueLabel, inr, inrExact, isoPlusDays, shortDate, velocityGlyph } from "../lib/format";
import { Sparkline } from "./Sparkline";

const ACTIVITY_ICONS: Record<string, typeof Mail> = {
  email: Mail,
  call: Phone,
  meeting: Users,
  qbr: PresentationIcon,
  note: FileText,
  update: MessageSquare,
};

type Tab = "activity" | "tasks" | "notes";

interface Props {
  detail: AccountDetail;
  onClose: () => void;
  onLogActivity: (payload: {
    type: string; summary: string; create_task?: { title: string; due_date: string; bucket: TaskBucket };
  }) => Promise<void>;
  onToggleTask: (taskId: string, done: boolean) => void;
  onCreateTask: (title: string, bucket: TaskBucket) => void;
  onOverride: () => void;
  onClearOverride: () => void;
  onToggleMilestone: (milestoneId: string, done: boolean) => void;
  onMarkDeparted: (contactId: string) => void;
  composerRef: React.RefObject<HTMLInputElement>;
}

export function Drawer({
  detail, onClose, onLogActivity, onToggleTask, onCreateTask, onOverride, onClearOverride,
  onToggleMilestone, onMarkDeparted, composerRef,
}: Props) {
  const [tab, setTab] = useState<Tab>("activity");
  const drawerRef = useRef<HTMLDivElement>(null);
  const { account, health, subscription, card } = detail;

  // Focus is trapped in the drawer and restored to the originating card on close.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const node = drawerRef.current;
    node?.querySelector<HTMLElement>("[data-autofocus]")?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !node) return;
      const focusables = node.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      opener?.focus?.();
    };
  }, [onClose]);

  const openTasks = detail.tasks.filter((t) => t.status === "open");
  const overdue = openTasks.filter((t) => t.overdue);
  const openRisks = detail.risks.filter((r) => r.status === "open");
  const escalations = openRisks.filter((r) => r.type === "escalation");
  const vel = velocityGlyph(health.velocity);

  const attentionBits: string[] = [];
  if (overdue.length) attentionBits.push(`${overdue.length} overdue task${overdue.length > 1 ? "s" : ""}`);
  if (escalations.length) attentionBits.push(`${escalations.length} open escalation${escalations.length > 1 ? "s" : ""}`);
  if (health.velocity !== null && health.velocity < 0) attentionBits.push(`health ▼${Math.abs(health.velocity)} in 30d`);
  if (subscription && subscription.days_to_renewal >= 0 && subscription.days_to_renewal <= 90) {
    attentionBits.push(`renews in ${subscription.days_to_renewal}d`);
  }
  const calm = attentionBits.length === 0;

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" ref={drawerRef} role="dialog" aria-modal="true" aria-label={`${account.name} details`}>
        <header className="drawer-head">
          <div className="drawer-title-row">
            <span className="health-dot" style={{ background: `var(--${health.dot})` }} />
            <span className="drawer-title">{account.name}</span>
            <span className="drawer-key">{account.key}</span>
            <div className="drawer-actions">
              <button type="button" className="btn" onClick={() => composerRef.current?.focus()}>
                Log activity
              </button>
              <button type="button" className="btn btn-icon" onClick={onClose} aria-label="Close" data-autofocus>
                <X size={15} strokeWidth={2.2} />
              </button>
            </div>
          </div>
          <div className="drawer-meta">
            {inr(account.arr)} ARR
            {subscription && ` · Renews ${shortDate(subscription.renewal_date)} (${subscription.days_to_renewal}d)`}
            {` · ${account.segment_label}`}
            {` · ${account.lifecycle_label}`}
            {account.city && ` · ${account.city}`}
          </div>
        </header>

        <div className={`attention-strip${calm ? " calm" : ""}`}>
          {calm ? <Check size={14} strokeWidth={2.4} /> : <AlertTriangle size={14} strokeWidth={2.4} />}
          <span>{calm ? "Nothing needs attention on this account." : attentionBits.join(" · ")}</span>
        </div>

        <div className="drawer-body">
          <div className="drawer-main">
            <div className="drawer-tabs" role="tablist">
              {([["activity", `Activity`], ["tasks", `Tasks (${openTasks.length})`], ["notes", "Notes"]] as const).map(
                ([key, label]) => (
                  <button key={key} type="button" role="tab" className="drawer-tab" aria-selected={tab === key} onClick={() => setTab(key as Tab)}>
                    {label}
                  </button>
                )
              )}
            </div>

            <div className="drawer-scroll">
              {tab === "activity" && <Timeline activities={detail.activities.filter((a) => a.type !== "note")} onCreateTask={onCreateTask} />}
              {tab === "notes" && <Timeline activities={detail.activities.filter((a) => a.type === "note")} onCreateTask={onCreateTask} />}
              {tab === "tasks" && (
                <div>
                  {detail.tasks.length === 0 && <p style={{ fontSize: 12.5, color: "var(--text-3)" }}>No tasks on this account.</p>}
                  {detail.tasks.map((t) => (
                    <div className="list-row" key={t.id}>
                      <button
                        type="button"
                        aria-label={t.status === "done" ? `Reopen ${t.title}` : `Complete ${t.title}`}
                        onClick={() => onToggleTask(t.id, t.status !== "done")}
                        style={{ display: "grid", placeItems: "center" }}
                      >
                        {t.status === "done" ? <Check size={14} strokeWidth={2.6} /> : <Circle size={14} strokeWidth={2} />}
                      </button>
                      <span style={{ textDecoration: t.status === "done" ? "line-through" : "none", color: t.status === "done" ? "var(--text-3)" : undefined }}>
                        {t.title}
                      </span>
                      <span className="list-role" style={{ marginLeft: "auto", color: t.overdue ? "var(--h-critical)" : undefined }}>
                        {t.status === "done" ? "Done" : dueLabel(t.days_until_due, t.overdue, t.overdue_days)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <Composer onLog={onLogActivity} composerRef={composerRef} />
          </div>

          <div className="drawer-side">
            <section className="side-block">
              <span className="side-label">Health</span>
              <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <span className="drawer-title" style={{ fontSize: 22 }}>{health.score}</span>
                <span className={`velocity ${vel.cls}`}>{vel.glyph}{health.velocity ? Math.abs(health.velocity) : ""}</span>
                <span className={`badge badge-${health.effective_band === "healthy" ? "green" : health.effective_band === "watch" ? "amber" : "red"}`}>
                  {health.effective_band_label}
                </span>
              </div>
              <Sparkline points={health.snapshots} color={`var(--${health.dot})`} />

              {health.components && (
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  {([["Usage", health.components.usage], ["Engagement", health.components.engagement],
                     ["Support", health.components.support], ["Sentiment", health.components.sentiment]] as const).map(([label, value]) => (
                    <div className="health-bar-row" key={label}>
                      <span className="health-bar-label">{label}</span>
                      <span className="health-bar-value">{value}</span>
                      <span className="health-bar"><span style={{ width: `${value}%` }} /></span>
                    </div>
                  ))}
                </div>
              )}

              {health.override && (
                <div className={`override-note${health.override.stale ? " stale" : ""}`}>
                  Score {health.score} ({health.computed_band_label}) · Overridden to {health.override.band_label} — “{health.override.reason}”
                  {health.override.stale && <><br />Override set {health.override.age_days}d ago — still accurate?</>}
                </div>
              )}

              <div style={{ display: "flex", gap: 8 }}>
                <button type="button" className="btn" onClick={onOverride}>
                  {health.override ? "Edit override" : "Override health"}
                </button>
                {health.override && (
                  <button type="button" className="btn subtle" onClick={onClearOverride}>Clear</button>
                )}
              </div>
            </section>

            <section className="side-block">
              <span className="side-label">Why this ranks {detail.attention.score}</span>
              {detail.attention.terms.filter((t) => t.value).map((t) => (
                <div className="attention-term" key={t.label}>
                  <b>{t.label}</b> <span>{t.detail}</span> <em style={{ marginLeft: "auto" }}>+{t.value}</em>
                </div>
              ))}
              {detail.attention.terms.every((t) => !t.value) && (
                <span style={{ fontSize: 12, color: "var(--text-3)" }}>Nothing is pulling this account up the queue.</span>
              )}
            </section>

            {subscription && (
              <section className="side-block">
                <span className="side-label">Renewal</span>
                <div style={{ fontSize: 12.5 }}>
                  {shortDate(subscription.renewal_date)} · {inr(account.arr)} ·{" "}
                  {subscription.auto_renew ? "Auto-renew on" : "Manual renewal"}
                </div>
                <span className="side-label" style={{ marginTop: 6 }}>Subscription</span>
                {subscription.line_items.map((li) => (
                  <div className="list-row" key={li.offering}>
                    <span>{li.offering}</span>
                    <span className="list-role" style={{ marginLeft: "auto" }}>
                      {li.qty.toLocaleString("en-IN")} × ₹{li.rate}
                    </span>
                  </div>
                ))}
                <div style={{ fontSize: 11.5, color: "var(--text-3)", marginTop: 4 }}>
                  Total {inrExact(account.arr)}
                </div>
              </section>
            )}

            <section className="side-block">
              <span className="side-label">Contacts</span>
              {detail.contacts.map((c) => (
                <div className="list-row" key={c.id} style={{ flexDirection: "column", alignItems: "stretch", gap: 4 }}>
                  <span style={{ display: "flex", gap: 6, alignItems: "baseline" }}>
                    <span>{c.name}</span>
                    <span className="list-role">{c.role}</span>
                  </span>
                  <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                    {c.is_champion && <span className="pill champion">★ Champion</span>}
                    {c.is_economic_buyer && <span className="pill">₹ Econ buyer</span>}
                    {c.status === "departed" ? (
                      <span className="pill departed">Departed</span>
                    ) : (
                      <button type="button" className="pill" onClick={() => onMarkDeparted(c.id)} title="Mark departed — fires a critical alert">
                        Mark departed
                      </button>
                    )}
                  </span>
                </div>
              ))}
            </section>

            {openRisks.length > 0 && (
              <section className="side-block">
                <span className="side-label">Open risks</span>
                {openRisks.map((r) => (
                  <div className="list-row" key={r.id} style={{ alignItems: "flex-start" }}>
                    <span className={`pill ${r.severity === "high" ? "departed" : ""}`}>{r.type.replace("_", " ")}</span>
                    <span style={{ fontSize: 12, color: "var(--text-2)", lineHeight: 1.4 }}>{r.note}</span>
                  </div>
                ))}
              </section>
            )}

            {detail.milestones.length > 0 && (
              <section className="side-block">
                <span className="side-label">Onboarding</span>
                {detail.milestones.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    className={`milestone-row${m.status === "done" ? " done" : ""}${m.overdue ? " overdue" : ""}`}
                    onClick={() => onToggleMilestone(m.id, m.status !== "done")}
                  >
                    {m.status === "done" ? <Check size={14} strokeWidth={2.6} /> : <Circle size={14} strokeWidth={2} />}
                    <span>{m.label}</span>
                    {m.overdue && <span className="pill departed" style={{ marginLeft: "auto" }}>Overdue</span>}
                  </button>
                ))}
              </section>
            )}

            <section className="side-block">
              <span className="side-label">Context</span>
              <div style={{ fontSize: 12, color: "var(--text-2)", lineHeight: 1.6 }}>
                {contactLabel(account.days_since_contact)}
                <br />
                Owner {account.owner?.name}
                <br />
                Attention score {card.attention_score}
              </div>
            </section>
          </div>
        </div>
      </aside>
    </>
  );
}

function Timeline({ activities, onCreateTask }: { activities: Activity[]; onCreateTask: (title: string, bucket: TaskBucket) => void }) {
  const grouped = useMemo(() => {
    const map = new Map<string, Activity[]>();
    activities.forEach((a) => {
      const label = dayLabel(a.occurred_at);
      map.set(label, [...(map.get(label) ?? []), a]);
    });
    return [...map.entries()];
  }, [activities]);

  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  if (!activities.length) {
    return <p style={{ fontSize: 12.5, color: "var(--text-3)" }}>Nothing logged yet. Use the composer below.</p>;
  }

  return (
    <div>
      {grouped.map(([label, items]) => (
        <div key={label}>
          <div className="timeline-day">{label}</div>
          {items.map((a) => {
            const Icon = ACTIVITY_ICONS[a.type] ?? MessageSquare;
            const isOpen = !!expanded[a.id];
            return (
              <div className="timeline-item" key={a.id}>
                <span className="timeline-icon"><Icon size={12} strokeWidth={2.2} /></span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <button
                    type="button"
                    className="timeline-summary"
                    style={{ textAlign: "left", display: "block", width: "100%" }}
                    onClick={() => a.body && setExpanded((s) => ({ ...s, [a.id]: !isOpen }))}
                  >
                    {a.summary}
                  </button>
                  <div className="timeline-sub">
                    {a.type.toUpperCase()}
                    {a.contact_name ? ` · ${a.contact_name}` : ""}
                    {a.body ? (isOpen ? " · collapse" : " · expand") : ""}
                  </div>
                  {isOpen && a.body && <div className="timeline-body">{a.body}</div>}
                </div>
                <button
                  type="button"
                  className="timeline-add"
                  onClick={() => onCreateTask(`Follow up: ${a.summary}`, "this_week")}
                >
                  + task
                </button>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

/**
 * The most important control in the app. One field, a type selector and a
 * toggle. Logging must take under 10 seconds — treat every extra click as a bug.
 */
function Composer({
  onLog, composerRef,
}: {
  onLog: Props["onLogActivity"];
  composerRef: React.RefObject<HTMLInputElement>;
}) {
  const [type, setType] = useState("call");
  const [summary, setSummary] = useState("");
  const [alsoTask, setAlsoTask] = useState(false);
  const [taskTitle, setTaskTitle] = useState("");
  const [taskDue, setTaskDue] = useState(isoPlusDays(3));
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!summary.trim() || busy) return;
    setBusy(true);
    try {
      await onLog({
        type,
        summary: summary.trim(),
        create_task:
          alsoTask && taskTitle.trim()
            ? { title: taskTitle.trim(), due_date: taskDue, bucket: "this_week" }
            : undefined,
      });
      setSummary("");
      setTaskTitle("");
      setAlsoTask(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="composer" onSubmit={submit}>
      <div className="composer-row">
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Activity type">
          {["call", "email", "meeting", "qbr", "note", "update"].map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <input
          ref={composerRef}
          type="text"
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder="What happened?"
          aria-label="Activity summary"
        />
        <button type="submit" className="btn primary" disabled={!summary.trim() || busy}>
          {busy ? "Saving…" : "Log"}
        </button>
      </div>

      <label className="composer-toggle">
        <input type="checkbox" checked={alsoTask} onChange={(e) => setAlsoTask(e.target.checked)} />
        Also create next action
      </label>

      {alsoTask && (
        <div className="composer-next">
          <input
            type="text"
            value={taskTitle}
            onChange={(e) => setTaskTitle(e.target.value)}
            placeholder="Next action…"
            aria-label="Next action title"
            style={{ flex: 1 }}
          />
          <input type="date" value={taskDue} onChange={(e) => setTaskDue(e.target.value)} aria-label="Due date" />
        </div>
      )}
    </form>
  );
}

export function NewTaskDialog({
  accountName, onSubmit, onClose,
}: {
  accountName: string;
  onSubmit: (title: string, bucket: TaskBucket, due: string) => void;
  onClose: () => void;
}) {
  const [title, setTitle] = useState("");
  const [bucket, setBucket] = useState<TaskBucket>("today");
  const [due, setDue] = useState(isoPlusDays(0));

  return (
    <div className="dialog-scrim" onClick={onClose}>
      <form
        className="dialog"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) onSubmit(title.trim(), bucket, due);
        }}
      >
        <h3>New task · {accountName}</h3>
        <div>
          <label htmlFor="nt-title">Title</label>
          <input id="nt-title" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="What needs doing?" />
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <div style={{ flex: 1 }}>
            <label htmlFor="nt-bucket">Column</label>
            <select id="nt-bucket" value={bucket} onChange={(e) => setBucket(e.target.value as TaskBucket)}>
              <option value="today">Today</option>
              <option value="this_week">This Week</option>
              <option value="follow_up">Follow-Up</option>
              <option value="waiting">Waiting</option>
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <label htmlFor="nt-due">Due</label>
            <input id="nt-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </div>
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn subtle" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={!title.trim()}>
            <Plus size={14} strokeWidth={2.4} /> Create
          </button>
        </div>
      </form>
    </div>
  );
}
