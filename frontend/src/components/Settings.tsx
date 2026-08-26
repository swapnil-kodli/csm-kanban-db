import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiDelete, apiGet, apiPatch, apiPost } from "../lib/api";
import type { ColumnConfig, ColumnImpact } from "../lib/types";

/**
 * A narrow configuration surface on purpose.
 *
 * Every destructive action states its blast radius *before* it happens, not
 * after — "this will move 4 cards" is the information
 * someone needs to decide, and showing it afterwards is a receipt, not a
 * choice. Recolouring is restricted to the token palette rather than a free
 * picker, so the board keeps one saturated channel for health.
 */
export function Settings({ onChanged }: { onChanged: () => void }) {
  const [columns, setColumns] = useState<ColumnConfig[]>([]);
  const [palette, setPalette] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<
    { column: ColumnConfig; impact: ColumnImpact; target: string } | null
  >(null);
  const [resetPhrase, setResetPhrase] = useState("");
  const [resetting, setResetting] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState("");

  async function load() {
    const d = await apiGet<{ columns: ColumnConfig[]; palette: string[] }>("/columns");
    setColumns(d.columns);
    setPalette(d.palette);
  }
  useEffect(() => {
    load().catch(() => setError("Could not load column configuration"));
  }, []);

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setError(null);
    setNote(null);
    try {
      await fn();
      await load();
      onChanged();
      if (ok) setNote(ok);
    } catch (e) {
      // 409s carry the constraint they are protecting — surface it verbatim.
      setError(e instanceof Error ? e.message : "That change was refused");
    }
  }

  async function askDelete(column: ColumnConfig) {
    const impact = await apiGet<ColumnImpact>(`/columns/${column.id}/impact`);
    const fallback = columns.find((c) => c.id !== column.id && !c.is_archived);
    setConfirmDelete({ column, impact, target: fallback?.id ?? "" });
  }

  function onDrop(targetId: string) {
    if (!dragId || dragId === targetId) return;
    const ids = columns.map((c) => c.id);
    const from = ids.indexOf(dragId);
    const to = ids.indexOf(targetId);
    ids.splice(to, 0, ...ids.splice(from, 1));
    setDragId(null);
    run(() => apiPost("/columns/reorder", { ordered_ids: ids }));
  }

  return (
    <div className="settings">
      <header className="settings-head">
        <h1>Settings</h1>
        <Link className="btn subtle" to="/">
          Back to board
        </Link>
      </header>

      <nav className="settings-tabs" role="tablist">
        <button className="tab" role="tab" aria-selected="true">
          Board Columns
        </button>
        <span className="settings-soon">Card Overview and Card Detail arrive in v3b</span>
      </nav>

      {error && <div className="panel-error">{error}</div>}
      {note && <div className="settings-note">{note}</div>}

      <ol className="col-config">
        {columns.map((c) => (
          <li
            key={c.id}
            className={`col-config-row ${c.is_archived ? "archived" : ""} ${dragId === c.id ? "dragging" : ""}`}
            draggable
            onDragStart={() => setDragId(c.id)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => onDrop(c.id)}
          >
            <span className="drag-handle" aria-hidden="true">⠿</span>
            <span className="col-swatch" style={{ background: c.color }} />

            <input
              className="col-label-input"
              // Uncontrolled so typing is not round-tripped per keystroke, but
              // keyed on the label so a server-side change — a reset, or an
              // edit from elsewhere — remounts it instead of showing stale text.
              key={`${c.id}:${c.label}`}
              defaultValue={c.label}
              aria-label={`Label for ${c.label}`}
              onBlur={(e) =>
                e.target.value.trim() !== c.label &&
                run(() => apiPatch(`/columns/${c.id}`, { label: e.target.value.trim() }))
              }
            />
            {/* The key never changes, so filters and URLs survive a rename. */}
            <code className="col-key">{c.key}</code>

            <div className="col-palette">
              {palette.map((hex) => (
                <button
                  key={hex}
                  className={`swatch ${c.color === hex ? "on" : ""}`}
                  style={{ background: hex }}
                  aria-label={`Set colour ${hex}`}
                  onClick={() => run(() => apiPatch(`/columns/${c.id}`, { color: hex }))}
                />
              ))}
            </div>

            <label className="col-stall">
              <input
                type="number"
                min={1}
                max={365}
                value={c.stalled_after_days ?? ""}
                placeholder="off"
                aria-label={`Stall after days for ${c.label}`}
                onChange={(e) => {
                  const v = e.target.value;
                  run(() =>
                    apiPatch(`/columns/${c.id}`,
                      v === ""
                        ? { clear_stalled_after_days: true }
                        : { stalled_after_days: Number(v) }
                    )
                  );
                }}
              />
              <span>d to stall</span>
            </label>

            <label className="col-entry">
              <input
                type="radio"
                name="entry"
                checked={c.is_default_entry}
                onChange={() => run(() => apiPatch(`/columns/${c.id}`, { is_default_entry: true }))}
              />
              Entry
            </label>

            <span className="col-count">{c.card_count}</span>

            <button
              className="btn btn-sm subtle"
              onClick={() =>
                run(() => apiPatch(`/columns/${c.id}`, { is_archived: !c.is_archived }))
              }
            >
              {c.is_archived ? "Restore" : "Archive"}
            </button>
            <button className="btn btn-sm subtle" onClick={() => askDelete(c)}>
              Delete
            </button>
          </li>
        ))}
      </ol>

      <div className="col-add">
        <input
          placeholder="New column label"
          value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && newLabel.trim()) {
              run(() => apiPost("/columns", { label: newLabel.trim() }));
              setNewLabel("");
            }
          }}
        />
        <button
          className="btn"
          disabled={!newLabel.trim()}
          onClick={() => {
            run(() => apiPost("/columns", { label: newLabel.trim() }));
            setNewLabel("");
          }}
        >
          Add column
        </button>
      </div>

      <section className="settings-danger">
        <h2>Reset to defaults</h2>
        <p>
          Restores the five shipped columns exactly. Cards keep their current
          column; only the configuration is restored. Type <code>reset</code> to
          confirm.
        </p>
        <div className="composer">
          <input value={resetPhrase} onChange={(e) => setResetPhrase(e.target.value)} />
          <button
            className="btn"
            disabled={resetPhrase !== "reset" || resetting}
            onClick={async () => {
              setResetting(true);
              await run(() => apiPost("/columns/reset", {}), "Defaults restored");
              setResetting(false);
              setResetPhrase("");
            }}
          >
            Reset
          </button>
        </div>
      </section>

      {confirmDelete && (
        <div className="dialog-scrim" onClick={() => setConfirmDelete(null)}>
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <h3>Delete “{confirmDelete.column.label}”?</h3>
            {/* Blast radius up front, so this is a decision and not a receipt. */}
            <p className="dialog-impact">
              {confirmDelete.impact.card_count > 0 ? (
                <>
                  This will move <strong>{confirmDelete.impact.card_count}</strong> card
                  {confirmDelete.impact.card_count === 1 ? "" : "s"} to{" "}
                  <strong>
                    {columns.find((c) => c.id === confirmDelete.target)?.label ?? "another column"}
                  </strong>
                  .
                </>
              ) : (
                <>This column is empty — nothing will be moved.</>
              )}
            </p>
            {confirmDelete.impact.card_count > 0 && (
              <label className="field">
                <span className="field-label">Move cards to</span>
                <select
                  value={confirmDelete.target}
                  onChange={(e) =>
                    setConfirmDelete({ ...confirmDelete, target: e.target.value })
                  }
                >
                  {columns
                    .filter((c) => c.id !== confirmDelete.column.id && !c.is_archived)
                    .map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                </select>
              </label>
            )}
            <div className="dialog-actions">
              <button className="btn subtle" onClick={() => setConfirmDelete(null)}>
                Cancel
              </button>
              <button
                className="btn"
                onClick={() => {
                  const { column, target } = confirmDelete;
                  setConfirmDelete(null);
                  run(() => apiDelete(`/columns/${column.id}`, { reassign_to: target || null }));
                }}
              >
                Delete column
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
