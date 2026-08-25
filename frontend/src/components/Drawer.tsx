import { useEffect, useMemo, useRef, useState } from "react";
import { Sparkline } from "./Sparkline";
import { TaskRow } from "./Cards";
import { EmailThreadsBoundary, EmailThreadsPanel } from "./EmailThreads";
import { formatINR, inrExact, isoPlusDays, relativeDate, shortDate, velocityGlyph } from "../lib/format";
import type { AccountDetail, ClientType, CommMode, Mode, TaskBucket, Workstream, TaskCard } from "../lib/types";

const WORKSTREAMS: { value: Workstream; label: string }[] = [
  { value: "bot_making", label: "Bot-Making" },
  { value: "data_procurement", label: "Data Procurement" },
  { value: "voice_ai_calling", label: "Voice AI Calling" },
];
const COLUMNS = [
  { value: "ready_for_onboarding", label: "Ready for Onboarding" },
  { value: "onboarding", label: "Onboarding" },
  { value: "working", label: "Working" },
  { value: "approval", label: "Approval" },
  { value: "launch", label: "Launch" },
];
const MODES: { value: Mode; label: string }[] = [
  { value: "pilot", label: "Pilot" },
  { value: "customer", label: "Customer" },
];
const CLIENT_TYPES: { value: ClientType; label: string }[] = [
  { value: "voice_ai_only", label: "Voice AI only" },
  { value: "data_plus_voice_ai", label: "Data + Voice AI" },
];
const COMM: { value: CommMode; label: string }[] = [
  { value: "whatsapp", label: "WhatsApp" },
  { value: "email", label: "Email" },
];

function Panel({
  title,
  children,
  aside,
}: {
  title: string;
  children: React.ReactNode;
  aside?: React.ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panel-head">
        <h3>{title}</h3>
        {aside}
      </header>
      {children}
    </section>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <div className="field-value">{children}</div>
    </div>
  );
}

