import { useDraggable } from "@dnd-kit/core";
import type { DealCard, TaskCard } from "../lib/types";

/**
 * The card carries exactly four things:
 *   1. name (+ key)   2. pilot/customer   3. workstream   4. health status
 *
 * Nothing else belongs here. Quoted value, margin, POC, next action, badges —
 * all of it lives in the drawer. An over-stuffed card stops being scannable,
 * which is the failure mode the research is most emphatic about. Resist adding
 * a fifth thing.
 *
 * Since the split the card is a DEAL. The company name rides along the title as
 * secondary text rather than as a fifth field: with two engagements for one
 * client, the deal names alone can be ambiguous, and the alternative — putting
 * the company on its own line — is exactly the fifth thing this comment warns
 * against.
 */
export function DealCardView({
  card,
  selected,
  onOpen,
}: {
  card: DealCard;
  selected: boolean;
  onOpen: (id: string) => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: card.id,
    data: { kind: "deal", column_id: card.column_id },
  });

  const classes = [
    "card",
    "card-deal",
    card.handoff ? "card-handoff" : "",
    card.stalled_handoff || card.column_stalled ? "card-stalled" : "",
    selected ? "card-selected" : "",
    isDragging ? "card-dragging" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <article
      ref={setNodeRef}
      className={classes}
      {...attributes}
      {...listeners}
      role="button"
      tabIndex={0}
      aria-label={`${card.name} for ${card.company_name}, ${card.mode_label}, ${card.workstream_label}, health ${card.health_band_label} ${card.health_score}`}
      onClick={() => onOpen(card.deal_id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(card.deal_id);
        }
      }}
    >
      {/* 1. health dot + name + key, with the client underneath */}
      <header className="card-head">
        <span className={`health-dot dot-${card.health_dot}`} aria-hidden="true" />
        <h3 className="card-title">{card.name}</h3>
        <span className="card-key">{card.key}</span>
      </header>
      {/* Only when it adds something. A deal named after its client — which is
          what every migrated deal starts as — would otherwise print the same
          words twice. */}
      {card.company_name !== card.name && (
        <p className="card-company">{card.company_name}</p>
      )}

      {/* 2. pilot / customer */}
      <div className="card-mode">
        <span className={`chip chip-${card.mode}`}>{card.mode_label.toUpperCase()}</span>
        {card.handoff && <span className="chip chip-handoff">HANDOFF</span>}
      </div>

      {/* 3. workstream — the other axis: what the team is doing right now */}
      <div className="card-workstream">
        <span className="ws-glyph" aria-hidden="true">
          {card.workstream_glyph}
        </span>
        <span className="ws-label">{card.workstream_label}</span>
      </div>

      {/* 4. health status — never colour alone, always band word + score */}
      <div className="card-health">
        <span className={`health-word text-${card.health_dot}`}>{card.health_band_label}</span>
        <span className="health-sep">·</span>
        <span className="health-score">{card.health_score}</span>
        {card.is_overridden && (
          <span className="health-override-mark" title="Manual override">
            ✎
          </span>
        )}
      </div>

      {(card.stalled_handoff || card.column_stalled) && (
        <p className="card-stalled-note">
          {card.stalled_handoff ? "Stalled handoff" : "Stalled in column"}
        </p>
      )}
    </article>
  );
}

/** Task cards no longer drive columns; they render inside the drawer. */
export function TaskRow({
  task,
  onToggle,
}: {
  task: TaskCard;
  onToggle: (task: TaskCard) => void;
}) {
  return (
    <div className={`task-row ${task.overdue ? "task-overdue" : ""}`}>
      <button
        className="task-check"
        aria-label={task.status === "done" ? "Reopen task" : "Complete task"}
        onClick={() => onToggle(task)}
      >
        {task.status === "done" ? "✓" : ""}
      </button>
      <div className="task-body">
        <p className={`task-title ${task.status === "done" ? "task-done" : ""}`}>{task.title}</p>
        <div className="task-meta">
          <span className={`chip chip-type`}>{task.type_label}</span>
          <span className={task.overdue ? "task-due-late" : "task-due"}>
            {task.overdue
              ? `Overdue by ${task.overdue_days}d`
              : task.days_until_due === 0
                ? "Due today"
                : `Due in ${task.days_until_due}d`}
          </span>
        </div>
        {task.provenance && <p className="task-provenance">⚠ {task.provenance}</p>}
      </div>
    </div>
  );
}
