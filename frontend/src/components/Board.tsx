import { useState } from "react";
import { DndContext, DragOverlay, KeyboardSensor, PointerSensor, useDroppable, useSensor, useSensors } from "@dnd-kit/core";
import type { DragEndEvent, DragStartEvent } from "@dnd-kit/core";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { BoardResponse, Card, Column, Swimlane } from "../lib/types";
import { inr } from "../lib/format";
import { CardView } from "./Cards";

const DONE_COLLAPSE_DAYS = 7;

function daysSince(iso: string | null): number {
  if (!iso) return 0;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
}

interface DropZoneProps {
  column: Column;
  laneKey: string;
  children: React.ReactNode;
}

function DropZone({ column, laneKey, children }: DropZoneProps) {
  const { setNodeRef, isOver } = useDroppable({
    id: `${column.key}::${laneKey}`,
    data: { columnKey: column.key, dropAction: column.drop_action },
    disabled: !column.droppable,
  });
  return (
    <div ref={setNodeRef} className={`col-body${isOver ? " drop-target" : ""}`}>
      {children}
    </div>
  );
}

interface ColumnViewProps {
  column: Column;
  cards: Card[];
  laneKey: string;
  selectedId: string | null;
  onOpen: (accountId: string) => void;
  onSetNextAction: (accountId: string) => void;
}

function ColumnView({ column, cards, laneKey, selectedId, onOpen, onSetNextAction }: ColumnViewProps) {
  const [showOlder, setShowOlder] = useState(false);

  let visible = cards;
  let hiddenCount = 0;
  if (column.collapse_older_than_days !== null && !showOlder) {
    const fresh = cards.filter(
      (c) => c.kind !== "task" || daysSince(c.completed_at) <= DONE_COLLAPSE_DAYS
    );
    hiddenCount = cards.length - fresh.length;
    visible = fresh;
  }

  // Subgroup cards arrive as separate JSON objects, so match on id, not identity.
  const visibleIds = new Set(cards.map((c) => c.id));
  const subgroups = column.subgroups
    ?.map((g) => ({ ...g, cards: g.cards.filter((c) => visibleIds.has(c.id)) }))
    .filter((g) => g.cards.length > 0);

  return (
    <section className="column" aria-label={column.title}>
      <header className="col-head">
        <span className="col-dot" style={{ background: `var(--${column.dot})` }} />
        <span className="col-title">{column.title}</span>
        <span className="col-count">{cards.length}</span>
        {cards.length > 0 && <span className="col-total">{inr(cards.reduce((s, c) => s + (c.kind === "account" ? c.arr : c.account.arr), 0))}</span>}
      </header>

      <DropZone column={column} laneKey={laneKey}>
        {subgroups && subgroups.length > 0
          ? subgroups.map((group) => {
              const groupCards = group.cards;
              return (
                <div key={group.key}>
                  <div className="subgroup-head">
                    {group.title} · {groupCards.length}
                  </div>
                  {groupCards.map((card) => (
                    <div key={card.id} style={{ marginTop: 11 }}>
                      <CardView card={card} selected={card.id === selectedId} onOpen={onOpen} onSetNextAction={onSetNextAction} />
                    </div>
                  ))}
                </div>
              );
            })
          : visible.map((card) => (
              <CardView key={card.id} card={card} selected={card.id === selectedId} onOpen={onOpen} onSetNextAction={onSetNextAction} />
            ))}

        {hiddenCount > 0 && (
          <button type="button" className="show-older" onClick={() => setShowOlder(true)}>
            Show {hiddenCount} older
          </button>
        )}

        {cards.length === 0 && <div className="col-empty">Nothing here</div>}
      </DropZone>
    </section>
  );
}

interface BoardProps {
  board: BoardResponse;
  selectedId: string | null;
  onOpen: (accountId: string) => void;
  onSetNextAction: (accountId: string) => void;
  onDrop: (cardId: string, columnKey: string, dropAction: Column["drop_action"]) => void;
}

