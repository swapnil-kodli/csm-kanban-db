import { DndContext, DragOverlay, PointerSensor, KeyboardSensor, useSensor, useSensors } from "@dnd-kit/core";
import type { DragEndEvent, DragStartEvent } from "@dnd-kit/core";
import { useDroppable } from "@dnd-kit/core";
import { useMemo, useState } from "react";
import { AccountCardView } from "./Cards";
import { formatINR } from "../lib/format";
import type { AccountCard, BoardResponse, GroupBy } from "../lib/types";

function Column({
  colKey,
  title,
  dot,
  count,
  totalQuoted,
  handoffInbox,
  cards,
  selectedId,
  onOpen,
}: {
  colKey: string;
  title: string;
  dot: string;
  count: number;
  totalQuoted: number;
  handoffInbox: boolean;
  cards: AccountCard[];
  selectedId: string | null;
  onOpen: (id: string) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: colKey });
  return (
    <section className="column" aria-label={title}>
      <header className="col-head">
        <span className={`col-dot dot-${dot}`} aria-hidden="true" />
        <h2 className="col-title">{title}</h2>
        <span className="col-count">{count}</span>
        <span className="col-total">{formatINR(totalQuoted)}</span>
      </header>
      <div
        ref={setNodeRef}
        className={`col-body ${isOver ? "drop-target" : ""} ${handoffInbox ? "col-handoff" : ""}`}
      >
        {cards.map((card) => (
          <AccountCardView
            key={card.id}
            card={card}
            selected={card.id === selectedId}
            onOpen={onOpen}
          />
        ))}
        {cards.length === 0 && <p className="col-empty">Nothing here</p>}
      </div>
    </section>
  );
}

export function Board({
  board,
  groupBy,
  selectedId,
  collapsedLanes,
  onToggleLane,
  onOpen,
  onMove,
}: {
  board: BoardResponse;
  groupBy: GroupBy;
  selectedId: string | null;
  collapsedLanes: Set<string>;
  onToggleLane: (key: string) => void;
  onOpen: (id: string) => void;
  onMove: (cardId: string, toColumn: string) => void;
}) {
  const [dragging, setDragging] = useState<AccountCard | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    // Keyboard drag path: Space to grab, arrows to move, Space to drop.
    useSensor(KeyboardSensor)
  );

  const allCards = useMemo(
    () => board.columns.flatMap((c) => c.cards),
    [board]
  );

  function handleStart(e: DragStartEvent) {
    setDragging(allCards.find((c) => c.id === e.active.id) ?? null);
  }

  function handleEnd(e: DragEndEvent) {
    setDragging(null);
    const target = e.over?.id;
    if (!target) return;
    const card = allCards.find((c) => c.id === e.active.id);
    // Dragging changes the column and nothing else. workstream is a separate
    // axis and is edited in the drawer only.
    if (card && card.column !== target) onMove(card.id, String(target));
  }

  const lanes = groupBy === "none" ? [{ key: "all", title: "", count: 0, total_quoted: 0 }] : board.swimlanes;

  return (
    <DndContext sensors={sensors} onDragStart={handleStart} onDragEnd={handleEnd}>
      <div className="board-wrap">
        {lanes.map((lane) => {
          const collapsed = collapsedLanes.has(lane.key);
          return (
            <div className="lane" key={lane.key}>
              {groupBy !== "none" && (
                <button
                  className="swimlane-head"
                  onClick={() => onToggleLane(lane.key)}
                  aria-expanded={!collapsed}
                >
                  <span className="lane-chevron">{collapsed ? "▸" : "▾"}</span>
                  <span className="lane-label">{lane.title}</span>
                  <span className="lane-count">{lane.count} items</span>
                  <span className="lane-total">{formatINR(lane.total_quoted)}</span>
                </button>
              )}
              {!collapsed && (
                <div className="board">
                  {board.columns.map((col) => {
                    const cards =
                      groupBy === "none"
                        ? col.cards
                        : col.cards.filter((c) => c.lane === lane.key);
                    return (
                      <Column
                        key={col.key + lane.key}
                        colKey={col.key}
                        title={col.title}
                        dot={col.dot}
                        count={groupBy === "none" ? col.count : cards.length}
                        totalQuoted={
                          groupBy === "none"
                            ? col.total_quoted
                            : cards.reduce((s, c) => s + c.quoted_total, 0)
                        }
                        handoffInbox={col.handoff_inbox}
                        cards={cards}
                        selectedId={selectedId}
                        onOpen={onOpen}
                      />
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <DragOverlay dropAnimation={null}>
        {dragging && (
          <div className="card card-account card-drag-ghost">
            <header className="card-head">
              <span className={`health-dot dot-${dragging.health_dot}`} />
              <h3 className="card-title">{dragging.name}</h3>
            </header>
          </div>
        )}
      </DragOverlay>
    </DndContext>
  );
}

/** Static block, never a shimmer — the board must not animate while loading. */
export function BoardSkeleton() {
  return (
    <div className="board-wrap">
      <div className="board">
        {[0, 1, 2, 3, 4].map((i) => (
          <section className="column" key={i}>
            <header className="col-head">
              <span className="skeleton skeleton-title" />
            </header>
            <div className="col-body">
              {[0, 1].map((j) => (
                <div className="skeleton skeleton-card" key={j} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