export function Drawer({
  detail,
  onClose,
  onPatch,
  onLogActivity,
  onToggleTask,
  onOverride,
  onClearOverride,
}: {
  detail: AccountDetail;
  onClose: () => void;
  onPatch: (patch: Record<string, unknown>) => void;
  onLogActivity: (payload: {
    type: string;
    summary: string;
    create_task?: { title: string; due_date: string; bucket: TaskBucket };
  }) => void;
  onToggleTask: (task: TaskCard) => void;
  onOverride: (band: string, reason: string) => void;
  onClearOverride: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [logType, setLogType] = useState("call");
  const [summary, setSummary] = useState("");
  const [alsoTask, setAlsoTask] = useState(false);
  const [taskTitle, setTaskTitle] = useState("");
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideBand, setOverrideBand] = useState("at_risk");
  const [overrideReason, setOverrideReason] = useState("");
  const [note, setNote] = useState(detail.health.note ?? "");

  const { account, poc, health, commercials, attention } = detail;
  const vel = velocityGlyph(health.velocity);

  // The composer defaults to whichever channel this client actually uses.
  useEffect(() => {
    const first = detail.comm_modes[0]?.value;
    if (first === "email") setLogType("email");
    else if (first === "whatsapp") setLogType("call");
  }, [detail.comm_modes]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("button, input, select")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const grouped = useMemo(() => {
    const out: Record<string, typeof detail.activities> = {};
    for (const a of detail.activities) {
      const day = a.occurred_at.slice(0, 10);
      (out[day] ||= []).push(a);
    }
    return Object.entries(out);
  }, [detail.activities]);

  function submitLog() {
    if (!summary.trim()) return;
    onLogActivity({
      type: logType,
      summary: summary.trim(),
      create_task:
        alsoTask && taskTitle.trim()
          ? { title: taskTitle.trim(), bucket: "this_week" as TaskBucket, due_date: isoPlusDays(3) }
          : undefined,
    });
    setSummary("");
    setTaskTitle("");
    setAlsoTask(false);
  }

  return (
    <>
      <div className="scrim" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" ref={ref} role="dialog" aria-modal="true" aria-label={account.name}>
        <header className="drawer-head">
          <div className="drawer-title-row">
            <span className={`health-dot dot-${health.dot}`} aria-hidden="true" />
            <h2>{account.name}</h2>
            <span className="card-key">{account.key}</span>
            <span className={`chip chip-${account.mode}`}>{account.mode_label.toUpperCase()}</span>
            <span className="chip chip-grey">{account.client_type_label}</span>
            <span className="chip chip-grey">{account.column_label}</span>
            <button className="drawer-close" onClick={onClose} aria-label="Close">
              ×
            </button>
          </div>
          {(account.stalled_handoff || account.column_stalled || health.override?.stale) && (
            <div className="attention-strip">
              {account.stalled_handoff && <span>Handoff stalled</span>}
              {account.column_stalled && (
                <span>{account.days_in_column}d in {account.column_label}</span>
              )}
              {health.override?.stale && (
                <span>Override set {health.override.age_days}d ago — still accurate?</span>
              )}
            </div>
          )}
        </header>

        <div className="drawer-body">
          <Panel title="Overview">
            <Field label="Client Type">
              <select
                value={account.client_type}
                onChange={(e) => onPatch({ client_type: e.target.value })}
              >
                {CLIENT_TYPES.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Mode">
              <select value={account.mode} onChange={(e) => onPatch({ mode: e.target.value })}>
                {MODES.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Workstream">
              {/* Edited here only — never changed by dragging between columns. */}
              <select
                value={account.workstream}
                onChange={(e) => onPatch({ workstream: e.target.value })}
              >
                {WORKSTREAMS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Column">
              <select value={account.column} onChange={(e) => onPatch({ column: e.target.value })}>
                {COLUMNS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </Field>
          </Panel>

          <Panel title="POC">
            <Field label="Name">
              <input
                defaultValue={poc.name ?? ""}
                onBlur={(e) => onPatch({ poc_name: e.target.value })}
              />
            </Field>
            <Field label="Email">
              <input
                type="email"
                defaultValue={poc.email ?? ""}
                onBlur={(e) => onPatch({ poc_email: e.target.value })}
              />
            </Field>
            <Field label="Phone">
              <input
                defaultValue={poc.phone ?? ""}
                onBlur={(e) => onPatch({ poc_phone: e.target.value })}
              />
            </Field>
          </Panel>

          <Panel title="Mode of Communication">
            <div className="chip-row">
              {COMM.map((c) => {
                const on = detail.comm_modes.some((m) => m.value === c.value);
                return (
                  <button
                    key={c.value}
                    className={`chip chip-toggle ${on ? "chip-on" : ""}`}
                    aria-pressed={on}
                    onClick={() =>
                      onPatch({
                        comm_modes: on
                          ? detail.comm_modes.filter((m) => m.value !== c.value).map((m) => m.value)
                          : [...detail.comm_modes.map((m) => m.value), c.value],
                      })
                    }
                  >
                    {c.label}
                  </button>
                );
              })}
            </div>
          </Panel>

          {detail.show_email_threads && (
            <Panel title="Email Threads">
              <EmailThreadsBoundary>
                <EmailThreadsPanel
                  accountId={account.id}
                  onLogActivity={(subject) =>
                    onLogActivity({ type: "email", summary: subject })
                  }
                />
              </EmailThreadsBoundary>
            </Panel>
          )}

          <Panel title="Health Check">
            <div className="health-readout">
              <span className={`health-big text-${health.dot}`}>{health.score}</span>
              <span className={`velocity ${vel.cls}`}>{vel.glyph}{health.velocity != null && health.velocity !== 0 ? Math.abs(health.velocity) : ""}</span>
              <span className="chip chip-grey">{health.effective_band_label}</span>
            </div>
            <Sparkline points={health.snapshots} color={`var(--${health.dot})`} />
            {health.components && (
              <div className="components">
                {Object.entries(health.components).map(([k, v]) => (
                  <div className="component" key={k}>
                    <span className="component-name">{k}</span>
                    <span className="component-bar">
                      <span style={{ width: `${v}%` }} />
                    </span>
                    <span className="component-value">{v}</span>
                  </div>
                ))}
              </div>
            )}
            {health.override && (
              <p className="override-note">
                Score {health.score} ({health.computed_band_label}) · Overridden to{" "}
                {health.override.band_label} — “{health.override.reason}”
                <button className="btn btn-sm" onClick={onClearOverride}>Clear</button>
              </p>
            )}
            <Field label="Health note">
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                onBlur={() => onPatch({ health_note: note })}
                placeholder="What did this check find?"
              />
            </Field>
            {!overrideOpen ? (
              <button className="btn btn-sm" onClick={() => setOverrideOpen(true)}>
                Override health
              </button>
            ) : (
              <div className="override-form">
                <select value={overrideBand} onChange={(e) => setOverrideBand(e.target.value)}>
                  <option value="healthy">Healthy</option>
                  <option value="watch">Watch</option>
                  <option value="at_risk">At Risk</option>
                  <option value="critical">Critical</option>
                </select>
                <input
                  placeholder="Reason (required)"
                  value={overrideReason}
                  onChange={(e) => setOverrideReason(e.target.value)}
                />
                <button
                  className="btn btn-sm"
                  disabled={overrideReason.trim().length < 3}
                  onClick={() => {
                    onOverride(overrideBand, overrideReason.trim());
                    setOverrideOpen(false);
                    setOverrideReason("");
                  }}
                >
                  Save
                </button>
              </div>
            )}
          </Panel>

          <Panel title="Costing">
            <Field label="Quoted total">
              <strong>{inrExact(commercials.quoted_total)}</strong>
            </Field>
            <Field label="Quoted on">
              {commercials.quoted_at ? shortDate(commercials.quoted_at) : "—"}
            </Field>
            <ul className="line-items">
              {commercials.quoted_line_items.map((li, i) => (
                <li key={i}>
                  <span>{li.offering}</span>
                  <span className="li-calc">
                    {li.qty.toLocaleString("en-IN")} × ₹{li.rate}
                  </span>
                  <span className="li-total">{formatINR(li.qty * li.rate)}</span>
                </li>
              ))}
            </ul>
            {commercials.quote_notes && <p className="quote-notes">{commercials.quote_notes}</p>}
          </Panel>

          <Panel title="PNL">
            {/* Quoted sits beside recognised on purpose: the gap is the signal. */}
            <div className="pnl-grid">
              <div>
                <span className="field-label">Quoted</span>
                <strong>{inrExact(commercials.quoted_total)}</strong>
              </div>
              <div>
                <span className="field-label">Recognised</span>
                <strong>{inrExact(commercials.revenue_recognised)}</strong>
              </div>
              <div>
                <span className="field-label">Drift</span>
                <strong className={commercials.quote_gap < 0 ? "text-h-critical" : "text-h-healthy"}>
                  {commercials.quote_gap >= 0 ? "+" : ""}
                  {inrExact(commercials.quote_gap)}
                </strong>
              </div>
            </div>
            <ul className="line-items">
              {commercials.cost_items.map((c, i) => (
                <li key={i}>
                  <span>{c.label}</span>
                  <span className="li-total">{formatINR(c.amount)}</span>
                </li>
              ))}
              {commercials.cost_items.length === 0 && <li className="panel-muted">No costs recorded</li>}
            </ul>
            <div className="pnl-grid">
              <div>
                <span className="field-label">Total cost</span>
                <strong>{inrExact(commercials.total_cost)}</strong>
              </div>
              <div>
                <span className="field-label">Gross margin</span>
                <strong>{inrExact(commercials.gross_margin)}</strong>
              </div>
              <div>
                <span className="field-label">Margin</span>
                <strong className={`text-${commercials.margin_band}`}>
                  {commercials.margin_pct === null ? "—" : `${commercials.margin_pct}%`}
                </strong>
              </div>
            </div>
            {commercials.margin_pct === null && (
              <p className="panel-muted">Nothing billed yet — margin is unknown, not zero.</p>
            )}
          </Panel>

          <Panel title={`Tasks (${detail.tasks.filter((t) => t.status === "open").length})`}>
            {detail.tasks.map((t) => (
              <TaskRow key={t.id} task={t} onToggle={onToggleTask} />
            ))}
            {detail.tasks.length === 0 && <p className="panel-muted">No tasks</p>}
          </Panel>

          <Panel title="Activity" aside={<span className="panel-muted">{relativeDate(account.last_contact_at)}</span>}>
            <div className="composer">
              <select value={logType} onChange={(e) => setLogType(e.target.value)}>
                <option value="call">Call</option>
                <option value="email">Email</option>
                <option value="meeting">Meeting</option>
                <option value="note">Note</option>
                <option value="qbr">QBR</option>
              </select>
              <input
                placeholder="What happened?"
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submitLog()}
              />
              <button className="btn btn-sm" onClick={submitLog} disabled={!summary.trim()}>
                Log
              </button>
            </div>
            <label className="composer-toggle">
              <input type="checkbox" checked={alsoTask} onChange={(e) => setAlsoTask(e.target.checked)} />
              Also create next action
            </label>
            {alsoTask && (
              <input
                className="composer-task"
                placeholder="Next action"
                value={taskTitle}
                onChange={(e) => setTaskTitle(e.target.value)}
              />
            )}
            <div className="timeline">
              {grouped.map(([day, items]) => (
                <div className="timeline-day" key={day}>
                  <p className="timeline-date">{shortDate(day)}</p>
                  {items.map((a) => (
                    <div className="timeline-item" key={a.id}>
                      <span className={`t-type t-${a.type}`}>{a.type}</span>
                      <p className="t-summary">{a.summary}</p>
                      {a.body && <p className="t-body">{a.body}</p>}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Why this ranks">
            <ul className="terms">
              {attention.terms
                .filter((t) => t.value)
                .map((t) => (
                  <li key={t.label}>
                    <span>{t.label}</span>
                    <span className="term-detail">{t.detail}</span>
                    <span className="term-value">+{t.value}</span>
                  </li>
                ))}
              {attention.terms.every((t) => !t.value) && (
                <li className="panel-muted">Nothing flagged</li>
              )}
            </ul>
          </Panel>
        </div>
      </aside>
    </>
  );
}
