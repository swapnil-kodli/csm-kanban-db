import { useDraggable } from "@dnd-kit/core";
import { AlertTriangle, Plus, Zap } from "lucide-react";
import type { AccountCard as AccountCardT, Badge, Card, TaskCard as TaskCardT } from "../lib/types";
import { contactLabel, dueLabel, inr, velocityGlyph } from "../lib/format";

const MAX_BADGES = 3;

function Badges({ badges }: { badges: Badge[] }) {
  if (!badges.length) return null;
  const shown = badges.slice(0, MAX_BADGES);
  const extra = badges.length - shown.length;
  return (
    <div className="badges">
      {shown.map((b) => (
        <span key={b.key} className={`badge badge-${b.variant}`}>
          {b.label}
        </span>
      ))}
      {extra > 0 && <span className="badge badge-more">+{extra}</span>}
    </div>
  );
}

interface DragProps {
  id: string;
  disabled?: boolean;
}

function useCardDrag({ id, disabled }: DragProps) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id, disabled });
  return { attributes, listeners, setNodeRef, isDragging };
}

interface AccountCardProps {
  card: AccountCardT;
  selected: boolean;
  onOpen: (accountId: string) => void;
  onSetNextAction: (accountId: string) => void;
}

export function AccountCardView({ card, selected, onOpen, onSetNextAction }: AccountCardProps) {
  const { attributes, listeners, setNodeRef, isDragging } = useCardDrag({ id: card.id });
  const vel = velocityGlyph(card.velocity);
  const isHandoff = card.lifecycle_stage === "ready_for_onboarding";

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      role="button"
      tabIndex={0}
      data-card-id={card.id}
      aria-label={`${card.name}, health ${card.health_score} ${card.health_band_label}, ${inr(card.arr)} ARR`}
      className={`card${isDragging ? " dragging" : ""}${selected ? " selected" : ""}${isHandoff ? " handoff" : ""}`}
      onClick={() => onOpen(card.account_id)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          onOpen(card.account_id);
        }
      }}
    >
      <div className="card-head">
        <span className="health-dot" style={{ background: `var(--${card.health_dot})` }} />
        <span className="card-title">{card.name}</span>
        <span className="card-key">{card.key}</span>
      </div>
      <div className="card-sub">
        {card.segment_label}
        {card.city ? ` · ${card.city}` : ""}
      </div>

      <div className="card-value-row">
        {card.arr ? (
          <span className="card-value">{inr(card.arr)}</span>
        ) : (
          <span className="card-value empty">No ARR set</span>
        )}
        <span className="health-readout">
          <span
            className="health-ring"
            style={{
              background: `var(--${card.health_dot})`,
              boxShadow: `0 0 0 3px color-mix(in srgb, var(--${card.health_dot}) 18%, transparent)`,
            }}
          />
          <span className="health-score">{card.health_score}</span>
          <span className={`velocity ${vel.cls}`} title={vel.label}>
            {vel.glyph}
            {card.velocity ? Math.abs(card.velocity) : ""}
          </span>
        </span>
      </div>

      <Badges badges={card.badges} />

      {card.next_action ? (
        <div className="next-step">
          <Zap size={13} strokeWidth={2.2} />
          <span>{card.next_action.title}</span>
        </div>
      ) : (
        <button
          type="button"
          className="next-step empty"
          onClick={(e) => {
            e.stopPropagation();
            onSetNextAction(card.account_id);
          }}
        >
          <Plus size={13} strokeWidth={2.2} />
          <span>Set next action</span>
        </button>
      )}

      <div className="card-foot">
        <span>{contactLabel(card.days_since_contact)}</span>
        <span className="stage-tag">
          <span className="stage-dot" style={{ background: `var(--${card.lifecycle_dot})` }} />
          {card.lifecycle_label}
        </span>
      </div>
    </div>
  );
}

interface TaskCardProps {
  card: TaskCardT;
  selected: boolean;
  onOpen: (accountId: string) => void;
}

export function TaskCardView({ card, selected, onOpen }: TaskCardProps) {
  const { attributes, listeners, setNodeRef, isDragging } = useCardDrag({ id: card.id });
  const done = card.status === "done";

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      role="button"
      tabIndex={0}
      data-card-id={card.id}
      aria-label={`${card.title}, ${card.account.name}, ${dueLabel(card.days_until_due, card.overdue, card.overdue_days)}`}
      className={`card${isDragging ? " dragging" : ""}${selected ? " selected" : ""}${card.overdue ? " overdue-task" : ""}${done ? " task-done" : ""}`}
      onClick={() => onOpen(card.account_id)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          onOpen(card.account_id);
        }
      }}
    >
      <div className="card-head">
        <span className="priority-dot" style={{ background: `var(--p-${card.priority})` }} />
        <span className="card-title">{card.title}</span>
      </div>
      <div className="card-sub">
        {card.account.name} · <span style={{ fontFamily: "ui-monospace, monospace" }}>{card.account.key}</span>
      </div>

      <div className="task-meta">
        <span className="type-chip">{card.type_label}</span>
        <span className={`due${card.overdue ? " is-overdue" : ""}`}>
          {done && card.completed_at
            ? "Completed"
            : dueLabel(card.days_until_due, card.overdue, card.overdue_days)}
        </span>
      </div>

      {card.provenance && (
        <div className="provenance">
          <AlertTriangle size={12} strokeWidth={2.2} />
          <span>{card.provenance}</span>
        </div>
      )}
    </div>
  );
}

interface CardViewProps {
  card: Card;
  selected: boolean;
  onOpen: (accountId: string) => void;
  onSetNextAction: (accountId: string) => void;
}

export function CardView({ card, selected, onOpen, onSetNextAction }: CardViewProps) {
  return card.kind === "task" ? (
    <TaskCardView card={card} selected={selected} onOpen={onOpen} />
  ) : (
    <AccountCardView card={card} selected={selected} onOpen={onOpen} onSetNextAction={onSetNextAction} />
  );
}
