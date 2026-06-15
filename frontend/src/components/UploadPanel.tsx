import { FileText, Images, ImageUp } from "lucide-react";
import { useRef, useState, type ChangeEvent, type FocusEvent, type FormEvent } from "react";
import {
  fetchCase,
  uploadBatch,
  uploadCase,
  type BatchImportSummary,
  type CaseDetailResponse,
} from "../api";
import { formatLabel, isVerificationActive, statusTone } from "../format";

type Props = {
  completedBatchId?: string | null;
  onUploaded: () => void;
  onCaseUploaded?: (caseId: string) => void;
  onBatchUploaded?: (batchId: string) => void;
  onReviewBatch?: () => void;
};

type UploadMessage = {
  tone: "success" | "error" | "pending";
  text: string;
};

type CaseProcessingSummary = {
  id: string;
  state: "processing" | "completed" | "timeout" | "error";
  elapsedMs: number;
  status?: string;
  recommendation?: string | null;
  providerLatencyMs?: number;
  error?: string;
};

type BatchUploadSummary = {
  id: string;
  totalCount: number;
  importSummary?: BatchImportSummary;
};

type BatchDetailKey = "rear" | "ignored" | "rejected";

const REQUIRED_CASE_FIELDS = [
  ["brand_name", "Brand"],
  ["class_type", "Class/type"],
  ["alcohol_content", "Alcohol content"],
  ["net_contents", "Net contents"],
] as const;

const CASE_IMAGE_FIELDS = [
  ["front", "front_image", "Front label image", true],
  ["back", "back_image", "Back label image", false],
] as const;

const OPTIONAL_CASE_FIELDS = [
  ["cola_id", "COLA ID"],
  ["fanciful_name", "Fanciful name"],
  ["serial_number", "Serial number"],
  ["formula", "Formula"],
  ["grape_varietals", "Grape varietals"],
  ["wine_appellation", "Wine appellation"],
  ["producer", "Producer"],
] as const;

const PRODUCT_ORIGIN_OPTIONS = ["Domestic", "Imported"] as const;
const RESPONSIBLE_PARTY_FIELD = "applicant_name_address";
const PRODUCT_ORIGIN_FIELD = "source_of_product";
const COUNTRY_OF_ORIGIN_FIELD = "country_of_origin";

