import { useState } from "react";
import { isoPlusDays } from "../lib/format";
import type { TaskBucket } from "../lib/types";

const BUCKETS: { value: TaskBucket; label: string; days: number }[] = [
  { value: "today", label: "Today", days: 0 },
  { value: "this_week", label: "This Week", days: 3 },
  { value: "follow_up", label: "Follow-Up", days: 10 },
  { value: "waiting", label: "Waiting", days: 7 },
];

export function NewTaskDialog({
  accountName,
  onSubmit,
  onClose,
}: {
  accountName: string;
  onSubmit: (title: string, bucket: TaskBucket, due: string) => void;
  onClose: () => void;
}) {
  const [title, setTitle] = useState("");
  const [bucket, setBucket] = useState<TaskBucket>("this_week");

  return (
    <div className="dialog-scrim" onClick={onClose}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`New task for ${accountName}`}
        onClick={(e) => e.stopPropagation()}
      >
        <h3>New task · {accountName}</h3>
        <input
          autoFocus
          placeholder="What needs doing?"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && title.trim()) {
              const b = BUCKETS.find((x) => x.value === bucket)!;
              onSubmit(title.trim(), bucket, isoPlusDays(b.days));
            }
          }}
        />
        <div className="popover-chips">
          {BUCKETS.map((b) => (
            <button
              key={b.value}
              type="button"
              className="chip"
              aria-pressed={bucket === b.value}
              onClick={() => setBucket(b.value)}
            >
              {b.label}
            </button>
          ))}
        </div>
        <div className="dialog-actions">
          <button className="btn subtle" onClick={onClose}>Cancel</button>
          <button
            className="btn"
            disabled={!title.trim()}
            onClick={() => {
              const b = BUCKETS.find((x) => x.value === bucket)!;
              onSubmit(title.trim(), bucket, isoPlusDays(b.days));
            }}
          >
            Create
          </button>
        </div>
      </div>
    </div>
  );
}
