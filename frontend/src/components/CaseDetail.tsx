import { Check, RefreshCw, X } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import {
  fetchCase,
  queueVerification,
  recordDecision,
  replaceCaseImage,
  type CaseDetailResponse,
} from "../api";
import {
  caseDisplayIdentifier,
  formatDateTime,
  formatDuration,
  formatLabel,
  formatTopBadge,
  isVerificationActive,
  statusTone,
} from "../format";
import { eventSummary, formatEventType } from "./AuditHistory";
import FieldResultTable from "./FieldResultTable";
import LabelImageViewer from "./LabelImageViewer";

type Props = {
  caseId: string | null;
  onDecisionRecorded: () => void;
  reviewTokenRequired: boolean;
  uploadNotice?: string | null;
};

const APPLICATION_FIELD_ROWS = [
  ["brand_name", "Brand"],
  ["class_type", "Class/type"],
  ["alcohol_content", "Alcohol"],
  ["net_contents", "Net contents"],
  ["cola_id", "COLA ID"],
  ["fanciful_name", "Fanciful name"],
  ["serial_number", "Serial number"],
  ["source_of_product", "Source"],
  ["formula", "Formula"],
  ["grape_varietals", "Grape varietals"],
  ["wine_appellation", "Wine appellation"],
  ["applicant_name_address", "Applicant"],
  ["producer", "Producer"],
  ["country_of_origin", "Country"],
] as const;