export default function UploadPanel({
  completedBatchId,
  onUploaded,
  onCaseUploaded,
  onBatchUploaded,
  onReviewBatch,
}: Props) {
  const [message, setMessage] = useState<UploadMessage | null>(null);
  const [activeTab, setActiveTab] = useState<"case" | "batch">("case");
  const [submitting, setSubmitting] = useState<"case" | "batch" | null>(null);
  const [caseProcessing, setCaseProcessing] = useState<CaseProcessingSummary | null>(null);
  const [batchUpload, setBatchUpload] = useState<BatchUploadSummary | null>(null);
  const [caseProductOrigin, setCaseProductOrigin] =
    useState<(typeof PRODUCT_ORIGIN_OPTIONS)[number]>("Domestic");
  const [caseImageNames, setCaseImageNames] = useState<Record<CaseImageKey, string>>({
    front: "",
    back: "",
  });
  const processingRunRef = useRef(0);

  async function submitCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const startedAt = performance.now();
    let formData: FormData;
    try {
      formData = buildCaseFormData(form);
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : "Please complete the case fields",
      });
      return;
    }

    setSubmitting("case");
    setCaseProcessing(null);
    setMessage({ tone: "pending", text: "Uploading case..." });
    try {
      const result = await uploadCase(formData);
      form.reset();
      setCaseProductOrigin("Domestic");
      setCaseImageNames({ front: "", back: "" });
      setMessage({ tone: "pending", text: `Case queued: ${result.id}` });
      const runId = processingRunRef.current + 1;
      processingRunRef.current = runId;
      setCaseProcessing({
        id: result.id,
        state: "processing",
        elapsedMs: performance.now() - startedAt,
      });
      if (onCaseUploaded) {
        onCaseUploaded(result.id);
      } else {
        onUploaded();
        void monitorCaseProcessing(result.id, startedAt, runId);
      }
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : "Unable to upload case",
      });
    } finally {
      setSubmitting(null);
    }
  }

  function handleCaseImageChange(imageKey: CaseImageKey, event: ChangeEvent<HTMLInputElement>) {
    const fileName = event.currentTarget.files?.[0]?.name ?? "";
    setCaseImageNames((current) => ({ ...current, [imageKey]: fileName }));
  }

  function normalizeAlcoholContentInput(event: FocusEvent<HTMLInputElement>) {
    event.currentTarget.value = normalizeCaseFieldValue(
      "alcohol_content",
      event.currentTarget.value.trim(),
    );
  }

  function handleProductOriginChange(event: ChangeEvent<HTMLSelectElement>) {
    const value = event.currentTarget.value;
    setCaseProductOrigin(value === "Imported" ? "Imported" : "Domestic");
  }

  async function monitorCaseProcessing(caseId: string, startedAt: number, runId: number) {
    for (let attempt = 0; attempt < 70; attempt += 1) {
      await delay(attempt === 0 ? 300 : 500);
      if (processingRunRef.current !== runId) return;

      try {
        const detail = await fetchCase(caseId);
        const elapsedMs = performance.now() - startedAt;
        const providerLatencyMs = totalProviderLatencyMs(detail);
        const summary: CaseProcessingSummary = {
          id: caseId,
          state: isVerificationActive(detail.status) ? "processing" : "completed",
          elapsedMs,
          status: detail.status,
          recommendation: detail.current_recommendation,
          providerLatencyMs,
        };
        setCaseProcessing(summary);

        if (!isVerificationActive(detail.status)) {
          setMessage({
            tone: "success",
            text: `Case processed in ${formatDuration(elapsedMs)}: ${formatLabel(detail.status)}`,
          });
          onUploaded();
          return;
        }
      } catch (err) {
        setCaseProcessing({
          id: caseId,
          state: "error",
          elapsedMs: performance.now() - startedAt,
          error: err instanceof Error ? err.message : "Unable to check processing time",
        });
        return;
      }
    }

    if (processingRunRef.current !== runId) return;
    setCaseProcessing((current) =>
      current
        ? {
            ...current,
            state: "timeout",
            elapsedMs: performance.now() - startedAt,
          }
        : null,
    );
  }

  async function submitBatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    let formData: FormData;
    try {
      formData = buildBatchFormData(form);
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : "Please select the batch files",
      });
      return;
    }

    setSubmitting("batch");
    setBatchUpload(null);
    setMessage({ tone: "pending", text: "Uploading batch..." });
    try {
      const result = await uploadBatch(formData);
      const importSummary = result.import_summary;
      const ignoredCount = importSummary?.ignored_images.length ?? 0;
      const attachedBackCount = importSummary?.inferred_back_images.length ?? 0;
      const rejectedCount = importSummary?.rejected_rows.length ?? 0;
      form.reset();
      setBatchUpload({
        id: result.id,
        totalCount: result.total_count,
        importSummary,
      });
      setMessage({
        tone: "success",
        text: batchUploadMessage(result.total_count, ignoredCount, attachedBackCount, rejectedCount),
      });
      onUploaded();
      onBatchUploaded?.(result.id);
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : "Unable to upload batch",
      });
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <section className="tool-pane">
      <header className="tool-header">
        <h2>Upload</h2>
        <p>Demo data only. Do not upload sensitive real applications.</p>
      </header>
      <div className="tool-content-narrow">
        {message ? (
          <div
            className="inline-status"
            data-tone={message.tone}
            role={message.tone === "error" ? "alert" : "status"}
          >
            {message.text}
          </div>
        ) : null}
        <div className="upload-grid">
          <div className="upload-tabs" role="tablist" aria-label="Upload mode">
            <button
              type="button"
              className={activeTab === "case" ? "is-active" : ""}
              aria-selected={activeTab === "case"}
              onClick={() => setActiveTab("case")}
            >
              Single case
            </button>
            <button
              type="button"
              className={activeTab === "batch" ? "is-active" : ""}
              aria-selected={activeTab === "batch"}
              onClick={() => setActiveTab("batch")}
            >
              Batch upload
            </button>
          </div>
          <div className="upload-tab-panel">
            {activeTab === "case" ? (
              <form className="upload-form" onSubmit={submitCase}>
                <h3>Single case</h3>
                <div className="upload-form-grid upload-form-grid--images">
                  {CASE_IMAGE_FIELDS.map(([imageKey, fieldName, label, required]) => (
                    <CaseImageUploadField
                      fileName={caseImageNames[imageKey]}
                      imageKey={imageKey}
                      key={imageKey}
                      label={label}
                      name={fieldName}
                      onChange={handleCaseImageChange}
                      required={required}
                    />
                  ))}
                </div>
                <div className="upload-form-grid">
                  {REQUIRED_CASE_FIELDS.map(([fieldName, label]) => (
                    <label key={fieldName}>
                      {label}
                      <input
                        name={fieldName}
                        required
                        inputMode={fieldName === "alcohol_content" ? "decimal" : undefined}
                        onBlur={
                          fieldName === "alcohol_content"
                            ? normalizeAlcoholContentInput
                            : undefined
                        }
                      />
                    </label>
                  ))}
                </div>
                <section className="upload-form-section">
                  <h4>Responsible Party Name and Address</h4>
                  <div className="upload-form-grid">
                    <label className="upload-form-grid__wide">
                      Name and address
                      <input
                        name={RESPONSIBLE_PARTY_FIELD}
                        placeholder="Name, city, state"
                        required
                      />
                    </label>
                    <label>
                      Product origin
                      <select
                        name={PRODUCT_ORIGIN_FIELD}
                        onChange={handleProductOriginChange}
                        required
                        value={caseProductOrigin}
                      >
                        {PRODUCT_ORIGIN_OPTIONS.map((origin) => (
                          <option key={origin} value={origin}>
                            {origin}
                          </option>
                        ))}
                      </select>
                    </label>
                    {caseProductOrigin === "Imported" ? (
                      <label>
                        Country of origin
                        <input name={COUNTRY_OF_ORIGIN_FIELD} required />
                      </label>
                    ) : null}
                  </div>
                </section>
                <h4>Optional fields</h4>
                <div className="upload-form-grid">
                  {OPTIONAL_CASE_FIELDS.map(([fieldName, label]) => (
                    <label key={fieldName}>
                      {label}
                      <input name={fieldName} />
                    </label>
                  ))}
                </div>
                <button type="submit" disabled={submitting !== null}>
                  <ImageUp size={16} />
                  {submitting === "case" ? "Uploading..." : "Upload case"}
                </button>
                {submitting === "case" && !caseProcessing ? (
                  <UploadScanCard
                    detail="Preparing automatic verification"
                    title="Uploading label"
                  />
                ) : null}
                {caseProcessing ? <CaseProcessingSummaryCard summary={caseProcessing} /> : null}
              </form>
            ) : (
              <form className="upload-form" onSubmit={submitBatch}>
                <div className="upload-form-heading">
                  <h3>Batch upload</h3>
                  <a
                    className="upload-template-link"
                    href="/batch-upload-template.csv"
                    download="batch-upload-template.csv"
                  >
                    <FileText size={14} />
                    Download manifest template
                  </a>
                </div>
                <div className="upload-file-grid">
                  <label className="upload-file-box">
                    <FileText size={18} />
                    <span>CSV manifest</span>
                    <input name="manifest" type="file" accept=".csv,text/csv" required />
                  </label>
                  <label className="upload-file-box">
                    <Images size={18} />
                    <span>Label image files</span>
                    <input
                      name="images"
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      multiple
                      required
                    />
                  </label>
                </div>
                <button type="submit" disabled={submitting !== null}>
                  <ImageUp size={16} />
                  {submitting === "batch" ? "Uploading..." : "Upload batch"}
                </button>
                {submitting === "batch" && !batchUpload ? (
                  <UploadScanCard
                    detail="Checking manifest rows and selected images"
                    title="Reading batch"
                  />
                ) : null}
                {batchUpload ? (
                  <BatchUploadSummaryCard
                    isComplete={completedBatchId === batchUpload.id}
                    onReviewBatch={onReviewBatch}
                    summary={batchUpload}
                  />
                ) : null}
              </form>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

type CaseImageKey = (typeof CASE_IMAGE_FIELDS)[number][0];

type CaseImageUploadFieldProps = {
  fileName: string;
  imageKey: CaseImageKey;
  label: string;
  name: string;
  onChange: (imageKey: CaseImageKey, event: ChangeEvent<HTMLInputElement>) => void;
  required: boolean;
};

function CaseImageUploadField({
  fileName,
  imageKey,
  label,
  name,
  onChange,
  required,
}: CaseImageUploadFieldProps) {
  return (
    <div className="upload-image-field">
      <div className="upload-image-field__header">
        <span>{label}</span>
        <small>{required ? "Required" : "Optional"}</small>
      </div>
      <label className="image-action-button">
        <ImageUp size={15} />
        Add image
        <input
          name={name}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          required={required}
          onChange={(event) => onChange(imageKey, event)}
        />
      </label>
      <span className={fileName ? "upload-image-field__filename" : "upload-image-field__empty"}>
        {fileName || "No image selected"}
      </span>
    </div>
  );
}

function UploadScanCard({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="upload-scan-card" role="status">
      <div className="upload-scan-window" aria-hidden="true" />
      <div>
        <span>{title}</span>
        <strong>{detail}</strong>
      </div>
    </div>
  );
}

function CaseProcessingSummaryCard({ summary }: { summary: CaseProcessingSummary }) {
  const tone =
    summary.state === "completed"
      ? statusTone(summary.status)
      : summary.state === "error"
        ? "error"
        : "pending";
  const title =
    summary.state === "completed"
      ? "Processed"
      : summary.state === "timeout"
        ? "Still processing"
        : summary.state === "error"
          ? "Timing unavailable"
          : "Processing";
  const detail =
    summary.state === "completed"
      ? formatLabel(summary.status)
      : summary.state === "timeout"
        ? "Worker has not finished yet"
        : summary.state === "error"
          ? summary.error
          : "Waiting for automatic verification";

  return (
    <div
      className="upload-processing-summary"
      data-scanning={summary.state === "processing" ? "true" : undefined}
      data-tone={tone}
    >
      <div>
        <span>{title}</span>
        <strong>{formatDuration(summary.elapsedMs)}</strong>
      </div>
      <p>
        Case {summary.id.slice(0, 8)}
        {detail ? ` - ${detail}` : ""}
        {summary.recommendation ? ` - ${formatLabel(summary.recommendation)}` : ""}
        {summary.providerLatencyMs ? ` - Model ${formatDuration(summary.providerLatencyMs)}` : ""}
      </p>
    </div>
  );
}

function BatchUploadSummaryCard({
  isComplete,
  onReviewBatch,
  summary,
}: {
  isComplete: boolean;
  onReviewBatch?: () => void;
  summary: BatchUploadSummary;
}) {
  const importSummary = summary.importSummary;
  const ignoredImages = importSummary?.ignored_images ?? [];
  const inferredBackImages = importSummary?.inferred_back_images ?? [];
  const rejectedRows = importSummary?.rejected_rows ?? [];
  const [openDetail, setOpenDetail] = useState<BatchDetailKey | null>(null);
  const hasImportDetails =
    inferredBackImages.length > 0 || ignoredImages.length > 0 || rejectedRows.length > 0;

  function toggleDetail(detail: BatchDetailKey) {
    setOpenDetail((current) => (current === detail ? null : detail));
  }

  return (
    <div className="upload-processing-summary" data-tone={isComplete ? "pass" : "pending"}>
      <div>
        <span>{isComplete ? "Batch complete" : "Batch queued"}</span>
        <strong>{summary.totalCount} cases</strong>
      </div>
      {importSummary ? (
        <dl className="batch-import-metrics">
          <div>
            <dt>Selected</dt>
            <dd>{importSummary.selected_image_count}</dd>
          </div>
          <div>
            <dt>Accepted</dt>
            <dd>{importSummary.accepted_image_count}</dd>
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
      ) : null}
      <p>
        Batch {summary.id.slice(0, 8)}{" "}
        {isComplete
          ? "has finished automatic verification. Review the machine results now."
          : "is queued for automatic verification. Live progress updates in the Batches panel below."}
      </p>
      {isComplete && onReviewBatch ? (
        <button className="batch-review-button" type="button" onClick={onReviewBatch}>
          Go to review
        </button>
      ) : null}
      {hasImportDetails ? (
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
  const disabled = count === 0;
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {disabled ? (
          <span>{count}</span>
        ) : (
          <button
            aria-label={`${label}: ${count}`}
            aria-expanded={isOpen}
            className="batch-metric-button"
            onClick={onClick}
            type="button"
          >
            {count}
          </button>
        )}
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

function batchUploadMessage(
  totalCount: number,
  ignoredCount: number,
  attachedBackCount: number,
  rejectedCount: number,
): string {
  const details = [];
  if (attachedBackCount > 0) {
    details.push(`${attachedBackCount} rear label${attachedBackCount === 1 ? "" : "s"} attached`);
  }
  if (ignoredCount > 0) {
    details.push(`${ignoredCount} extra file${ignoredCount === 1 ? "" : "s"} ignored`);
  }
  if (rejectedCount > 0) {
    details.push(`${rejectedCount} row${rejectedCount === 1 ? "" : "s"} rejected`);
  }
  const suffix = details.length > 0 ? ` ${details.join("; ")}.` : "";
  return `Batch queued: ${totalCount} cases.${suffix} Verification is running in the background.`;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function totalProviderLatencyMs(detail: CaseDetailResponse): number {
  return detail.provider_usage.reduce((total, usage) => {
    const latency = usage.latency_ms;
    return total + (typeof latency === "number" ? latency : 0);
  }, 0);
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;
}

function buildCaseFormData(form: HTMLFormElement): FormData {
  const formData = new FormData(form);
  const frontImage = formData.get("front_image");
  if (!(frontImage instanceof File) || frontImage.size === 0) {
    throw new Error("Front label image is required");
  }
  const backImage = formData.get("back_image");
  if (backImage instanceof File && backImage.size === 0) {
    formData.delete("back_image");
  }
  for (const [fieldName, label] of REQUIRED_CASE_FIELDS) {
    const rawValue = formData.get(fieldName);
    const value = typeof rawValue === "string" ? rawValue.trim() : "";
    if (!value) {
      throw new Error(`${label} is required`);
    }
    formData.set(fieldName, normalizeCaseFieldValue(fieldName, value));
  }
  const responsibleParty = textFormValue(formData, RESPONSIBLE_PARTY_FIELD);
  if (!responsibleParty) {
    throw new Error("Responsible party name/address is required");
  }
  if (!containsUsState(responsibleParty)) {
    throw new Error("Responsible party name/address must include at least a U.S. state");
  }
  formData.set(RESPONSIBLE_PARTY_FIELD, responsibleParty);

  const productOrigin = textFormValue(formData, PRODUCT_ORIGIN_FIELD);
  if (!PRODUCT_ORIGIN_OPTIONS.some((origin) => origin === productOrigin)) {
    throw new Error("Product origin must be Domestic or Imported");
  }
  formData.set(PRODUCT_ORIGIN_FIELD, productOrigin);

  const countryOfOrigin = textFormValue(formData, COUNTRY_OF_ORIGIN_FIELD);
  if (productOrigin === "Imported") {
    if (!countryOfOrigin) {
      throw new Error("Country of origin is required for imported products");
    }
    formData.set(COUNTRY_OF_ORIGIN_FIELD, countryOfOrigin);
  } else if (countryOfOrigin) {
    formData.set(COUNTRY_OF_ORIGIN_FIELD, countryOfOrigin);
  } else {
    formData.delete(COUNTRY_OF_ORIGIN_FIELD);
  }

  for (const [fieldName] of OPTIONAL_CASE_FIELDS) {
    const rawValue = formData.get(fieldName);
    const value = typeof rawValue === "string" ? rawValue.trim() : "";
    if (value) {
      formData.set(fieldName, value);
    } else {
      formData.delete(fieldName);
    }
  }
  return formData;
}

function normalizeCaseFieldValue(fieldName: string, value: string): string {
  if (fieldName === "alcohol_content" && /^\d+(?:\.\d+)?$/.test(value)) {
    return `${value}%`;
  }
  return value;
}

function textFormValue(formData: FormData, fieldName: string): string {
  const rawValue = formData.get(fieldName);
  return typeof rawValue === "string" ? rawValue.trim() : "";
}

function containsUsState(value: string): boolean {
  const stateAbbreviations = new Set([
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "DC",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "PR",
    "VI",
    "GU",
  ]);
  const stateNames = [
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "district of columbia",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
    "puerto rico",
    "virgin islands",
    "guam",
  ];
  const abbreviationMatches = value.toUpperCase().match(/\b[A-Z]{2}\b/g) ?? [];
  if (abbreviationMatches.some((abbreviation) => stateAbbreviations.has(abbreviation))) {
    return true;
  }
  const lowerValue = value.toLowerCase();
  return stateNames.some((stateName) =>
    new RegExp(`\\b${escapeRegExp(stateName)}\\b`).test(lowerValue),
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function buildBatchFormData(form: HTMLFormElement): FormData {
  const formData = new FormData(form);
  const manifest = formData.get("manifest");
  if (!(manifest instanceof File) || manifest.size === 0) {
    throw new Error("CSV manifest is required");
  }

  const images = formData
    .getAll("images")
    .filter((value): value is File => value instanceof File && value.size > 0);
  if (images.length === 0) {
    throw new Error("Select at least one label image file");
  }

  formData.delete("images");
  for (const image of images) {
    formData.append("images", image);
  }
  return formData;
}
