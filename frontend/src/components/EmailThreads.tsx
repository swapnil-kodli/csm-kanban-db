import { Component, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { apiGet } from "../lib/api";
import { relativeDate } from "../lib/format";
import type { EmailThreadsResponse, EmailThread } from "../lib/types";

/**
 * A Gmail failure must never block the drawer from opening or the board from
 * rendering, so the whole panel sits behind an error boundary as well as the
 * server-side state machine.
 */
export class EmailThreadsBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed) {
      return (
        <div className="panel-error">
          Email threads could not be rendered. The rest of this record is unaffected.
        </div>
      );
    }
    return this.props.children;
  }
}

export function EmailThreadsPanel({
  accountId,
  onMarkContacted,
}: {
  accountId: string;
  /** A thread is evidence of contact; its date sets `last_contact_at`. */
  onMarkContacted: (iso: string) => void;
}) {
  const [data, setData] = useState<EmailThreadsResponse | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    apiGet<EmailThreadsResponse>(`/accounts/${accountId}/email-threads`)
      .then((d) => live && setData(d))
      .catch(() => live && setData({ state: "error", threads: [] }));
    return () => {
      live = false;
    };
  }, [accountId]);

  if (!data) return <p className="panel-muted">Loading threads…</p>;

  // Four states, each rendered cleanly — none of them an exception.
  if (data.state === "disabled")
    return <p className="panel-muted">Gmail integration is turned off.</p>;
  if (data.state === "not_connected")
    return (
      <a className="btn btn-sm" href="../api/google/authorize?app_base=/">
        Connect Gmail
      </a>
    );
  if (data.state === "no_poc_email")
    return <p className="panel-muted">Add a POC email to see threads.</p>;
  if (data.state === "token_expired" || data.state === "error")
    return (
      <div className="panel-error">
        <span>{data.detail || "Gmail could not be reached."}</span>
        <a className="btn btn-sm" href="../api/google/authorize?app_base=/">
          Reconnect
        </a>
      </div>
    );
  if (data.threads.length === 0)
    return <p className="panel-muted">No threads with this POC yet.</p>;

  return (
    <ul className="thread-list">
      {data.threads.map((t: EmailThread) => (
        <li key={t.thread_id} className={t.unread ? "thread unread" : "thread"}>
          <button
            className="thread-head"
            onClick={() => setExpanded(expanded === t.thread_id ? null : t.thread_id)}
            aria-expanded={expanded === t.thread_id}
          >
            <span className="thread-subject">{t.subject}</span>
            <span className="thread-count">{t.message_count}</span>
            <span className="thread-date">{relativeDate(t.last_message_at)}</span>
          </button>
          <p className="thread-snippet">{t.snippet}</p>
          {expanded === t.thread_id && (
            <div className="thread-detail">
              <p className="thread-participants">{t.participants.join(", ")}</p>
              <button
                className="btn btn-sm"
                disabled={!t.last_message_at}
                onClick={() => t.last_message_at && onMarkContacted(t.last_message_at)}
              >
                Set as last contact
              </button>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
