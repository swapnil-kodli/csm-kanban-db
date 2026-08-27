import { useEffect, useMemo, useState } from "react";
import { Briefcase } from "lucide-react";
import type {
  CommMode, CompanyContact, CompanySummary, Mode, NewDealInput, Workstream,
} from "../lib/types";

const MODES: { value: Mode; label: string; hint: string }[] = [
  { value: "pilot", label: "Pilot", hint: "Proving it out. Shorter no-contact window." },
  { value: "customer", label: "Customer", hint: "Committed engagement." },
];

const WORKSTREAMS: { value: Workstream; label: string }[] = [
  { value: "bot_making", label: "Bot-Making" },
  { value: "data_procurement", label: "Data Procurement" },
  { value: "voice_ai_calling", label: "Voice AI Calling" },
];

const COMM_MODES: { value: CommMode; label: string }[] = [
  { value: "whatsapp", label: "WhatsApp" },
  { value: "email", label: "Email" },
];

/**
 * Open an engagement against an existing client.
 *
 * Company and POC are both required, and the POC list is scoped to the selected
 * company — but that scoping is a convenience, not the guarantee. The server
 * re-checks that the POC belongs to the company on every write, because a
 * mismatched pair is well-formed JSON and the consequence is one client's
 * contact, and through Gmail their correspondence, on another client's drawer.
 *
 * `key` and `column` are absent: the key is derived per company (PRE-04-01),
 * and new work lands in the default entry column, which the drawer shows
 * read-only.
 */
export function NewDealDialog({
  companies,
  contactsFor,
  initialCompanyId = "",
  onSubmit,
  onClose,
  busy = false,
}: {
  companies: CompanySummary[];
  /** Loads a company's contacts on demand — the picker cannot offer a POC
   *  before a company is chosen, and loading every company's contacts up front
   *  to populate a list nobody has opened is wasted work. */
  contactsFor: (companyId: string) => Promise<CompanyContact[]>;
  initialCompanyId?: string;
  onSubmit: (input: NewDealInput) => void;
  onClose: () => void;
  busy?: boolean;
}) {
  const [companyId, setCompanyId] = useState(initialCompanyId);
  const [contacts, setContacts] = useState<CompanyContact[]>([]);
  const [loadingContacts, setLoadingContacts] = useState(false);
  const [pocId, setPocId] = useState("");
  const [name, setName] = useState("");
  const [mode, setMode] = useState<Mode>("pilot");
  const [workstream, setWorkstream] = useState<Workstream>("bot_making");
  const [commModes, setCommModes] = useState<CommMode[]>([]);
  const [quoted, setQuoted] = useState("");

  const company = useMemo(
    () => companies.find((c) => c.id === companyId) ?? null,
    [companies, companyId]
  );

  useEffect(() => {
    if (!companyId) { setContacts([]); setPocId(""); return; }
    let cancelled = false;
    setLoadingContacts(true);
    contactsFor(companyId)
      .then((rows) => {
        if (cancelled) return;
        setContacts(rows);
        // Default to the company's primary contact — the usual answer — but
        // never to "whichever came back first", which would silently attach the
        // engagement to an arbitrary person.
        const primary = rows.find((c) => c.is_primary);
        setPocId(primary ? primary.id : rows.length === 1 ? rows[0].id : "");
      })
      .catch(() => { if (!cancelled) setContacts([]); })
      .finally(() => { if (!cancelled) setLoadingContacts(false); });
    return () => { cancelled = true; };
  }, [companyId, contactsFor]);

  const noContacts = Boolean(companyId) && !loadingContacts && contacts.length === 0;
  const ready = Boolean(companyId) && Boolean(pocId) && name.trim() !== "" && !busy;

  function toggleComm(value: CommMode) {
    setCommModes((prev) =>
      prev.includes(value) ? prev.filter((m) => m !== value) : [...prev, value]
    );
  }

  function submit() {
    if (!ready) return;
    const quotedTotal = Number.parseInt(quoted.replace(/[^0-9]/g, ""), 10);
    onSubmit({
      company_id: companyId,
      poc_id: pocId,
      name: name.trim(),
      mode,
      workstream,
      comm_modes: commModes.length ? commModes : undefined,
      quoted_total: Number.isFinite(quotedTotal) ? quotedTotal : undefined,
    });
  }

  return (
    <div className="dialog-scrim" onClick={onClose}>
      <div
        className="dialog dialog-wide"
        role="dialog"
        aria-modal="true"
        aria-label="New deal"
        onClick={(e) => e.stopPropagation()}
      >
        <h3>
          <Briefcase size={15} strokeWidth={2.2} aria-hidden="true" /> New deal
        </h3>

        <label className="field">
          <span className="field-label">Client</span>
          <select value={companyId} onChange={(e) => setCompanyId(e.target.value)} autoFocus>
            <option value="">Choose a client…</option>
            {companies.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.key}
                {c.counts.active ? ` · ${c.counts.active} active` : ""}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span className="field-label">POC</span>
          <select
            value={pocId}
            disabled={!companyId || loadingContacts || noContacts}
            onChange={(e) => setPocId(e.target.value)}
          >
            <option value="">
              {!companyId
                ? "Choose a client first…"
                : loadingContacts
                  ? "Loading contacts…"
                  : noContacts
                    ? "This client has no contacts"
                    : "Choose a POC…"}
            </option>
            {contacts.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}{c.role ? ` · ${c.role}` : ""}{c.email ? ` · ${c.email}` : ""}
              </option>
            ))}
          </select>
          {noContacts && (
            <span className="field-hint">
              A deal must name a POC. Add a contact to {company?.name ?? "this client"} first —
              open the client and use Add contact.
            </span>
          )}
        </label>

        <label className="field">
          <span className="field-label">Deal name</span>
          <input
            placeholder={company ? `e.g. ${company.name} voice pilot` : "What is this engagement?"}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
          <span className="field-hint">
            Its own name, not the client's — with two engagements for one client
            the board is only readable if the cards say different things.
          </span>
        </label>

        <div className="field">
          <span className="field-label">Mode</span>
          <div className="popover-chips">
            {MODES.map((m) => (
              <button
                key={m.value}
                type="button"
                className="chip"
                aria-pressed={mode === m.value}
                title={m.hint}
                onClick={() => setMode(m.value)}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <span className="field-label">Workstream</span>
          <div className="popover-chips">
            {WORKSTREAMS.map((w) => (
              <button
                key={w.value}
                type="button"
                className="chip"
                aria-pressed={workstream === w.value}
                onClick={() => setWorkstream(w.value)}
              >
                {w.label}
              </button>
            ))}
          </div>
        </div>

        <div className="dialog-rule">
          <span>Optional — the drawer can fill these in later</span>
        </div>

        <div className="field-row">
          <label className="field">
            <span className="field-label">Quoted value (₹)</span>
            <input
              inputMode="numeric"
              value={quoted}
              onChange={(e) => setQuoted(e.target.value)}
              placeholder="450000"
            />
          </label>
          <div className="field">
            <span className="field-label">Mode of communication</span>
            <div className="popover-chips">
              {COMM_MODES.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  className="chip"
                  aria-pressed={commModes.includes(c.value)}
                  onClick={() => toggleComm(c.value)}
                >
                  {c.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="dialog-actions">
          <button className="btn subtle" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!ready} onClick={submit}>
            {busy ? "Creating…" : "Create deal"}
          </button>
        </div>
      </div>
    </div>
  );
}
