import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchBatches, type BatchImportSummary, type BatchSummary } from "../api";
import { formatDateTime, formatLabel, statusTone } from "../format";

type Props = {
  highlightedBatchId?: string | null;
  onHighlightedBatchComplete?: (batchId: string) => void;
  onReviewBatch?: (batchId: string) => void;
  refreshKey?: number;
};

const ACTIVE_BATCH_STATUSES = new Set(["queued", "processing"]);
type BatchDetailKey = "ignored" | "rejected" | "rear";

export default function BatchMonitor({
  highlightedBatchId,
  onHighlightedBatchComplete,
  onReviewBatch,
  refreshKey = 0,
}: Props) {
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [expandedBatchId, setExpandedBatchId] = useState<string | null>(null);

  const hasActiveBatch = batches.some((batch) => isActiveBatch(batch));
  const featuredBatch = useMemo(
    () =>
      batches.find((batch) => batch.id === highlightedBatchId) ??
      batches.find((batch) => isActiveBatch(batch)) ??
      batches[0] ??
      null,
    [batches, highlightedBatchId],
  );
  const displayedBatches = useMemo(
    () => batches.filter((batch) => batch.id !== featuredBatch?.id),
    [batches, featuredBatch?.id],
  );

  const refresh = useCallback(async (showBusy = false) => {
    if (showBusy) setIsRefreshing(true);
    setRefreshError(null);
    try {
      const response = await fetchBatches();
      setBatches(response.items);
      setLastUpdatedAt(new Date().toISOString());
    } catch {
      setRefreshError("Batch progress could not be refreshed.");
    } finally {
      if (showBusy) setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (highlightedBatchId) setExpandedBatchId(highlightedBatchId);
  }, [highlightedBatchId]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshKey]);

  useEffect(() => {
    const intervalMs = hasActiveBatch ? 3000 : 10000;
    const intervalId = window.setInterval(() => {
      void refresh();
    }, intervalMs);
    return () => window.clearInterval(intervalId);
  }, [hasActiveBatch, refresh]);

  useEffect(() => {
    if (
      highlightedBatchId &&
      featuredBatch?.id === highlightedBatchId &&
      featuredBatch.status === "completed"
    ) {
      onHighlightedBatchComplete?.(highlightedBatchId);
    }
  }, [featuredBatch, highlightedBatchId, onHighlightedBatchComplete]);

  return (
    <section className="tool-pane">
      <div className="tool-content-narrow">
        <header className="tool-header row-header">
          <div>
            <h2>Batches</h2>
            <p>
              {batches.length} batch uploads
              {hasActiveBatch ? " - auto-refreshing active work" : ""}
            </p>
          </div>
          <div className="batch-monitor-controls">
            {refreshError ? (
              <span className="batch-refresh-status" data-tone="error">
                {refreshError}
              </span>
            ) : lastUpdatedAt ? (
              <span className="batch-refresh-status">Updated {formatDateTime(lastUpdatedAt)}</span>
            ) : null}
            <button
              className={`batch-refresh-button ${isRefreshing ? "is-loading" : ""}`}
              type="button"
              title="Refresh batch progress"
              disabled={isRefreshing}
              onClick={() => void refresh(true)}
            >
              <RefreshCw size={16} />
              <span>{isRefreshing ? "Refreshing..." : "Refresh progress"}</span>
            </button>
          </div>
        </header>
        {featuredBatch ? (
          <BatchProgressCallout batch={featuredBatch} onReviewBatch={onReviewBatch} />
        ) : null}
        <div className="batch-list">
          {batches.length === 0 ? (
            <div className="field-evidence-empty">No batch uploads recorded yet.</div>
          ) : null}
          {displayedBatches.map((batch) => (
            <BatchProgressRow
              batch={batch}
              isExpanded={expandedBatchId === batch.id}
              isHighlighted={batch.id === highlightedBatchId}
              key={batch.id}
              onToggle={() =>
                setExpandedBatchId((current) => (current === batch.id ? null : batch.id))
              }
            />
          ))}
        </div>
      </div>
    </section>
  );
}

