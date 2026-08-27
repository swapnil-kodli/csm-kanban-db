import { useState } from "react";
import { ArrowLeft, Plus, Trash2, AlertTriangle } from "lucide-react";
import type { CompanyDealRow, CompanyDetail, Outcome } from "../lib/types";
import { formatINR, inrExact } from "../lib/format";

const OUTCOME_ORDER: Outcome[] = ["active", "completed", "lost"];
const OUTCOME_TITLES: Record<Outcome, string> = {
  active: "Active",
  completed: "Completed",
  lost: "Lost",
};

/**
 * The client, whole.
 *
 * This is the view the Company/Deal split exists to make possible: across
 * everything done with one client, what is running, what finished, what was
 * lost, what it was worth, and who we talk to. The board answers "what needs me
 * today"; this answers "what is this relationship".
 */
export function CompanyView({
  detail,
  onBack,
  onOpenDeal,
  onNewDeal,
  onAddContact,
  onDeleteContact,
  onArchive,
}: {
  detail: CompanyDetail;
  onBack: () => void;
  onOpenDeal: (dealId: string) => void;
  onNewDeal: (companyId: string) => void;
  onAddContact: (companyId: string) => void;
  onDeleteContact: (contactId: string) => void;
  onArchive: () => void;
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const { company, deals, contacts } = detail;
  const { health } = company;

  return (
    <div className="board-wrap">
      <div className="company">
        <button type="button" className="btn subtle company-back" onClick={onBack}>
          <ArrowLeft size={13} strokeWidth={2.2} aria-hidden="true" /> Board
        </button>

        <header className="company-head">
          <div className="company-title">
            <h2>{company.name}</h2>
            <span className="card-key">{company.key}</span>
            <span className="chip chip-grey">{company.client_type_label}</span>
            {company.city && <span className="chip chip-grey">{company.city}</span>}
          </div>

          {/* Worst active band with its count, never a mean. A client with one
              critical engagement and two healthy ones is a client at risk, and
              an average would report "watch". */}
          <div className="company-health">
            {health.band ? (
              <>
                <span className={`health-dot dot-${health.dot}`} aria-hidden="true" />
                <span className={`health-word text-${health.dot}`}>{health.band_label}</span>
                <span className="health-sep">—</span>
                <span className="company-health-count">
                  {health.worst_count} of {health.active_count}{" "}
                  {health.active_count === 1 ? "deal" : "deals"}
                </span>
              </>
            ) : (
              <span className="panel-muted">
                No active engagements — no health to report.
              </span>
            )}
          </div>
        </header>

        <div className="company-stats">
          <Stat label="Deals" value={String(company.total_deals)}
                sub={`${company.counts.active} active · ${company.counts.completed} completed · ${company.counts.lost} lost`} />
          <Stat label="Quoted" value={formatINR(company.quoted_total)}
                sub="across every deal" />
          <Stat label="Recognised" value={formatINR(company.revenue_recognised)}
                sub="actually billed" />
          <Stat
            label="Gross margin"
            value={inrExact(company.gross_margin)}
            /* Unknown, not zero. Nothing billed anywhere is not a 100% margin
               and not a 0% one — it is an absent input. */
            sub={company.margin_pct === null ? "nothing billed yet" : `${company.margin_pct}%`}
          />
          <Stat
            label="Last contact"
            value={company.last_contact_at ? relative(company.last_contact_at) : "—"}
            sub="most recent across active deals"
          />
        </div>

        <section className="company-section">
          <header className="company-section-head">
            <h3>Deals</h3>
            <button type="button" className="btn btn-sm" onClick={() => onNewDeal(company.id)}>
              <Plus size={13} strokeWidth={2.4} aria-hidden="true" /> New deal
            </button>
          </header>

          {company.total_deals === 0 && (
            <p className="panel-muted">
              No deals yet. This client exists, but nothing is being delivered
              for them — add a deal and it appears on the board.
            </p>
          )}

          {/* Grouped by outcome rather than listed flat: "three active, one
              completed, two lost" is the shape of the relationship, and one
              ordered list buries it. */}
          {OUTCOME_ORDER.map((outcome) =>
            deals[outcome]?.length ? (
              <div key={outcome} className="deal-group">
                <h4 className={`deal-group-head outcome-${outcome}`}>
                  {OUTCOME_TITLES[outcome]}
                  <span className="deal-group-count">{deals[outcome].length}</span>
                </h4>
                <ul className="deal-list">
                  {deals[outcome].map((d) => (
                    <DealRow key={d.id} deal={d} onOpen={() => onOpenDeal(d.id)} />
                  ))}
                </ul>
              </div>
            ) : null
          )}
        </section>

        <section className="company-section">
          <header className="company-section-head">
            <h3>Contacts</h3>
            <button type="button" className="btn btn-sm" onClick={() => onAddContact(company.id)}>
              <Plus size={13} strokeWidth={2.4} aria-hidden="true" /> Add contact
            </button>
          </header>
          <ul className="company-contacts">
            {contacts.map((c) => (
              <li key={c.id} className={c.is_primary ? "contact primary" : "contact"}>
                <div className="contact-id">
                  <span className="contact-name">
                    {c.is_primary && <span title="Primary contact" aria-label="Primary contact">★ </span>}
                    {c.name}
                  </span>
                  {c.role && <span className="contact-role">{c.role}</span>}
                </div>
                <div className="contact-reach">
                  {c.email && <span>{c.email}</span>}
                  {c.phone && <span>{c.phone}</span>}
                </div>
                <div className="contact-flags">
                  {c.is_champion && <span className="chip chip-grey">Champion</span>}
                  {c.is_economic_buyer && <span className="chip chip-grey">Econ buyer</span>}
                  {c.status === "departed" && <span className="chip chip-red">Departed</span>}
                  {/* Stated up front rather than only in the 409 afterwards:
                      the POC of any deal cannot be deleted, because the deal's
                      history is unreadable without them. */}
                  {c.is_poc && (
                    <span className="chip chip-grey" title={`POC on ${c.poc_on.join(", ")}`}>
                      POC · {c.poc_on.length}
                    </span>
                  )}
                </div>
                <button
                  className="btn btn-sm subtle"
                  disabled={c.is_poc}
                  title={
                    c.is_poc
                      ? `POC on ${c.poc_on.join(", ")} — reassign those deals first, or mark this contact departed`
                      : `Delete ${c.name}`
                  }
                  aria-label={`Delete ${c.name}`}
                  onClick={() => onDeleteContact(c.id)}
                >
                  ×
                </button>
              </li>
            ))}
            {contacts.length === 0 && (
              <li className="panel-muted">
                No contacts. A deal needs a POC, so add one before opening an
                engagement for this client.
              </li>
            )}
          </ul>
        </section>

        <div className="drawer-danger">
          <button type="button" className="btn btn-sm danger subtle" onClick={() => setConfirmDelete(true)}>
            <Trash2 size={13} strokeWidth={2.2} aria-hidden="true" /> Delete client
          </button>
          <span className="panel-muted">
            Moves to Trash{company.total_deals
              ? ` with its ${company.total_deals} ${company.total_deals === 1 ? "deal" : "deals"}`
              : ""}. Nothing is destroyed.
          </span>
        </div>
      </div>

      {confirmDelete && (
        <div className="dialog-scrim" onClick={() => setConfirmDelete(false)}>
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-label={`Delete ${company.name}`}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="danger-title">
              <AlertTriangle size={15} strokeWidth={2.2} aria-hidden="true" />
              Delete {company.name}?
            </h3>
            <p className="dialog-body">
              It moves to Trash along with its {company.total_deals}{" "}
              {company.total_deals === 1 ? "deal" : "deals"}, which leave the board
              and every metric. Contacts, tasks and health history stay intact, and
              restoring the client brings back exactly the deals that went down
              with it.
            </p>
            <div className="dialog-actions">
              <button className="btn subtle" onClick={() => setConfirmDelete(false)}>Cancel</button>
              <button
                className="btn danger"
                onClick={() => { setConfirmDelete(false); onArchive(); }}
              >
                Move to Trash
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="company-stat">
      <span className="company-stat-value">{value}</span>
      <span className="company-stat-label">{label}</span>
      <span className="company-stat-sub">{sub}</span>
    </div>
  );
}

function DealRow({ deal, onOpen }: { deal: CompanyDealRow; onOpen: () => void }) {
  return (
    <li className={`deal-row outcome-${deal.outcome}`}>
      <button type="button" className="deal-open" onClick={onOpen}>
        <span className="deal-name">{deal.name}</span>
        <span className="card-key">{deal.key}</span>
      </button>
      <div className="deal-meta">
        <span>{deal.mode_label}</span>
        <span>·</span>
        <span>{deal.workstream_label}</span>
        {deal.outcome === "active" && (
          <>
            <span>·</span>
            <span>{deal.column_label}</span>
          </>
        )}
        {deal.poc && (
          <>
            <span>·</span>
            <span>{deal.poc.name}</span>
          </>
        )}
      </div>
      <div className="deal-numbers">
        {deal.quoted_total > 0 && <span>{formatINR(deal.quoted_total)} quoted</span>}
        {deal.margin_pct !== null && <span>{deal.margin_pct}% margin</span>}
        {/* Health only on active deals. A band frozen at the moment a deal
            closed describes nothing anyone can act on, and sitting in a history
            table it reads as current. */}
        {deal.outcome === "active" && deal.health_band && (
          <span className={`health-word text-h-${bandToken(deal.health_band)}`}>
            {deal.health_score}
          </span>
        )}
      </div>
      {deal.outcome !== "active" && (
        <p className="deal-outcome-note">
          {deal.outcome_label}
          {deal.outcome_at ? ` ${relative(deal.outcome_at)}` : ""}
          {deal.outcome_reason ? ` — ${deal.outcome_reason}` : ""}
        </p>
      )}
    </li>
  );
}

function bandToken(band: string): string {
  return band === "at_risk" ? "risk" : band;
}

/** Coarse on purpose — a relationship view never needs minute precision. */
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
