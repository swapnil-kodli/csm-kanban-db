import { useEffect, useRef, useState } from "react";
import { Sparkline } from "./Sparkline";
import { TaskRow } from "./Cards";
import { EmailThreadsBoundary, EmailThreadsPanel } from "./EmailThreads";
import { formatINR, inrExact, velocityGlyph } from "../lib/format";
import type { CommMode, CostItem, DealDetail, LineItem, Mode, Outcome, TaskCard, Workstream } from "../lib/types";

const WORKSTREAMS: { value: Workstream; label: string }[] = [
  { value: "bot_making", label: "Bot-Making" },
  { value: "data_procurement", label: "Data Procurement" },
  { value: "voice_ai_calling", label: "Voice AI Calling" },
];
const MODES: { value: Mode; label: string }[] = [
  { value: "pilot", label: "Pilot" },
  { value: "customer", label: "Customer" },
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
  onToggleTask,
  onAddTask,
  onOverride,
  onClearOverride,
  onAddContact,
  onPatchContact,
  onDeleteContact,
  onDeleteDeal,
  onOpenCompany,
  onSetOutcome,
}: {
  detail: DealDetail;
  onClose: () => void;
  onPatch: (patch: Record<string, unknown>) => void;
  onToggleTask: (task: TaskCard) => void;
  onAddTask: () => void;
  onOverride: (band: string, reason: string) => void;
  onClearOverride: () => void;
  onAddContact: () => void;
  onPatchContact: (id: string, patch: Record<string, unknown>) => void;
  onDeleteContact: (id: string) => void;
  onDeleteDeal: () => void;
  onOpenCompany: () => void;
  onSetOutcome: (outcome: Outcome, reason: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideBand, setOverrideBand] = useState("at_risk");
  const [overrideReason, setOverrideReason] = useState("");
  const [note, setNote] = useState(detail.health.note ?? "");
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Held rather than applied immediately: `lost` needs a reason, and the server
  // rejects it without one, so the chip opens a prompt instead of firing.
  const [outcomeDraft, setOutcomeDraft] = useState<Outcome | null>(null);
  const [outcomeReason, setOutcomeReason] = useState("");

  const { deal, company, poc, health, commercials, attention } = detail;
  const vel = velocityGlyph(health.velocity);

  const lineItemsSum = commercials.quoted_line_items.reduce(
    (sum, li) => sum + li.qty * li.rate,
    0
  );

  function writeLineItems(next: LineItem[]) {
    onPatch({ quoted_line_items: next });
  }
  function patchLineItem(index: number, patch: Partial<LineItem>) {
    const next = commercials.quoted_line_items.map((li, i) =>
      i === index ? { ...li, ...patch } : li
    );
    writeLineItems(next);
  }
  function addLineItem() {
    writeLineItems([...commercials.quoted_line_items, { offering: "QLs", qty: 0, rate: 500 }]);
  }
  function removeLineItem(index: number) {
    writeLineItems(commercials.quoted_line_items.filter((_, i) => i !== index));
  }

  function writeCostItems(next: CostItem[]) {
    onPatch({ cost_items: next });
  }
  function patchCostItem(index: number, patch: Partial<CostItem>) {
    writeCostItems(
      commercials.cost_items.map((c, i) => (i === index ? { ...c, ...patch } : c))
    );
  }
  function addCostItem() {
    writeCostItems([...commercials.cost_items, { label: "New cost", amount: 0 }]);
  }
  function removeCostItem(index: number) {
    writeCostItems(commercials.cost_items.filter((_, i) => i !== index));
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("button, input, select")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="scrim" onClick={onClose} aria-hidden="true" />
      <aside className="drawer" ref={ref} role="dialog" aria-modal="true" aria-label={deal.name}>
        <header className="drawer-head">
          <div className="drawer-title-row">
            <span className={`health-dot dot-${health.dot}`} aria-hidden="true" />
            <h2>{deal.name}</h2>
            <span className="card-key">{deal.key}</span>
            <span className={`chip chip-${deal.mode}`}>{deal.mode_label.toUpperCase()}</span>
            {company && (
              <button type="button" className="chip chip-link" onClick={onOpenCompany}>
                {company.name}
              </button>
            )}
            <span className="chip chip-grey">{deal.column_label}</span>
            {deal.outcome !== "active" && (
              <span className={`chip chip-${deal.outcome}`}>
                {deal.outcome.toUpperCase()}
              </span>
            )}
            <button className="drawer-close" onClick={onClose} aria-label="Close">
              ×
            </button>
          </div>
          {(deal.stalled_handoff || deal.column_stalled || health.override?.stale) && (
            <div className="attention-strip">
              {deal.stalled_handoff && <span>Handoff stalled</span>}
              {deal.column_stalled && (
                <span>{deal.days_in_column}d in {deal.column_label}</span>
              )}
              {health.override?.stale && (
                <span>Override set {health.override.age_days}d ago — still accurate?</span>
              )}
            </div>
          )}
          {/* The ranking has to stay interrogable. Terms keep the order the
              formula weights them, so this reads as an explanation of the
              scoring rather than a leaderboard of this deal's worst numbers. */}
          {attention.summary && (
            <p className="attention-why">
              <span className="attention-rank">Attention {Math.round(attention.score)}</span>
              {attention.summary}
            </p>
          )}
        </header>

        <div className="drawer-body">
          <Panel title="Overview">
            {/* Client Type moved to the company: it describes WHO the client
                is, not what this engagement does, and one company's two deals
                cannot disagree about it. Shown here read-only, editable on the
                company view — one field, one place. */}
            <Field label="Client">
              {company ? (
                <button type="button" className="link-chip" onClick={onOpenCompany}>
                  {company.name} · {company.client_type_label}
                </button>
              ) : (
                <span className="panel-muted">Unknown</span>
              )}
            </Field>
            <Field label="POC">
              {/* Only this company's contacts. The server enforces the same set
                  — a POC from another company is rejected regardless of what
                  the picker offers. */}
              <select
                value={deal.poc_id}
                onChange={(e) => onPatch({ poc_id: e.target.value })}
              >
                {detail.contacts.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}{c.role ? ` · ${c.role}` : ""}
                  </option>
                ))}
              </select>
              {poc?.email && <span className="field-sub">{poc.email}</span>}
            </Field>
            <Field label="Mode">
              <select value={deal.mode} onChange={(e) => onPatch({ mode: e.target.value })}>
                {MODES.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Workstream">
              {/* Edited here only — never changed by dragging between columns. */}
              <select
                value={deal.workstream}
                onChange={(e) => onPatch({ workstream: e.target.value })}
              >
                {WORKSTREAMS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </Field>
            {/* Column is deliberately not editable here. Drag is the only way
                to move an engagement through the pipeline — two paths to the
                same state drift apart. The current column shows as a read-only
                chip in the header. */}
            <Field label="Last contact">
              {/* Hand-maintained since activity logging was removed, so it has
                  to be one click. Unset is neutral everywhere it is read, never
                  a penalty — a deal nobody filled in is not a deal
                  nobody called. */}
              <div className="date-set">
                <input
                  type="date"
                  value={deal.last_contact_at ? deal.last_contact_at.slice(0, 10) : ""}
                  onChange={(e) =>
                    onPatch({ last_contact_at: e.target.value ? `${e.target.value}T12:00:00` : null })
                  }
                />
                <button
                  className="btn btn-sm"
                  onClick={() => onPatch({ last_contact_at: new Date().toISOString() })}
                >
                  Today
                </button>
                <span className="panel-muted">
                  {deal.days_since_contact === null
                    ? "not recorded"
                    : `${deal.days_since_contact}d ago`}
                </span>
              </div>
            </Field>
          </Panel>

          <Panel
            title="Contacts"
            aside={
              <button className="btn btn-sm" onClick={() => onAddContact()}>
                + Add
              </button>
            }
          >
            <ul className="contact-list">
              {detail.contacts.map((c) => (
                <li key={c.id} className={c.is_primary ? "contact primary" : "contact"}>
                  <button
                    className="contact-star"
                    aria-label={c.is_primary ? `${c.name} is the primary contact` : `Make ${c.name} primary`}
                    aria-pressed={c.is_primary}
                    title={c.is_primary ? "Primary contact" : "Set as primary"}
                    onClick={() => !c.is_primary && onPatchContact(c.id, { is_primary: true })}
                  >
                    {c.is_primary ? "★" : "☆"}
                  </button>
                  <div className="contact-fields">
                    <input
                      key={`${c.id}:name:${c.name}`}
                      defaultValue={c.name}
                      aria-label="Name"
                      onBlur={(e) =>
                        e.target.value.trim() !== c.name &&
                        onPatchContact(c.id, { name: e.target.value.trim() })
                      }
                    />
                    <input
                      key={`${c.id}:role:${c.role}`}
                      defaultValue={c.role}
                      aria-label="Role"
                      onBlur={(e) =>
                        e.target.value.trim() !== c.role &&
                        onPatchContact(c.id, { role: e.target.value.trim() })
                      }
                    />
                    <input
                      key={`${c.id}:email:${c.email ?? ""}`}
                      type="email"
                      defaultValue={c.email ?? ""}
                      aria-label="Email"
                      onBlur={(e) =>
                        e.target.value.trim() !== (c.email ?? "") &&
                        onPatchContact(c.id, { email: e.target.value.trim() })
                      }
                    />
                    <input
                      key={`${c.id}:phone:${c.phone ?? ""}`}
                      defaultValue={c.phone ?? ""}
                      aria-label="Phone"
                      onBlur={(e) =>
                        e.target.value.trim() !== (c.phone ?? "") &&
                        onPatchContact(c.id, { phone: e.target.value.trim() })
                      }
                    />
                  </div>
                  <div className="contact-flags">
                    {c.is_champion && <span className="chip chip-grey">Champion</span>}
                    {c.is_economic_buyer && <span className="chip chip-grey">Econ buyer</span>}
                    {c.status === "departed" && <span className="chip chip-red">Departed</span>}
                  </div>
                  <button
                    className="btn btn-sm subtle"
                    onClick={() => onDeleteContact(c.id)}
                    aria-label={`Delete ${c.name}`}
                  >
                    ×
                  </button>
                </li>
              ))}
              {detail.contacts.length === 0 && <li className="panel-muted">No contacts yet</li>}
            </ul>
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
                {/* Activity logging is gone, so a thread's value now is as
                    evidence of contact: its date sets the field the engagement
                    score reads. */}
                <EmailThreadsPanel
                  dealId={deal.id}
                  onMarkContacted={(iso) => onPatch({ last_contact_at: iso })}
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
              {/* Independent of the line items on purpose. A soft hint when they
                  disagree, never an overwrite of what someone typed. */}
              <input
                type="number"
                min={0}
                key={`qt:${commercials.quoted_total}`}
                defaultValue={commercials.quoted_total}
                onBlur={(e) => {
                  const v = Number(e.target.value);
                  if (v !== commercials.quoted_total) onPatch({ quoted_total: v });
                }}
              />
            </Field>
            {lineItemsSum !== commercials.quoted_total && (
              <p className="soft-hint">
                Line items add up to {inrExact(lineItemsSum)}, which differs from the
                quoted total by {inrExact(Math.abs(lineItemsSum - commercials.quoted_total))}.
              </p>
            )}
            <Field label="Quoted on">
              <input
                type="date"
                key={`qa:${commercials.quoted_at ?? ""}`}
                defaultValue={commercials.quoted_at ?? ""}
                onBlur={(e) => onPatch({ quoted_at: e.target.value || null })}
              />
            </Field>

            <ul className="editable-rows">
              {commercials.quoted_line_items.map((li, i) => (
                <li key={i}>
                  <input
                    aria-label="Offering"
                    defaultValue={li.offering}
                    onBlur={(e) => patchLineItem(i, { offering: e.target.value })}
                  />
                  <input
                    type="number" min={0} aria-label="Quantity"
                    defaultValue={li.qty}
                    onBlur={(e) => patchLineItem(i, { qty: Number(e.target.value) })}
                  />
                  <input
                    type="number" min={0} aria-label="Rate"
                    defaultValue={li.rate}
                    onBlur={(e) => patchLineItem(i, { rate: Number(e.target.value) })}
                  />
                  <span className="li-total">{formatINR(li.qty * li.rate)}</span>
                  <button className="btn btn-sm subtle" aria-label="Remove line" onClick={() => removeLineItem(i)}>×</button>
                </li>
              ))}
            </ul>
            <button className="btn btn-sm" onClick={addLineItem}>+ Add line item</button>

            <Field label="Quote notes">
              <textarea
                key={`qn:${commercials.quote_notes ?? ""}`}
                defaultValue={commercials.quote_notes ?? ""}
                onBlur={(e) => onPatch({ quote_notes: e.target.value })}
              />
            </Field>
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
                <input
                  type="number" min={0}
                  key={`rr:${commercials.revenue_recognised}`}
                  defaultValue={commercials.revenue_recognised}
                  onBlur={(e) => {
                    const v = Number(e.target.value);
                    if (v !== commercials.revenue_recognised) onPatch({ revenue_recognised: v });
                  }}
                />
              </div>
              <div>
                <span className="field-label">Drift</span>
                <strong className={commercials.quote_gap < 0 ? "text-h-critical" : "text-h-healthy"}>
                  {commercials.quote_gap >= 0 ? "+" : ""}
                  {inrExact(commercials.quote_gap)}
                </strong>
              </div>
            </div>

            <ul className="editable-rows">
              {commercials.cost_items.map((c, i) => (
                <li key={i}>
                  <input
                    aria-label="Cost label"
                    defaultValue={c.label}
                    onBlur={(e) => patchCostItem(i, { label: e.target.value })}
                  />
                  <input
                    type="number" min={0} aria-label="Amount"
                    defaultValue={c.amount}
                    onBlur={(e) => patchCostItem(i, { amount: Number(e.target.value) })}
                  />
                  <button className="btn btn-sm subtle" aria-label="Remove cost" onClick={() => removeCostItem(i)}>×</button>
                </li>
              ))}
              {commercials.cost_items.length === 0 && <li className="panel-muted">No costs recorded</li>}
            </ul>
            <button className="btn btn-sm" onClick={addCostItem}>+ Add cost</button>

            {/* Derived, never editable. A typed margin that disagrees with its
                own inputs is worse than no margin at all. */}
            <div className="pnl-grid derived">
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

          <Panel
            title={`Tasks (${detail.tasks.filter((t) => t.status === "open").length})`}
            aside={
              <button className="btn btn-sm" onClick={onAddTask}>
                + Add task
              </button>
            }
          >
            {detail.tasks.map((t) => (
              <TaskRow key={t.id} task={t} onToggle={onToggleTask} />
            ))}
            {detail.tasks.length === 0 && <p className="panel-muted">No tasks</p>}
          </Panel>

          {/* Outcome is a separate axis from the column, and the UI has to keep
              them separate too: a deal can be lost from anywhere, and Launch is
              where active work ends up rather than a declaration that it is
              finished. */}
          <Panel title="Outcome">
            <div className="popover-chips">
              {(["active", "completed", "lost"] as Outcome[]).map((o) => (
                <button
                  key={o}
                  type="button"
                  className={`chip${o === "lost" ? " chip-danger" : ""}`}
                  aria-pressed={deal.outcome === o}
                  onClick={() => setOutcomeDraft(o)}
                >
                  {o === "active" ? "Active" : o === "completed" ? "Completed" : "Lost"}
                </button>
              ))}
            </div>
            {deal.outcome !== "active" && deal.outcome_reason && (
              <p className="panel-muted">{deal.outcome_reason}</p>
            )}
            {deal.outcome === "active" && (
              <p className="panel-muted">
                On the board. Completing or losing it removes the card and files
                it under this client's history.
              </p>
            )}
          </Panel>

          {/* Last, and visually quiet. Delete is soft: this moves the deal to
              Trash, where it keeps its tasks and health history until someone
              deletes it permanently on purpose. Not the same as marking it
              lost — that is a result, this is a record that should not exist. */}
          <div className="drawer-danger">
            <button
              type="button"
              className="btn btn-sm danger subtle"
              onClick={() => setConfirmDelete(true)}
            >
              {/* "Delete deal", not "Delete client" — this removes ONE
                  engagement. Deleting the client is a different, much larger
                  action and lives on the company view. Since the split those
                  are genuinely different consequences, so the labels have to
                  say which one you are about to take. */}
              Delete deal
            </button>
            <span className="panel-muted">
              Moves this deal to Trash. The client and its other deals are untouched.
            </span>
          </div>

        </div>
      </aside>

      {outcomeDraft && (
        <div className="dialog-scrim" onClick={() => setOutcomeDraft(null)}>
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-label={`Mark ${deal.name} ${outcomeDraft}`}
            onClick={(e) => e.stopPropagation()}
          >
            <h3>
              {outcomeDraft === "active"
                ? `Reopen ${deal.name}?`
                : `Mark ${deal.name} ${outcomeDraft}?`}
            </h3>
            <p className="dialog-body">
              {outcomeDraft === "active"
                ? "It goes back on the board and starts being scored again."
                : "It leaves the board and is filed under this client's history. Nothing is deleted."}
            </p>
            {outcomeDraft !== "active" && (
              <label className="field">
                <span className="field-label">
                  Reason{outcomeDraft === "lost" ? "" : " (optional)"}
                </span>
                <textarea
                  value={outcomeReason}
                  autoFocus
                  placeholder={
                    outcomeDraft === "lost"
                      ? "Why did we lose it? This is the whole point of recording it."
                      : "Anything worth remembering about how it finished."
                  }
                  onChange={(e) => setOutcomeReason(e.target.value)}
                />
              </label>
            )}
            <div className="dialog-actions">
              <button className="btn subtle" onClick={() => setOutcomeDraft(null)}>Cancel</button>
              <button
                className={`btn${outcomeDraft === "lost" ? " danger" : " primary"}`}
                /* A lost deal must give a reason — the server enforces it too,
                   so this only saves the user a rejected round trip. */
                disabled={outcomeDraft === "lost" && !outcomeReason.trim()}
                onClick={() => {
                  onSetOutcome(outcomeDraft, outcomeReason.trim());
                  setOutcomeDraft(null);
                  setOutcomeReason("");
                }}
              >
                {outcomeDraft === "active" ? "Reopen" : "Confirm"}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmDelete && (
        <div className="dialog-scrim" onClick={() => setConfirmDelete(false)}>
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-label={`Delete ${deal.name}`}
            onClick={(e) => e.stopPropagation()}
          >
            <h3>Delete {deal.name}?</h3>
            <p className="dialog-body">
              It moves to Trash and leaves the board and every metric. Its tasks
              and health history stay intact, and you can restore it from there
              at any time. The client and its contacts are untouched.
            </p>
            <div className="dialog-actions">
              <button className="btn subtle" onClick={() => setConfirmDelete(false)}>Cancel</button>
              <button
                className="btn danger"
                onClick={() => { setConfirmDelete(false); onDeleteDeal(); }}
              >
                Move to Trash
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