function BatchProgressCallout({
  batch,
  onReviewBatch,
}: {
  batch: BatchSummary;
  onReviewBatch?: (batchId: string) => void;
}) {
  const isActive = isActiveBatch(batch);
  const isComplete = batch.status === "completed";
  return (
    <div className="batch-progress-callout" data-status={batch.status}>
      <div className="batch-progress-callout__header">
        <span>{isActive ? "Processing batch" : isComplete ? "Batch complete" : "Batch issue"}</span>
        <strong>{formatProgressPercent(batch)}%</strong>
      </div>
      <progress
        aria-label={`${batchDisplayName(batch)} progress`}
        value={batch.processed_count}
        max={Math.max(batch.total_count, 1)}
      />
      <p>
        {batchDisplayName(batch)} - {batchProgressText(batch)}. Source file: {batch.filename}.
        {isActive
          ? " The worker is verifying these cases in the background."
          : isComplete
            ? " Automatic verification has finished."
            : " This batch needs attention."}
      </p>
      {isComplete && onReviewBatch ? (
        <button className="batch-review-button" type="button" onClick={() => onReviewBatch(batch.id)}>
          Go to review
        </button>
      ) : null}
    </div>
  );
}

function BatchProgressRow({
  batch,
  isExpanded,
  isHighlighted,
  onToggle,
}: {
  batch: BatchSummary;
  isExpanded: boolean;
  isHighlighted: boolean;
  onToggle: () => void;
}) {
  const importSummary = batch.import_summary ?? null;
  return (
    <article
      className={`batch-row ${isHighlighted ? "is-highlighted" : ""}`}
      data-status={batch.status}
    >
      <div className="batch-row-main">
        <strong>{batchDisplayName(batch)}</strong>
        {importSummary ? (
          <span>{batchImportSummaryText(importSummary)}</span>
        ) : (
          <span>Import details unavailable for this batch</span>
        )}
      </div>
      <span className="status-badge status-badge--compact" data-tone={statusTone(batch.status)}>
        {formatLabel(batch.status)}
      </span>
      <progress
        aria-label={`${batchDisplayName(batch)} progress`}
        value={batch.processed_count}
        max={Math.max(batch.total_count, 1)}
      />
      <small>{batchProgressText(batch)}</small>
      <small className="batch-row-source">Source file: {batch.filename}</small>
      {importSummary ? (
        <button
          className="batch-details-toggle"
          type="button"
          aria-expanded={isExpanded}
          onClick={onToggle}
        >
          {isExpanded ? "Hide details" : "Details"}
        </button>
      ) : null}
      {batch.error ? <p>{batch.error}</p> : null}
      {importSummary && isExpanded ? <BatchImportDetails summary={importSummary} /> : null}
    </article>
  );
}

function BatchImportDetails({ summary }: { summary: BatchImportSummary }) {
  const [openDetail, setOpenDetail] = useState<BatchDetailKey | null>(null);
  const ignoredImages = summary.ignored_images ?? [];
  const rejectedRows = summary.rejected_rows ?? [];
  const inferredBackImages = summary.inferred_back_images ?? [];
  const hasDetails =
    ignoredImages.length > 0 || rejectedRows.length > 0 || inferredBackImages.length > 0;

  function toggleDetail(detail: BatchDetailKey) {
    setOpenDetail((current) => (current === detail ? null : detail));
  }

  return (
    <div className="batch-import-detail">
      <dl className="batch-import-metrics">
        <div>
          <dt>Selected</dt>
          <dd>{summary.selected_image_count}</dd>
        </div>
        <div>
          <dt>Used images</dt>
          <dd>{summary.accepted_image_count}</dd>
        </div>
        <BatchMetricButton
          count={inferredBackImages.length}
          isOpen={openDetail === "rear"}
          label="Rear labels"
          onClick={() => toggleDetail("rear")}
        />
        <BatchMetricButton
          count={ignoredImages.length}
          isOpen={openDetail === "ignored"}
          label="Ignored"
          onClick={() => toggleDetail("ignored")}
        />
        <BatchMetricButton
          count={rejectedRows.length}
          isOpen={openDetail === "rejected"}
          label="Rejected"
          onClick={() => toggleDetail("rejected")}
        />
      </dl>
      <p>
        Ignored files were selected for upload but not used by an accepted case. Files from
        rejected manifest rows are also ignored.
      </p>
      {hasDetails ? (
        <BatchDetailPanel
          ignoredImages={ignoredImages}
          inferredBackImages={inferredBackImages}
          openDetail={openDetail}
          rejectedRows={rejectedRows}
        />
      ) : null}
    </div>
  );
}

