import { useState } from "react";
import { Building2 } from "lucide-react";
import type { ClientType, NewCompanyInput } from "../lib/types";

const CLIENT_TYPES: { value: ClientType; label: string }[] = [
  { value: "voice_ai_only", label: "Voice AI only" },
  { value: "data_plus_voice_ai", label: "Data + Voice AI" },
];

/**
 * Add a client organisation.
 *
 * Two required fields, because a company only has two: who they are and what
 * kind of client they are. Everything about the WORK — mode, workstream,
 * quoted value, health — belongs to a Deal, and a company can have several.
 *
 * The contact block is optional here but effectively required before any deal
 * exists, since `deal.poc_id` is mandatory. Offering it now saves a second
 * trip; the New Deal flow asks for one if this was skipped.
 *
 * `key` is absent: derived server-side from the name (PRE-04) and immutable, so
 * nobody has to invent an identifier or keep them collision-free.
 */
export function NewCompanyDialog({
  onSubmit,
  onClose,
  busy = false,
}: {
  onSubmit: (input: NewCompanyInput) => void;
  onClose: () => void;
  busy?: boolean;
}) {
  const [name, setName] = useState("");
  const [clientType, setClientType] = useState<ClientType>("voice_ai_only");
  const [city, setCity] = useState("");
  const [pocName, setPocName] = useState("");
  const [pocRole, setPocRole] = useState("");
  const [pocEmail, setPocEmail] = useState("");
  const [pocPhone, setPocPhone] = useState("");

  const ready = name.trim() !== "" && !busy;

  function submit() {
    if (!ready) return;
    onSubmit({
      name: name.trim(),
      client_type: clientType,
      city: city.trim() || undefined,
      primary_contact_name: pocName.trim() || undefined,
      primary_contact_role: pocRole.trim() || undefined,
      primary_contact_email: pocEmail.trim() || undefined,
      primary_contact_phone: pocPhone.trim() || undefined,
    });
  }

  return (
    <div className="dialog-scrim" onClick={onClose}>
      <div
        className="dialog dialog-wide"
        role="dialog"
        aria-modal="true"
        aria-label="New client"
        onClick={(e) => e.stopPropagation()}
      >
        <h3>
          <Building2 size={15} strokeWidth={2.2} aria-hidden="true" /> New client
        </h3>

        <label className="field">
          <span className="field-label">Name</span>
          <input
            placeholder="Sunbeam Retail Partners"
            value={name}
            autoFocus
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
          <span className="field-hint">
            The key (SRP-01) is derived from this and cannot be changed later.
            Renaming the client afterwards leaves the key alone.
          </span>
        </label>

        <div className="field">
          <span className="field-label">Client type</span>
          <div className="popover-chips">
            {CLIENT_TYPES.map((t) => (
              <button
                key={t.value}
                type="button"
                className="chip"
                aria-pressed={clientType === t.value}
                onClick={() => setClientType(t.value)}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <label className="field">
          <span className="field-label">City</span>
          <input value={city} onChange={(e) => setCity(e.target.value)} placeholder="Pune" />
        </label>

        <div className="dialog-rule">
          <span>First contact — needed before this client can have a deal</span>
        </div>

        <div className="field-row">
          <label className="field">
            <span className="field-label">Name</span>
            <input value={pocName} onChange={(e) => setPocName(e.target.value)} placeholder="Asha Rao" />
          </label>
          <label className="field">
            <span className="field-label">Role</span>
            <input value={pocRole} onChange={(e) => setPocRole(e.target.value)} placeholder="Ops Lead" />
          </label>
        </div>
        <div className="field-row">
          <label className="field">
            <span className="field-label">Email</span>
            <input
              type="email"
              value={pocEmail}
              onChange={(e) => setPocEmail(e.target.value)}
              placeholder="asha@sunbeam.example"
            />
            <span className="field-hint">The Gmail panel keys off this address.</span>
          </label>
          <label className="field">
            <span className="field-label">Phone</span>
            <input value={pocPhone} onChange={(e) => setPocPhone(e.target.value)} placeholder="+91…" />
          </label>
        </div>

        <div className="dialog-actions">
          <button className="btn subtle" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={!ready} onClick={submit}>
            {busy ? "Creating…" : "Create client"}
          </button>
        </div>
      </div>
    </div>
  );
}
