/** Indian short scale. Amounts are stored as whole rupees; formatting is a UI job. */
export function inr(value: number): string {
  if (!value) return "₹0";
  const abs = Math.abs(value);
  if (abs >= 10000000) return `₹${trim(value / 10000000)} Cr`;
  if (abs >= 100000) return `₹${trim(value / 100000)} L`;
  if (abs >= 1000) return `₹${trim(value / 1000)} K`;
  return `₹${value}`;
}

function trim(n: number): string {
  const rounded = n >= 100 ? Math.round(n) : Math.round(n * 100) / 100;
  return String(rounded);
}

export function inrExact(value: number): string {
  return `₹${value.toLocaleString("en-IN")}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function shortDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((startOf(today) - startOf(d)) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return `${diff} days ago`;
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function dueLabel(days: number, overdue: boolean, overdueDays: number): string {
  if (overdue) return `Overdue by ${overdueDays}d`;
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  return `Due in ${days} days`;
}

export function contactLabel(days: number | null): string {
  if (days === null) return "No contact logged";
  if (days === 0) return "Last contact today";
  if (days === 1) return "Last contact 1d ago";
  return `Last contact ${days}d ago`;
}

export function velocityGlyph(v: number | null): { glyph: string; cls: string; label: string } {
  if (v === null) return { glyph: "–", cls: "flat", label: "no 30-day history" };
  if (v > 0) return { glyph: "▲", cls: "up", label: `up ${v} points in 30 days` };
  if (v < 0) return { glyph: "▼", cls: "down", label: `down ${Math.abs(v)} points in 30 days` };
  return { glyph: "–", cls: "flat", label: "flat over 30 days" };
}

export function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function isoPlusDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
