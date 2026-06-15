import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchAuditEvents, type AuditEvent } from "../api";
import { formatDateTime, formatDuration, formatLabel, shortId, statusTone } from "../format";

type Props = {
  onOpenCase?: (caseId: string) => void;
  onOpenBatch?: (batchId: string) => void;
};

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

export default function AuditHistory({ onOpenCase, onOpenBatch }: Props) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const [page, setPage] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const pageCount = Math.max(1, Math.ceil(totalCount / pageSize));
  const firstVisibleRecord = totalCount === 0 ? 0 : page * pageSize + 1;
  const lastVisibleRecord = Math.min(totalCount, page * pageSize + events.length);

  async function refresh() {
    setIsRefreshing(true);
    setRefreshError(null);
    try {
      const response = await fetchAuditEvents({ limit: pageSize, offset: page * pageSize });
      setEvents(response.items);
      setTotalCount(response.total_count);
      setLastUpdatedAt(new Date().toISOString());
      if (response.items.length === 0 && response.total_count > 0 && page > 0) {
        setPage(Math.max(0, Math.ceil(response.total_count / pageSize) - 1));
      }
    } catch {
      setRefreshError("Activity could not be refreshed.");
    } finally {
      setIsRefreshing(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [page, pageSize]);

  return (
    <section className="tool-pane">
      <header className="tool-header row-header">
        <div>
          <h2>Activity</h2>
          <p>
            {totalCount === 0
              ? "No recent system or reviewer events"
              : `Showing ${firstVisibleRecord}-${lastVisibleRecord} of ${totalCount} system and reviewer events`}
          </p>
        </div>
        <div className="activity-controls">
          <label>
            <span>Display</span>
            <select
              aria-label="Activity records per page"
              value={pageSize}
              onChange={(event) => {
                setPageSize(Number(event.target.value));
                setPage(0);
              }}
            >
              {PAGE_SIZE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <div className="activity-page-controls" aria-label="Activity pagination">
            <button
              className="icon-button"
              type="button"
              title="Previous activity page"
              disabled={page === 0}
              onClick={() => setPage((current) => Math.max(0, current - 1))}
            >
              <ChevronLeft size={16} />
            </button>
            <span>
              Page {page + 1} of {pageCount}
            </span>
            <button
              className="icon-button"
              type="button"
              title="Next activity page"
              disabled={page + 1 >= pageCount}
              onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}
            >
              <ChevronRight size={16} />
            </button>
          </div>
          <button
            className={`activity-refresh-button ${isRefreshing ? "is-loading" : ""}`}
            type="button"
            title="Refresh activity"
            disabled={isRefreshing}
            onClick={refresh}
          >
            <RefreshCw size={16} />
            <span>{isRefreshing ? "Refreshing..." : "Refresh"}</span>
          </button>
          {refreshError ? (
            <span className="activity-refresh-status" data-tone="error">
              {refreshError}
            </span>
          ) : lastUpdatedAt ? (
            <span className="activity-refresh-status">Updated {formatDateTime(lastUpdatedAt)}</span>
          ) : null}
        </div>
      </header>
      <div className="audit-list">
        {events.length === 0 ? <div className="field-evidence-empty">No activity recorded yet.</div> : null}
        {events.map((event) => {
          const targetLabel = event.case
            ? `${event.case.brand_name} · ${event.case.display_label}`
            : event.case_id
              ? `Case ${shortId(event.case_id)}`
              : event.batch_id
                ? `Batch ${shortId(event.batch_id)}`
                : "System";
          const isCaseEvent = Boolean(event.case_id && onOpenCase);
          const isBatchEvent = Boolean(event.batch_id && onOpenBatch);
          const modelProcessingTime = formatModelProcessingTime(event.case);
          const rowContent = (
            <>
              <div className="audit-row-main">
                <strong>{formatEventType(event.event_type)}</strong>
                <span>{targetLabel}</span>
                <p>{eventSummary(event)}</p>
              </div>
              <div className="audit-row-meta">
                {event.case ? (
                  <span className="status-badge status-badge--compact" data-tone={statusTone(event.case.status)}>
                    {formatLabel(event.case.status)}
                  </span>
                ) : null}
                <time>{formatDateTime(event.created_at)}</time>
                {modelProcessingTime ? <span className="audit-processing-time">{modelProcessingTime}</span> : null}
              </div>
            </>
          );

          if (isCaseEvent) {
            return (
              <button
                className="audit-row audit-row--button"
                key={event.id}
                type="button"
                onClick={() => onOpenCase?.(event.case_id ?? "")}
              >
                {rowContent}
              </button>
            );
          }
          if (isBatchEvent) {
            return (
              <button
                className="audit-row audit-row--button"
                key={event.id}
                type="button"
                onClick={() => onOpenBatch?.(event.batch_id ?? "")}
              >
                {rowContent}
              </button>
            );
          }
          return (
            <article className="audit-row" key={event.id}>
              {rowContent}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function formatEventType(eventType: string): string {
  const labels: Record<string, string> = {
    batch_created: "Batch created",
    case_created: "Case created",
    human_decision_recorded: "Reviewer decision",
    label_image_replaced: "Label image replaced",
    sampled_review_selected: "Sampled for review",
    verification_completed: "Verification completed",
    verification_failed: "Verification failed",
    verification_queued: "Verification queued",
  };
  return labels[eventType] ?? formatLabel(eventType);
}

export function eventSummary(event: AuditEvent): string {
  const payload = event.payload ?? {};
  if (event.event_type === "human_decision_recorded") {
    const decision = typeof payload.decision === "string" ? formatLabel(payload.decision) : "Decision";
    const note = typeof payload.note === "string" && payload.note.trim() ? `: ${payload.note.trim()}` : "";
    return `${decision}${note}`;
  }
  if (event.event_type === "verification_completed") {
    const recommendation = typeof payload.recommendation === "string" ? payload.recommendation : "completed";
    const sampled = payload.sampled_review ? " and sampled for human review" : "";
    return `Machine recommendation: ${formatLabel(recommendation)}${sampled}`;
  }
  if (event.event_type === "label_image_replaced") {
    const imageKey = typeof payload.image_key === "string" ? formatLabel(payload.image_key) : "Label";
    const filename = typeof payload.filename === "string" && payload.filename ? ` from ${payload.filename}` : "";
    return `${imageKey} image replaced${filename}; verification queued`;
  }
  if (event.event_type === "batch_created") {
    const count = typeof payload.total_count === "number" ? payload.total_count : null;
    return count === null ? "Batch queued" : `${count} cases queued for verification`;
  }
  if (event.event_type === "sampled_review_selected") {
    const reason = typeof payload.reason === "string" ? payload.reason : "sampling policy";
    return `Selected by ${reason}`;
  }
  if (event.event_type === "verification_failed") {
    return typeof payload.error === "string" ? payload.error : "Verification worker reported an error";
  }
  if (event.case?.issue_summary) return event.case.issue_summary;
  return "Recorded for traceability";
}

function formatModelProcessingTime(caseInfo: AuditEvent["case"]): string | null {
  if (!caseInfo) return null;
  const providerMs = caseInfo.provider_latency_ms;
  return typeof providerMs === "number" ? `Model ${formatDuration(providerMs)}` : null;
}
