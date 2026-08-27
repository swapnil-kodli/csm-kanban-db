import { useState } from "react";
import { RotateCcw, Trash2, AlertTriangle } from "lucide-react";
import type { CompanyTrashRow, DealTrashRow } from "../lib/types";
import { formatINR } from "../lib/format";

/**
 * Trash — soft-deleted clients and deals, and the only place a hard delete is
 * reachable.
 *
 * Deals and companies are listed separately because deleting them means
 * different things: a deleted deal is one engagement withdrawn, a deleted
 * client takes all of its engagements with it. Merging them into one list would
 * make the second look like the first.
 *
 * With the demo seed off in production there is nothing to restore from, so a
 * hard delete is genuinely unrecoverable. Each row states what it owns before
 * offering to destroy it, and the confirmation asks for the key to be typed
 * back so the action cannot be reached by clicking through.
 *
 * Note this is not the same as a LOST deal. A lost deal is a real result and
 * lives in the client's history; a deleted one is a record that should not
 * exist.
 */
type AnyRow =
  | ({ kind: "deal" } & DealTrashRow)
  | ({ kind: "company" } & CompanyTrashRow);

export function Trash({
  deals,
  companies,
  onRestore,
  onHardDelete,
  onBack,
}: {
  deals: DealTrashRow[];
  companies: CompanyTrashRow[];
  onRestore: (row: AnyRow) => void;
  onHardDelete: (row: AnyRow, confirmKey: string) => void;
  onBack: () => void;
}) {
  const [confirming, setConfirming] = useState<AnyRow | null>(null);
  const rows: AnyRow[] = [
    ...companies.map((c) => ({ kind: "company" as const, ...c })),
    ...deals.map((d) => ({ kind: "deal" as const, ...d })),
  ];

  if (!rows.length) {
    return (
      <div className="board-wrap">
        <div className="empty-state">
          <h2>Trash is empty</h2>
          <p>
            Deleted clients and deals wait here until someone removes them
            permanently. Nothing is lost while something sits in Trash —
            restoring it brings back its contacts, tasks and full health history.
          </p>
          <button type="button" className="btn" onClick={onBack}>Back to the board</button>
        </div>
      </div>
    );
  }

  return (
    <div className="board-wrap">
      <div className="trash">
        <div className="trash-head">
          <h2>Trash</h2>
          <p>
            {describeCounts(companies.length, deals.length)} These are off the
            board and out of every metric, but nothing has been destroyed.
          </p>
        </div>

        {companies.length > 0 && (
          <>
            <h3 className="trash-group">Clients</h3>
            <ul className="trash-list">
              {companies.map((row) => {
                const r: AnyRow = { kind: "company", ...row };
                return (
                  <li key={row.id} className="trash-row">
                    <div className="trash-id">
                      <span className="trash-name">{row.name}</span>
                      <span className="trash-key">{row.key}</span>
                    </div>
                    <div className="trash-meta">
                      <span>{row.client_type_label}</span>
                      {row.city && (<><span>·</span><span>{row.city}</span></>)}
                      {row.quoted_total > 0 && (
                        <><span>·</span><span>{formatINR(row.quoted_total)} quoted</span></>
                      )}
                    </div>
                    <div className="trash-owns">
                      {describeCompanyOwns(row)}
                      {row.archived_at && <> · deleted {relative(row.archived_at)}</>}
                    </div>
                    <TrashActions row={r} onRestore={onRestore} onConfirm={setConfirming} />
                  </li>
                );
              })}
            </ul>
          </>
        )}

        {deals.length > 0 && (
          <>
            <h3 className="trash-group">Deals</h3>
            <ul className="trash-list">
              {deals.map((row) => {
                const r: AnyRow = { kind: "deal", ...row };
                return (
                  <li key={row.id} className="trash-row">
                    <div className="trash-id">
                      <span className="trash-name">{row.name}</span>
                      <span className="trash-key">{row.key}</span>
                    </div>
                    <div className="trash-meta">
                      <span>{row.company_name}</span>
                      <span>·</span>
                      <span>{row.mode_label}</span>
                      <span>·</span>
                      <span>{row.workstream_label}</span>
                      <span>·</span>
                      <span>{row.column_label}</span>
                      {row.quoted_total > 0 && (
                        <><span>·</span><span>{formatINR(row.quoted_total)} quoted</span></>
                      )}
                    </div>
                    <div className="trash-owns">
                      {describeDealOwns(row)}
                      {row.archived_at && <> · deleted {relative(row.archived_at)}</>}
                    </div>
                    <TrashActions row={r} onRestore={onRestore} onConfirm={setConfirming} />
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>

      {confirming && (
        <HardDeleteDialog
          row={confirming}
          onConfirm={(key) => { onHardDelete(confirming, key); setConfirming(null); }}
          onClose={() => setConfirming(null)}
        />
      )}
    </div>
  );
}

function TrashActions({
  row, onRestore, onConfirm,
}: {
  row: AnyRow;
  onRestore: (row: AnyRow) => void;
  onConfirm: (row: AnyRow) => void;
}) {
  return (
    <div className="trash-actions">
      <button type="button" className="btn" onClick={() => onRestore(row)}>
        <RotateCcw size={13} strokeWidth={2.2} aria-hidden="true" />
        Restore
      </button>
      <button type="button" className="btn danger" onClick={() => onConfirm(row)}>
        <Trash2 size={13} strokeWidth={2.2} aria-hidden="true" />
        Delete permanently
      </button>
    </div>
  );
}

function HardDeleteDialog({
  row,
  onConfirm,
  onClose,
}: {
  row: AnyRow;
  onConfirm: (confirmKey: string) => void;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  // Case-insensitive on purpose: keys are stored upper-case, so demanding exact
  // case would be friction without adding any safety.
  const matches = typed.trim().toUpperCase() === row.key.toUpperCase();

  return (
    <div className="dialog-scrim" onClick={onClose}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`Permanently delete ${row.name}`}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="danger-title">
          <AlertTriangle size={15} strokeWidth={2.2} aria-hidden="true" />
          Delete {row.name} permanently
        </h3>

        <p className="dialog-body">
          This destroys{" "}
          {row.kind === "company" ? describeCompanyOwns(row) : describeDealOwns(row)}.
          There is no backup to restore from and no undo.
        </p>

        <label className="field">
          <span className="field-label">Type <strong>{row.key}</strong> to confirm</span>
          <input
            value={typed}
            autoFocus
            placeholder={row.key}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && matches && onConfirm(typed.trim())}
          />
        </label>

        <div className="dialog-actions">
          <button className="btn subtle" onClick={onClose}>Keep it</button>
          <button
            className="btn danger"
            disabled={!matches}
            onClick={() => onConfirm(typed.trim())}
          >
            Delete permanently
          </button>
        </div>
      </div>
    </div>
  );
}

function join(parts: string[], fallback: string): string {
  if (!parts.length) return fallback;
  const last = parts.pop() as string;
  return parts.length ? `${parts.join(", ")} and ${last}` : last;
}

function describeDealOwns(row: DealTrashRow): string {
  const parts: string[] = [];
  const { tasks, snapshots, risks } = row.owns;
  if (tasks) parts.push(`${tasks} task${tasks === 1 ? "" : "s"}`);
  if (snapshots) parts.push(`${snapshots} health snapshot${snapshots === 1 ? "" : "s"}`);
  if (risks) parts.push(`${risks} risk${risks === 1 ? "" : "s"}`);
  return join(parts, "the deal record, with no attached history");
}

function describeCompanyOwns(row: CompanyTrashRow): string {
  const parts: string[] = [];
  const { deals, contacts, tasks } = row.owns;
  if (deals) parts.push(`${deals} deal${deals === 1 ? "" : "s"}`);
  if (contacts) parts.push(`${contacts} contact${contacts === 1 ? "" : "s"}`);
  if (tasks) parts.push(`${tasks} task${tasks === 1 ? "" : "s"}`);
  return join(parts, "the client record, with nothing attached");
}

function describeCounts(companies: number, deals: number): string {
  const parts: string[] = [];
  if (companies) parts.push(`${companies} deleted ${companies === 1 ? "client" : "clients"}`);
  if (deals) parts.push(`${deals} deleted ${deals === 1 ? "deal" : "deals"}`);
  return `${join(parts, "Nothing deleted")}.`;
}

/** Coarse on purpose — Trash never needs minute precision. */
function relative(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "recently";
  const days = Math.floor((Date.now() - then) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  const months = Math.floor(days / 30);
  return `${months} month${months === 1 ? "" : "s"} ago`;
}
