export type HealthBand = "healthy" | "watch" | "at_risk" | "critical";
/** Column keys are user-defined now; nothing may assume a fixed set. */
export type BoardColumnKey = string;

export interface ColumnConfig {
  id: string;
  key: string;
  label: string;
  color: string;
  position: number;
  is_archived: boolean;
  is_default_entry: boolean;
  description: string | null;
  stalled_after_days: number | null;
  card_count: number;
}

export interface ColumnImpact {
  card_count: number;
  is_default_entry: boolean;
}
export type Workstream = "bot_making" | "data_procurement" | "voice_ai_calling";
export type Mode = "pilot" | "customer";
export type ClientType = "voice_ai_only" | "data_plus_voice_ai";
export type CommMode = "whatsapp" | "email";
export type GroupBy = "none" | "priority" | "mode" | "client_type" | "workstream";
export type TaskType =
  | "onboarding" | "risk" | "renewal" | "expansion" | "checkin" | "escalation" | "admin";
export type TaskPriority = "critical" | "high" | "normal";
export type TaskBucket = "today" | "this_week" | "follow_up" | "waiting" | "done";

/**
 * The card face carries exactly four things: name, mode, workstream, health.
 * Everything else here is board mechanics or grouping input — never rendered
 * on the card itself.
 */
export type Outcome = "active" | "completed" | "lost";

export interface DealCard {
  kind: "deal";
  id: string;
  deal_id: string;
  /** The DEAL's key and name — PRE-04-01, not the company's. */
  key: string;
  name: string;
  /** The company chip. Opens the company view; never the card's main label. */
  company_id: string;
  company_key: string | null;
  company_name: string;
  mode: Mode;
  mode_label: string;
  workstream: Workstream;
  workstream_label: string;
  workstream_glyph: string;
  workstream_dot: string;
  health_score: number;
  health_band: HealthBand;
  health_band_label: string;
  health_dot: string;
  is_overridden: boolean;
  column_id: string;
  column_key: string | null;
  column_label: string;
  column_color: string;
  attention_score: number;
  pinned: boolean;
  handoff: boolean;
  stalled_handoff: boolean;
  column_stalled: boolean;
  client_type: ClientType;
  quoted_total: number;
  outcome: Outcome;
  lane?: string;
  lane_title?: string;
}

export interface TaskCard {
  kind: "task";
  id: string;
  deal_id: string;
  title: string;
  type: string;
  type_label: string;
  bucket: TaskBucket;
  bucket_label: string;
  status: "open" | "done";
  priority: "critical" | "high" | "normal";
  due_date: string;
  days_until_due: number;
  overdue: boolean;
  overdue_days: number;
  provenance: string | null;
  rule_key: string | null;
  sort_index: number;
  completed_at: string | null;
  deal: { id: string; key: string; name: string; health_band: HealthBand };
}

export interface BoardColumn {
  id: string;
  key: string;
  title: string;
  color: string;
  description: string | null;
  position: number;
  count: number;
  total_quoted: number;
  cards: DealCard[];
  droppable: boolean;
  is_default_entry: boolean;
  stalled_after_days: number | null;
}

export interface Swimlane {
  key: string;
  title: string;
  count: number;
  total_quoted: number;
}

export interface BoardResponse {
  group_by: GroupBy;
  columns: BoardColumn[];
  swimlanes: Swimlane[];
  /** Post-filter. Zero here does not mean the book is empty — see book_size. */
  total_cards: number;
  /** Unfiltered active deals. Separates "no deals yet" from "no matches". */
  book_size: number;
  archived_count: number;
  /** How many clients this book of work spans. */
  company_count: number;
}

/** A client organisation. Two required fields; the work belongs to a Deal. */
export interface NewCompanyInput {
  name: string;
  client_type: ClientType;
  city?: string;
  primary_contact_name?: string;
  primary_contact_role?: string;
  primary_contact_email?: string;
  primary_contact_phone?: string;
}

