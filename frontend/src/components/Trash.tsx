import { useState } from "react";
import { RotateCcw, Trash2, AlertTriangle } from "lucide-react";
import type { TrashRow } from "../lib/types";
import { formatINR } from "../lib/format";

/**
 * Trash — soft-deleted clients, and the only place a hard delete is reachable.
 *
 * A client owns contacts, tasks, health snapshots, costing and PNL history. The
 * demo seed is off in production, so there is nothing to restore from: a hard
 * delete is genuinely unrecoverable. Each row therefore states what it owns
 * before offering to destroy it, and the confirmation asks for the client's key
 * to be typed back so the action cannot be reached by clicking through.
 */
export function Trash({
  rows,
  onRestore,
  onHardDelete,
  onBack,
}: {
  rows: TrashRow[];
  onRestore: (row: TrashRow) => void;
  onHardDelete: (row: TrashRow, confirmKey: string) => void;
  onBack: () => void;
}) {
  const [confirming, setConfirming] = useState<TrashRow | null>(null);

  if (!rows.length) {
    return (
      <div className="board-wrap">
        <div className="empty-state">
          <h2>Trash is empty</h2>
          <p>
            Deleted clients wait here until someone removes them permanently.
            Nothing is lost while a client sits in Trash — restoring one brings
            back its contacts, tasks and full health history.
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
            {rows.length} deleted {rows.length === 1 ? "client" : "clients"}. These are off
            the board and out of every metric, but nothing has been destroyed.
          </p>
        </div>

        <ul className="trash-list">
          {rows.map((row) => (
            <li key={row.id} className="trash-row">
              <div className="trash-id">
                <span className="trash-name">{row.name}</span>
                <span className="trash-key">{row.key}</span>
              </div>
              <div className="trash-meta">
                <span>{row.mode_label}</span>
                <span>·</span>
                <span>{row.workstream_label}</span>
                <span>·</span>
                <span>{row.column_label}</span>
                {row.quoted_total > 0 && (
                  <>
                    <span>·</span>
                    <span>{formatINR(row.quoted_total)} quoted</span>
                  </>
                )}
              </div>
              <div className="trash-owns">
                {describeOwns(row)}
                {row.archived_at && <> · deleted {relative(row.archived_at)}</>}
              </div>
              <div className="trash-actions">
                <button type="button" className="btn" onClick={() => onRestore(row)}>
                  <RotateCcw size={13} strokeWidth={2.2} aria-hidden="true" />
                  Restore
                </button>
                <button
                  type="button"
                  className="btn danger"
                  onClick={() => setConfirming(row)}
                >
                  <Trash2 size={13} strokeWidth={2.2} aria-hidden="true" />
                  Delete permanently
                </button>
              </div>
            </li>
          ))}
        </ul>
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

function HardDeleteDialog({
  row,
  onConfirm,
  onClose,
}: {
  row: TrashRow;
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
          This destroys {describeOwns(row)}. There is no backup to restore from and
          no undo.
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

function describeOwns(row: TrashRow): string {
  const parts: string[] = [];
  const { contacts, tasks, snapshots, risks } = row.owns;
  if (contacts) parts.push(`${contacts} contact${contacts === 1 ? "" : "s"}`);
  if (tasks) parts.push(`${tasks} task${tasks === 1 ? "" : "s"}`);
  if (snapshots) parts.push(`${snapshots} health snapshot${snapshots === 1 ? "" : "s"}`);
  if (risks) parts.push(`${risks} risk${risks === 1 ? "" : "s"}`);
  if (!parts.length) return "the client record, with no attached history";
  const last = parts.pop() as string;
  return parts.length ? `${parts.join(", ")} and ${last}` : last;
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
