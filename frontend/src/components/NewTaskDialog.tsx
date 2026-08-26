import { useState } from "react";
import { isoPlusDays } from "../lib/format";
import type { TaskBucket, TaskPriority, TaskType } from "../lib/types";

const BUCKETS: { value: TaskBucket; label: string; days: number }[] = [
  { value: "today", label: "Today", days: 0 },
  { value: "this_week", label: "This Week", days: 3 },
  { value: "follow_up", label: "Follow-Up", days: 10 },
  { value: "waiting", label: "Waiting", days: 7 },
];

const TYPES: TaskType[] = [
  "onboarding", "risk", "renewal", "expansion", "checkin", "escalation", "admin",
];
const PRIORITIES: TaskPriority[] = ["critical", "high", "normal"];

/**
 * Manual task creation. Tasks made here carry no `provenance` — that string is
 * reserved for alert-generated tasks, and is how the board distinguishes work it
 * raised from work a person chose.
 */
export function NewTaskDialog({
  accounts,
  initialAccountId,
  onSubmit,
  onClose,
}: {
  accounts: { id: string; name: string; key: string }[];
  initialAccountId: string;
  onSubmit: (accountId: string, title: string, bucket: TaskBucket, due: string,
             type: TaskType, priority: TaskPriority) => void;
  onClose: () => void;
}) {
  // Defaults to nothing when opened from the board. Silently attaching a task
  // to whichever account sorted first is worse than asking.
  const [accountId, setAccountId] = useState(initialAccountId);
  const [title, setTitle] = useState("");
  const [bucket, setBucket] = useState<TaskBucket>("this_week");
  const [type, setType] = useState<TaskType>("checkin");
  const [priority, setPriority] = useState<TaskPriority>("normal");
  const [due, setDue] = useState(isoPlusDays(3));

  const ready = accountId !== "" && title.trim() !== "";

  function submit() {
    if (!ready) return;
    onSubmit(accountId, title.trim(), bucket, due, type, priority);
  }

  return (
    <div className="dialog-scrim" onClick={onClose}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label="New task"
        onClick={(e) => e.stopPropagation()}
      >
        <h3>New task</h3>

        <label className="field">
          <span className="field-label">Account</span>
          <select value={accountId} onChange={(e) => setAccountId(e.target.value)} autoFocus>
            <option value="">Choose an account…</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} · {a.key}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span className="field-label">Title</span>
          <input
            placeholder="What needs doing?"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
        </label>

        <label className="field">
          <span className="field-label">Type</span>
          <select value={type} onChange={(e) => setType(e.target.value as TaskType)}>
            {TYPES.map((t) => (
              <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
            ))}
          </select>
        </label>

        <label className="field">
          <span className="field-label">Priority</span>
          <select value={priority} onChange={(e) => setPriority(e.target.value as TaskPriority)}>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>

        <label className="field">
          <span className="field-label">Due</span>
          <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </label>

        <div className="popover-chips">
          {BUCKETS.map((b) => (
            <button
              key={b.value}
              type="button"
              className="chip"
              aria-pressed={bucket === b.value}
              onClick={() => { setBucket(b.value); setDue(isoPlusDays(b.days)); }}
            >
              {b.label}
            </button>
          ))}
        </div>

        <div className="dialog-actions">
          <button className="btn subtle" onClick={onClose}>Cancel</button>
          <button className="btn" disabled={!ready} onClick={submit}>Create</button>
        </div>
      </div>
    </div>
  );
}