/**
 * An engagement. `company_id` and `poc_id` are both required, and the POC must
 * be a contact of that company — the picker only offers those, and the server
 * rejects anything else regardless.
 */
export interface NewDealInput {
  company_id: string;
  poc_id: string;
  name: string;
  mode: Mode;
  workstream: Workstream;
  comm_modes?: CommMode[];
  quoted_total?: number;
}

export interface CompanyContact {
  id: string;
  name: string;
  role: string;
  email: string | null;
  phone: string | null;
  is_primary: boolean;
  is_champion: boolean;
  is_economic_buyer: boolean;
  status: "active" | "departed";
  /** Whether this contact is POC on any deal, and which — the UI explains why
   *  deleting is refused before someone tries it. */
  is_poc: boolean;
  poc_on: string[];
}

/** Worst active band with its count. Null band = no active deals at all. */
export interface HealthRollup {
  band: HealthBand | null;
  band_label: string | null;
  dot: string | null;
  worst_count: number;
  active_count: number;
}

export interface CompanySummary {
  id: string;
  key: string;
  name: string;
  city: string | null;
  client_type: ClientType;
  client_type_label: string;
  tags: string[];
  archived_at: string | null;
  health: HealthRollup;
  last_contact_at: string | null;
  counts: { active: number; completed: number; lost: number };
  total_deals: number;
  quoted_total: number;
  revenue_recognised: number;
  total_cost: number;
  gross_margin: number;
  margin_pct: number | null;
  owner?: { id: string; name: string; initials: string } | null;
}

export interface CompanyDealRow {
  id: string;
  key: string;
  name: string;
  mode: Mode;
  mode_label: string;
  workstream: Workstream;
  workstream_label: string;
  column_label: string;
  column_color: string;
  outcome: Outcome;
  outcome_label: string;
  outcome_at: string | null;
  outcome_reason: string | null;
  /** Null on anything not active — a band frozen at close describes nothing. */
  health_band: HealthBand | null;
  health_score: number | null;
  quoted_total: number;
  revenue_recognised: number;
  margin_pct: number | null;
  poc: { id: string; name: string; email: string | null } | null;
  last_contact_at: string | null;
}

export interface CompanyDetail {
  company: CompanySummary;
  deals: Record<Outcome, CompanyDealRow[]>;
  contacts: CompanyContact[];
}

/**
 * A soft-deleted deal, as Trash shows it. Deliberately not a DealCard: an
 * archived deal has no attention score, no size band and no stall state,
 * because those describe live work. What matters here is identity plus the
 * weight of what a hard delete would destroy.
 */
export interface DealTrashRow {
  id: string;
  key: string;
  name: string;
  company_id: string;
  company_name: string;
  mode: Mode;
  mode_label: string;
  workstream: Workstream;
  workstream_label: string;
  column_label: string;
  outcome: Outcome;
  archived_at: string | null;
  quoted_total: number;
  owns: { tasks: number; snapshots: number; risks: number };
  restorable: boolean;
}

/** A soft-deleted company. Deleting one takes its deals down with it. */
export interface CompanyTrashRow {
  id: string;
  key: string;
  name: string;
  client_type_label: string;
  city: string | null;
  archived_at: string | null;
  quoted_total: number;
  owns: { deals: number; contacts: number; tasks: number };
  restorable: boolean;
}

export interface Metric {
  key: string;
  label: string;
  value: number;
  format: "count" | "inr";
  sub: string;
  margin_band?: string;
  filters: Record<string, unknown>;
}

export interface LineItem {
  offering: string;
  qty: number;
  rate: number;
}

export interface CostItem {
  label: string;
  amount: number;
}

export interface Commercials {
  quoted_total: number;
  quoted_at: string | null;
  quote_notes: string | null;
  quoted_line_items: LineItem[];
  revenue_recognised: number;
  cost_items: CostItem[];
  total_cost: number;
  gross_margin: number;
  /** null when nothing has been billed — unknown, not 100%. */
  margin_pct: number | null;
  margin_band: string;
  quote_gap: number;
  quote_gap_pct: number | null;
}