export function Board({ board, selectedId, onOpen, onSetNextAction, onDrop }: BoardProps) {
  const [dragging, setDragging] = useState<Card | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    // Keyboard path for drag-drop: Space to grab, arrows to move, Space to drop.
    useSensor(KeyboardSensor)
  );

  const allCards = board.columns.flatMap((c) => c.cards);

  function handleStart(event: DragStartEvent) {
    setDragging(allCards.find((c) => c.id === event.active.id) ?? null);
  }

  function handleEnd(event: DragEndEvent) {
    setDragging(null);
    const over = event.over;
    if (!over) return;
    const data = over.data.current as { columnKey: string; dropAction: Column["drop_action"] } | undefined;
    if (!data) return;
    onDrop(String(event.active.id), data.columnKey, data.dropAction);
  }

  const lanes: Swimlane[] = board.group_by === "none" ? [] : board.swimlanes;

  return (
    <DndContext sensors={sensors} onDragStart={handleStart} onDragEnd={handleEnd} onDragCancel={() => setDragging(null)}>
      <div className="board-wrap">
        {lanes.length === 0 ? (
          <div className="board">
            {board.columns.map((column) => (
              <ColumnView
                key={column.key}
                column={column}
                cards={column.cards}
                laneKey="all"
                selectedId={selectedId}
                onOpen={onOpen}
                onSetNextAction={onSetNextAction}
              />
            ))}
          </div>
        ) : (
          <SwimlaneBoard
            board={board}
            lanes={lanes}
            selectedId={selectedId}
            onOpen={onOpen}
            onSetNextAction={onSetNextAction}
          />
        )}
      </div>

      <DragOverlay dropAnimation={null}>
        {dragging ? (
          <div style={{ width: 320, cursor: "grabbing" }}>
            <CardView card={dragging} selected={false} onOpen={() => {}} onSetNextAction={() => {}} />
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}

interface SwimlaneBoardProps {
  board: BoardResponse;
  lanes: Swimlane[];
  selectedId: string | null;
  onOpen: (accountId: string) => void;
  onSetNextAction: (accountId: string) => void;
}

const COLLAPSE_KEY = "signal-cs:collapsed-lanes";

function readCollapsed(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(COLLAPSE_KEY) || "{}");
  } catch {
    return {};
  }
}

function SwimlaneBoard({ board, lanes, selectedId, onOpen, onSetNextAction }: SwimlaneBoardProps) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(readCollapsed);

  function toggle(key: string) {
    const next = { ...collapsed, [key]: !collapsed[key] };
    setCollapsed(next);
    try {
      localStorage.setItem(COLLAPSE_KEY, JSON.stringify(next));
    } catch { /* private mode */ }
  }

  return (
    <div className="swimlanes">
      {lanes.map((lane) => {
        const isCollapsed = !!collapsed[lane.key];
        return (
          <div className="swimlane" key={lane.key}>
            <button type="button" className="swimlane-head" onClick={() => toggle(lane.key)} aria-expanded={!isCollapsed}>
              {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
              <span className="swimlane-label">{lane.title}</span>
              <span className="swimlane-meta">
                {lane.count} items · {inr(lane.total_arr)}
              </span>
            </button>
            {!isCollapsed && (
              <div className="board">
                {board.columns.map((column) => (
                  <ColumnView
                    key={column.key}
                    column={column}
                    cards={column.cards.filter((c) => c.lane === lane.key)}
                    laneKey={lane.key}
                    selectedId={selectedId}
                    onOpen={onOpen}
                    onSetNextAction={onSetNextAction}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function BoardSkeleton() {
  return (
    <div className="board-wrap">
      <div className="board">
        {[0, 1, 2, 3].map((i) => (
          <div className="skeleton-col" key={i}>
            <div className="skeleton" style={{ height: 18, width: 120 }} />
            {[0, 1, 2].map((j) => (
              <div className="skeleton skeleton-card" key={j} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