export default function CaseDetail({
  caseId,
  onDecisionRecorded,
  reviewTokenRequired,
  uploadNotice,
}: Props) {
  const [detail, setDetail] = useState<CaseDetailResponse | null>(null);
  const [note, setNote] = useState("");
  const [reviewerToken, setReviewerToken] = useState(
    () => window.localStorage.getItem("labelReviewerToken") ?? "",
  );
  const [error, setError] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [imageReplaceError, setImageReplaceError] = useState<string | null>(null);
  const [isSubmittingDecision, setIsSubmittingDecision] = useState(false);

  useEffect(() => {
    if (!caseId) return;
    setError(null);
    setDetail(null);
    fetchCase(caseId).then(setDetail).catch((err: Error) => setError(err.message));
  }, [caseId]);

  useEffect(() => {
    window.localStorage.setItem("labelReviewerToken", reviewerToken);
  }, [reviewerToken]);

  useEffect(() => {
    if (!detail || !isVerificationActive(detail.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        const refreshed = await fetchCase(detail.id);
        setDetail(refreshed);
        onDecisionRecorded();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unable to refresh case");
      }
    }, 500);
    return () => window.clearTimeout(timer);
  }, [detail?.id, detail?.status, onDecisionRecorded]);

  if (!caseId) {
    return <section className="detail-pane empty-state">Select a case to review.</section>;
  }

  if (error) {
    return <section className="detail-pane empty-state">{error}</section>;
  }

  if (!detail) {
    return <section className="detail-pane empty-state">Loading case...</section>;
  }

  async function refresh() {
    if (!detail) return;
    const refreshed = await fetchCase(detail.id);
    setDetail(refreshed);
    onDecisionRecorded();
  }

  async function decide(decision: string) {
    if (!detail) return;
    setDecisionError(null);
    setIsSubmittingDecision(true);
    try {
      await recordDecision(detail.id, decision, note, reviewerToken.trim() || undefined);
      setNote("");
      await refresh();
    } catch (err) {
      setDecisionError(err instanceof Error ? err.message : "Unable to record decision");
    } finally {
      setIsSubmittingDecision(false);
    }
  }

  async function reprocess() {
    if (!detail) return;
    await queueVerification(detail.id);
    setDetail({
      ...detail,
      status: "queued",
      current_recommendation: null,
      tier_events: [],
      field_results: [],
      provider_usage: [],
    });
    onDecisionRecorded();
  }

  async function replaceActiveImage(imageKey: string, file: File) {
    if (!detail) return;
    setImageReplaceError(null);
    try {
      const updated = await replaceCaseImage(
        detail.id,
        imageKey,
        file,
        reviewerToken.trim() || undefined,
      );
      setDetail(updated);
      onDecisionRecorded();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to replace label image";
      setImageReplaceError(message);
      throw err;
    }
  }

  const displayedStatus = displayStatusForCase(detail);
  const shouldShowReviewerToken = reviewTokenRequired || decisionError === "Review token required";
  const applicationRows = APPLICATION_FIELD_ROWS.map(([fieldName, label]) => ({
    fieldName,
    label,
    value: detail.application_fields[fieldName],
  })).filter((row) => row.value);
  const modelProcessingMs = totalProviderLatencyMs(detail);

  return (
    <section className="detail-pane">
      <header className="detail-header">
        <div>
          <h2>{detail.application_fields.brand_name}</h2>
          <p>
            {caseDisplayIdentifier(detail)} · {detail.application_fields.class_type}
          </p>
        </div>
        <div className="header-actions">
          <span className="status-badge" data-tone={statusTone(displayedStatus)}>
            {formatTopBadge(displayedStatus)}
          </span>
          <button
            className="case-reprocess-button"
            disabled={isVerificationActive(detail.status)}
            title="Run automatic verification again"
            type="button"
            onClick={reprocess}
          >
            <RefreshCw size={16} />
            <span>Reprocess</span>
          </button>
        </div>
      </header>
      {uploadNotice ? <div className="review-notice">{uploadNotice}</div> : null}
      <div className="detail-grid">
        <div className="review-media-stack">
          <LabelImageViewer
            imageUrl={detail.image_url}
            images={detail.image_assets}
            onReplaceImage={replaceActiveImage}
            replaceDisabled={detail.status === "processing"}
            scanning={isVerificationActive(detail.status)}
          />
          {imageReplaceError ? <p className="inline-error">{imageReplaceError}</p> : null}
          <section className="review-side-panel">
            <h3>Verification Trail</h3>
            {modelProcessingMs > 0 ? <p className="verification-model-time">Model {formatDuration(modelProcessingMs)}</p> : null}
            <ol className="tier-list">
              {detail.tier_events.length === 0 ? (
                <li>No verification layers have run yet.</li>
              ) : (
                detail.tier_events.map((event) => (
                  <li key={event.id}>
                    <strong className="tier-list__layer">{formatLabel(event.layer)}</strong>
                    <span
                      className="status-badge status-badge--compact tier-list__decision"
                      data-tone={statusTone(event.decision)}
                    >
                      {formatLabel(event.decision)}
                    </span>
                    <span className="tier-list__confidence">{formatConfidence(event.confidence)}</span>
                    <p className="tier-list__rationale">{event.rationale}</p>
                  </li>
                ))
              )}
            </ol>
            <form className="decision-form" onSubmit={(event) => event.preventDefault()}>
              <div className="decision-command-row">
                <textarea
                  id="decision-note"
                  name="decision-note"
                  className="decision-note-input"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="Decision note"
                  aria-label="Decision note"
                  disabled={isSubmittingDecision}
                  rows={3}
                />
                <div className="decision-bar" aria-label="Review decision actions">
                  <button
                    type="button"
                    data-action="approve"
                    disabled={isSubmittingDecision}
                    onClick={() => decide("approved")}
                  >
                    <Check size={16} />
                    Approve
                  </button>
                  <button
                    type="button"
                    data-action="reject"
                    disabled={isSubmittingDecision}
                    onClick={() => decide("rejected")}
                  >
                    <X size={16} />
                    Reject
                  </button>
                  <button
                    type="button"
                    data-action="override"
                    disabled={isSubmittingDecision}
                    onClick={() => decide("override_approved")}
                  >
                    <RefreshCw size={16} />
                    Override
                  </button>
                </div>
              </div>
              {shouldShowReviewerToken ? (
                <div className="review-auth-row">
                  <input
                    id="reviewer-token"
                    name="reviewer-token"
                    type="password"
                    autoComplete="off"
                    value={reviewerToken}
                    onChange={(event) => setReviewerToken(event.target.value)}
                    placeholder="Reviewer token"
                    aria-label="Reviewer token"
                  />
                </div>
              ) : null}
              {decisionError ? <p className="inline-error">{decisionError}</p> : null}
            </form>
          </section>
        </div>
        <section className="evidence-panel">
          <div className="application-fields">
            <h3>Application</h3>
            <dl>
              {applicationRows.map((row) => (
                <Fragment key={row.fieldName}>
                  <dt>{row.label}</dt>
                  <dd>{row.value}</dd>
                </Fragment>
              ))}
              <dt>Status</dt>
              <dd>
                <span className="status-badge status-badge--compact" data-tone={statusTone(detail.status)}>
                  {formatLabel(detail.status)}
                </span>
              </dd>
            </dl>
          </div>
          <h3>Field Evidence</h3>
          <FieldResultTable rows={detail.field_results} />
          <section className="case-activity">
            <details>
              <summary>
                <span>Activity</span>
                <strong>{detail.audit_events.length}</strong>
              </summary>
              <div className="case-activity-list">
                {detail.audit_events.length === 0 ? (
                  <p>No activity recorded yet.</p>
                ) : (
                  detail.audit_events.map((event) => (
                    <article className="case-activity-row" key={event.id}>
                      <strong>{formatEventType(event.event_type)}</strong>
                      <span>{eventSummary(event)}</span>
                      <time>{formatDateTime(event.created_at)}</time>
                    </article>
                  ))
                )}
              </div>
            </details>
          </section>
        </section>
      </div>
    </section>
  );
}

function formatConfidence(value: number | null) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "n/a";
}

function displayStatusForCase(detail: CaseDetailResponse): string {
  if (isVerificationActive(detail.status)) return detail.status;
  if (detail.final_decision) return detail.status;
  if (
    detail.status === "approved" ||
    detail.status === "rejected" ||
    detail.status === "better_image_requested"
  ) {
    return detail.status;
  }
  return detail.current_recommendation ?? detail.status;
}

function totalProviderLatencyMs(detail: CaseDetailResponse): number {
  return detail.provider_usage.reduce((total, usage) => {
    const latency = usage.latency_ms;
    return total + (typeof latency === "number" ? latency : 0);
  }, 0);
}