export interface Contact {
  id: string;
  name: string;
  role: string;
  email: string | null;
  phone: string | null;
  is_champion: boolean;
  is_economic_buyer: boolean;
  is_primary: boolean;
  status: string;
}

export interface AttentionTerm {
  label: string;
  detail: string;
  value: number;
}

export interface EmailThread {
  thread_id: string;
  subject: string;
  snippet: string;
  last_message_at: string | null;
  message_count: number;
  participants: string[];
  unread: boolean;
}

export type EmailThreadState =
  | "ok"
  | "disabled"
  | "not_connected"
  | "no_poc_email"
  | "token_expired"
  | "error";

export interface EmailThreadsResponse {
  state: EmailThreadState;
  threads: EmailThread[];
  detail?: string;
}

export interface DealDetail {
  card: DealCard;
  /** The client. Read-only in the drawer — company fields are edited on the
   *  company view, in one place, or the two drift. */
  company: {
    id: string;
    key: string;
    name: string;
    city: string | null;
    client_type: ClientType;
    client_type_label: string;
    tags: string[];
  } | null;
  /** This deal's own POC. The Gmail panel keys off their address. */
  poc: {
    id: string;
    name: string;
    role: string;
    email: string | null;
    phone: string | null;
  } | null;
  deal: {
    id: string;
    key: string;
    name: string;
    company_id: string;
    poc_id: string;
    outcome: Outcome;
    outcome_at: string | null;
    outcome_reason: string | null;
    column_id: string;
    column_key: string | null;
    column_label: string;
    column_color: string;
    days_in_column: number | null;
    column_stalled: boolean;
    workstream: Workstream;
    workstream_label: string;
    workstream_glyph: string;
    mode: Mode;
    mode_label: string;
    size_band: string;
    pinned: boolean;
    owner: { id: string; name: string; initials: string } | null;
    handoff_received_at: string | null;
    last_contact_at: string | null;
    days_since_contact: number | null;
    no_contact: boolean;
    stalled_handoff: boolean;
  };
  comm_modes: { value: CommMode; label: string }[];
  show_email_threads: boolean;
  health: {
    score: number;
    computed_band: HealthBand;
    computed_band_label: string;
    effective_band: HealthBand;
    effective_band_label: string;
    dot: string;
    velocity: number | null;
    note: string | null;
    override: {
      band: HealthBand;
      band_label: string;
      reason: string;
      set_at: string | null;
      age_days: number | null;
      stale: boolean;
    } | null;
    components: { usage: number; engagement: number; support: number; sentiment: number } | null;
    weights: Record<string, number>;
    snapshots: { date: string; score: number }[];
  };
  commercials: Commercials;
  attention: { score: number; terms: AttentionTerm[]; summary: string | null };
  contacts: Contact[];
  tasks: TaskCard[];
  risks: {
    id: string;
    type: string;
    severity: string;
    status: string;
    note: string | null;
    opened_at: string;
  }[];
  usage: { date: string; active_users: number; sessions: number; feature_adoption_pct: number }[];
}

/**
 * Board filter state. Ephemeral by design — held in the URL query string so a
 * filtered board stays shareable, never persisted as a stored object.
 */
export interface Filters {
  bands?: string[];
  modes?: string[];
  client_types?: string[];
  workstreams?: string[];
  columns?: string[];
  quoted_min?: number;
  quoted_max?: number;
  owner_id?: string;
  tags?: string[];
  negative_margin?: boolean;
  thin_margin?: boolean;
  stalled_handoff?: boolean;
  column_stalled?: boolean;
  no_contact?: boolean;
  overdue?: boolean;
  attention?: boolean;
  high_value?: boolean;
  q?: string;
}
