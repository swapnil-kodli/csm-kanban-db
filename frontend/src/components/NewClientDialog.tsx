import { useState } from "react";
import { Building2 } from "lucide-react";
import type { ClientType, CommMode, Mode, NewClientInput, Workstream } from "../lib/types";

const MODES: { value: Mode; label: string; hint: string }[] = [
  { value: "pilot", label: "Pilot", hint: "Proving it out. Shorter no-contact window." },
  { value: "customer", label: "Customer", hint: "Committed engagement." },
];

const CLIENT_TYPES: { value: ClientType; label: string }[] = [
  { value: "voice_ai_only", label: "Voice AI only" },
  { value: "data_plus_voice_ai", label: "Data + Voice AI" },
];

const WORKSTREAMS: { value: Workstream; label: string; glyph: string }[] = [
  { value: "bot_making", label: "Bot-Making", glyph: "◔" },
  { value: "data_procurement", label: "Data Procurement", glyph: "◑" },
  { value: "voice_ai_calling", label: "Voice AI Calling", glyph: "◕" },
];

const COMM_MODES: { value: CommMode; label: string }[] = [
  { value: "whatsapp", label: "WhatsApp" },
  { value: "email", label: "Email" },
];

/**
 * Put a real client on the board.
 *
 * Four required fields — name, mode, client type, workstream — because those
 * are the four the card renders. Everything below the rule is optional and can
 * equally be filled in from the drawer later; requiring it here would block
 * someone from recording a client they have not finished scoping, which is
 * exactly when they most want it visible.
 *
 * Two fields are deliberately absent:
 *   key     derived server-side from the name and immutable thereafter, so
 *           nobody has to invent an identifier or keep them collision-free.
 *   column  new work lands in the default entry column. The drawer shows
 *           Column as read-only, and offering it here would contradict that.
 */
export function NewClientDialog({
  onSubmit,
  onClose,
  busy = false,
}: {
  onSubmit: (input: NewClientInput) => void;
  onClose: () => void;
  busy?: boolean;
}) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState<Mode>("pilot");
  const [clientType, setClientType] = useState<ClientType>("voice_ai_only");
  const [workstream, setWorkstream] = useState<Workstream>("bot_making");

  const [city, setCity] = useState("");
  const [commModes, setCommModes] = useState<CommMode[]>([]);
  const [quoted, setQuoted] = useState("");
  const [pocName, setPocName] = useState("");
  const [pocRole, setPocRole] = useState("");
  const [pocEmail, setPocEmail] = useState("");
  const [pocPhone, setPocPhone] = useState("");

  const ready = name.trim() !== "" && !busy;

  function toggleComm(value: CommMode) {
    setCommModes((prev) =>
      prev.includes(value) ? prev.filter((m) => m !== value) : [...prev, value]
    );
  }

  function submit() {
    if (!ready) return;
    const quotedTotal = Number.parseInt(quoted.replace(/[^0-9]/g, ""), 10);
    onSubmit({
      name: name.trim(),
      mode,
      client_type: clientType,
      workstream,
      city: city.trim() || undefined,
      comm_modes: commModes.length ? commModes : undefined,
      quoted_total: Number.isFinite(quotedTotal) ? quotedTotal : undefined,
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
                <span aria-hidden="true">{w.glyph}</span> {w.label}
              </button>
            ))}
          </div>
        </div>

        <div className="dialog-rule">
          <span>Optional — the drawer can fill these in later</span>
        </div>

        <div className="field-row">
          <label className="field">
            <span className="field-label">City</span>
            <input value={city} onChange={(e) => setCity(e.target.value)} placeholder="Pune" />
          </label>
          <label className="field">
            <span className="field-label">Quoted value (₹)</span>
            <input
              inputMode="numeric"
              value={quoted}
              onChange={(e) => setQuoted(e.target.value)}
              placeholder="450000"
            />
          </label>
        </div>

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

        <div className="field-row">
          <label className="field">
            <span className="field-label">Primary contact</span>
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
