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
export type TaskBucket = "today" | "this_week" | "follow_up" | "waiting" | "done";

/**
 * The card face carries exactly four things: name, mode, workstream, health.
 * Everything else here is board mechanics or grouping input — never rendered
 * on the card itself.
 */
export interface AccountCard {
  kind: "account";
  id: string;
  account_id: string;
  key: string;
  name: string;
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
  lane?: string;
  lane_title?: string;
}

export interface TaskCard {
  kind: "task";
  id: string;
  account_id: string;
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
  account: { id: string; key: string; name: string; health_band: HealthBand };
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
  cards: AccountCard[];
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
  total_cards: number;
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

export interface AccountDetail {
  card: AccountCard;
  account: {
    id: string;
    key: string;
    name: string;
    city: string | null;
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
    client_type: ClientType;
    client_type_label: string;
    size_band: string;
    tags: string[];
    pinned: boolean;
    owner: { id: string; name: string; initials: string } | null;
    handoff_received_at: string | null;
    last_contact_at: string | null;
    days_since_contact: number | null;
    no_contact: boolean;
    stalled_handoff: boolean;
  };
  poc: { name: string | null; email: string | null; phone: string | null };
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
  attention: { score: number; terms: AttentionTerm[] };
  contacts: {
    id: string;
    name: string;
    role: string;
    email: string | null;
    phone: string | null;
    is_champion: boolean;
    is_economic_buyer: boolean;
    status: string;
  }[];
  tasks: TaskCard[];
  activities: {
    id: string;
    type: string;
    occurred_at: string;
    summary: string;
    body: string | null;
    contact_id: string | null;
    contact_name: string | null;
    created_task_id: string | null;
  }[];
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
