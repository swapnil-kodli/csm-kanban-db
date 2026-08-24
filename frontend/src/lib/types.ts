export type HealthBand = "healthy" | "watch" | "at_risk" | "critical";
export type BoardView = "work" | "health" | "lifecycle";
export type GroupBy = "none" | "priority" | "segment" | "renewal_month";
export type TaskBucket = "today" | "this_week" | "follow_up" | "waiting" | "done";

export interface Badge {
  key: string;
  label: string;
  variant: "red" | "amber" | "green" | "grey" | "outline" | "red-outline";
}

export interface NextAction {
  id: string;
  title: string;
  due_date: string;
  overdue: boolean;
}

export interface AccountCard {
  kind: "account";
  id: string;
  account_id: string;
  key: string;
  name: string;
  segment: string;
  segment_label: string;
  city: string | null;
  arr: number;
  lifecycle_stage: string;
  lifecycle_label: string;
  lifecycle_dot: string;
  closed_reason: string | null;
  health_score: number;
  health_band: HealthBand;
  computed_band: HealthBand;
  health_band_label: string;
  health_dot: string;
  is_overridden: boolean;
  override_reason: string | null;
  velocity: number | null;
  days_to_renewal: number | null;
  days_since_contact: number | null;
  expansion_flag: boolean;
  pinned: boolean;
  attention_score: number;
  badges: Badge[];
  next_action: NextAction | null;
  open_tasks: number;
  overdue_tasks: number;
  open_escalations: number;
  lane?: string;
  lane_title?: string;
  attention_terms?: AttentionTerm[];
}

export interface TaskCard {
  kind: "task";
  id: string;
  account_id: string;
  title: string;
  type: string;
  type_label: string;
  bucket: TaskBucket;
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
  account: {
    id: string;
    key: string;
    name: string;
    health_band: HealthBand;
    health_dot: string;
    arr: number;
    segment: string;
  };
  lane?: string;
  lane_title?: string;
}

export type Card = AccountCard | TaskCard;

export interface Column {
  key: string;
  title: string;
  dot: string;
  count: number;
  total_arr: number;
  cards: Card[];
  droppable: boolean;
  drop_action: "task_bucket" | "health_override" | "lifecycle_stage";
  collapse_older_than_days: number | null;
  subgroups?: { key: string; title: string; cards: Card[] }[];
  handoff_inbox?: boolean;
}

export interface Swimlane {
  key: string;
  title: string;
  count: number;
  total_arr: number;
}

export interface BoardResponse {
  view: BoardView;
  group_by: GroupBy;
  columns: Column[];
  swimlanes: Swimlane[];
  total_cards: number;
}

export interface Metric {
  key: string;
  label: string;
  value: number;
  format: "count" | "inr";
  sub: string;
  sub_value?: number;
  sub_format?: string;
  filters: Filters;
  view: BoardView | null;
}

export interface AttentionTerm {
  label: string;
  detail: string;
  value: number;
}

export interface Filters {
  bands?: HealthBand[];
  renewal_window?: number;
  arr_min?: number;
  arr_max?: number;
  owner_id?: string;
  stages?: string[];
  segments?: string[];
  tags?: string[];
  last_contact_gt?: number;
  expansion?: boolean;
  overdue?: boolean;
  attention?: boolean;
  high_value?: boolean;
  task_status?: string;
  priorities?: string[];
  q?: string;
}

export interface SavedView {
  id: string;
  name: string;
  filter_json: Filters;
  pinned: boolean;
  is_default: boolean;
}

export interface Activity {
  id: string;
  type: string;
  occurred_at: string;
  summary: string;
  body: string | null;
  contact_id: string | null;
  contact_name?: string | null;
  created_task_id: string | null;
}

export interface Contact {
  id: string;
  name: string;
  role: string;
  email: string | null;
  phone: string | null;
  is_champion: boolean;
  is_economic_buyer: boolean;
  status: "active" | "departed";
}

export interface Milestone {
  id: string;
  label: string;
  status: "pending" | "done";
  target_date: string | null;
  overdue: boolean;
}

export interface AccountDetail {
  card: AccountCard;
  account: {
    id: string; key: string; name: string; segment: string; segment_label: string;
    city: string | null; lifecycle_stage: string; lifecycle_label: string; lifecycle_dot: string;
    closed_reason: string | null; arr: number; tags: string[]; expansion_flag: boolean;
    pinned: boolean; entitled_seats: number;
    owner: { id: string; name: string; initials: string } | null;
    handoff_received_at: string | null; last_contact_at: string | null;
    days_since_contact: number | null;
  };
  health: {
    score: number; computed_band: HealthBand; computed_band_label: string;
    effective_band: HealthBand; effective_band_label: string; dot: string;
    velocity: number | null;
    override: {
      band: HealthBand; band_label: string; reason: string; set_at: string | null;
      age_days: number | null; stale: boolean;
    } | null;
    components: { usage: number; engagement: number; support: number; sentiment: number } | null;
    weights: Record<string, number>;
    snapshots: { date: string; score: number }[];
  };
  attention: { score: number; terms: AttentionTerm[] };
  subscription: {
    id: string; start_date: string | null; renewal_date: string; days_to_renewal: number;
    auto_renew: boolean; status: string;
    line_items: { offering: string; qty: number; rate: number }[];
  } | null;
  contacts: Contact[];
  tasks: TaskCard[];
  activities: Activity[];
  risks: { id: string; type: string; severity: string; status: string; note: string | null; opened_at: string }[];
  milestones: Milestone[];
  usage: { date: string; active_users: number; sessions: number; feature_adoption_pct: number }[];
}

export interface SearchResults {
  query: string;
  accounts: { id: string; key: string; name: string; segment: string; city: string | null; arr: number; health_band: HealthBand; health_dot: string; health_score: number }[];
  contacts: { id: string; name: string; role: string; account_id: string; account_name: string; status: string }[];
  tasks: { id: string; title: string; bucket: string; status: string; due_date: string; type_label: string; account_id: string; account_name: string }[];
  activities: { id: string; type: string; summary: string; occurred_at: string; account_id: string; account_name: string }[];
}