function BatchMetricButton({
  count,
  isOpen,
  label,
  onClick,
}: {
  count: number;
  isOpen: boolean;
  label: string;
  onClick: () => void;
}) {
  if (count === 0) {
    return (
      <div>
        <dt>{label}</dt>
        <dd>
          <span>{count}</span>
        </dd>
      </div>
    );
  }

  return (
    <div>
      <dt>{label}</dt>
      <dd>
        <button
          aria-label={`${label}: ${count}`}
          aria-expanded={isOpen}
          className="batch-metric-button"
          onClick={onClick}
          type="button"
        >
          {count}
        </button>
      </dd>
    </div>
  );
}

function BatchDetailPanel({
  ignoredImages,
  inferredBackImages,
  openDetail,
  rejectedRows,
}: {
  ignoredImages: string[];
  inferredBackImages: BatchImportSummary["inferred_back_images"];
  openDetail: BatchDetailKey | null;
  rejectedRows: BatchImportSummary["rejected_rows"];
}) {
  if (openDetail === "ignored") {
    return (
      <section className="batch-detail-panel" aria-label="Ignored image files">
        <h4>Ignored files</h4>
        <ul>
          {ignoredImages.map((filename) => (
            <li key={filename}>{filename}</li>
          ))}
        </ul>
      </section>
    );
  }

  if (openDetail === "rejected") {
    return (
      <section className="batch-detail-panel" aria-label="Rejected manifest rows">
        <h4>Rejected rows</h4>
        <ul>
          {rejectedRows.map((item) => (
            <li key={`${item.row_number}-${item.filename}-${item.reason}`}>
              <strong>
                Row {item.row_number}
                {item.filename ? ` - ${item.filename}` : ""}
              </strong>
              <span>{item.reason}</span>
            </li>
          ))}
        </ul>
      </section>
    );
  }

  if (openDetail === "rear") {
    return (
      <section className="batch-detail-panel" aria-label="Attached rear labels">
        <h4>Attached rear labels</h4>
        <ul>
          {inferredBackImages.map((item) => (
            <li key={`${item.filename}-${item.back_filename}`}>
              <strong>{item.filename}</strong>
              <span>{item.back_filename}</span>
            </li>
          ))}
        </ul>
      </section>
    );
  }

  return null;
}

function batchDisplayName(batch: BatchSummary): string {
  const caseLabel = batch.total_count === 1 ? "case" : "cases";
  return `Batch ${formatDateTime(batch.created_at)} - ${batch.total_count} ${caseLabel}`;
}

function batchProgressText(batch: BatchSummary): string {
  return `${batch.processed_count} of ${batch.total_count} cases processed`;
}

function batchImportSummaryText(summary: BatchImportSummary): string {
  const ignoredCount = summary.ignored_images.length;
  const rejectedCount = summary.rejected_rows.length;
  const rearCount = summary.inferred_back_images.length;
  const parts = [
    `${summary.selected_image_count} selected`,
    `${summary.accepted_image_count} used`,
  ];
  if (ignoredCount > 0) parts.push(`${ignoredCount} ignored`);
  if (rejectedCount > 0) parts.push(`${rejectedCount} rejected rows`);
  if (rearCount > 0) parts.push(`${rearCount} rear attached`);
  return parts.join(" · ");
}

function formatProgressPercent(batch: BatchSummary): number {
  if (batch.total_count <= 0) return 0;
  return Math.min(100, Math.round((batch.processed_count / batch.total_count) * 100));
}

function isActiveBatch(batch: BatchSummary): boolean {
  return ACTIVE_BATCH_STATUSES.has(batch.status);
}
