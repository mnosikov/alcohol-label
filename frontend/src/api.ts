export type CaseSummary = {
  id: string;
  batch_id: string | null;
  source: string;
  status: string;
  current_recommendation: string | null;
  final_decision: string | null;
  issue_summary: string;
  application_fields: Record<string, string>;
  created_at: string;
};

export type FieldResult = {
  id: number;
  field_name: string;
  expected_value: string;
  extracted_value: string | null;
  verdict: string;
  confidence: number | null;
  rationale: string;
  source_layer: string;
  created_at: string;
};

export type TierEvent = {
  id: number;
  layer: string;
  decision: string;
  confidence: number | null;
  rationale: string;
  evidence: Record<string, unknown>;
  latency_ms: number;
  error: string | null;
  created_at: string;
};

export type CaseListResponse = {
  counts: Record<string, number>;
  items: CaseSummary[];
};

export type CaseDetailResponse = CaseSummary & {
  image_sha256: string;
  image_url: string;
  image_assets: Array<{
    key: string;
    label: string;
    image_url: string;
    sha256?: string;
  }>;
  final_note: string | null;
  tier_events: TierEvent[];
  field_results: FieldResult[];
  provider_usage: Array<Record<string, unknown>>;
  human_decisions: Array<Record<string, unknown>>;
  audit_events: AuditEvent[];
};

export type AuditEvent = {
  id: number;
  case_id: string | null;
  batch_id: string | null;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
  case?: {
    id: string;
    display_id: string;
    display_label: string;
    brand_name: string;
    status: string;
    issue_summary: string;
    provider_latency_ms?: number | null;
  };
};

export type BatchSummary = {
  id: string;
  filename: string;
  status: string;
  total_count: number;
  processed_count: number;
  error: string | null;
  created_at: string;
  import_summary?: BatchImportSummary | null;
};

export type BatchImportSummary = {
  selected_image_count: number;
  accepted_image_count: number;
  ignored_images: string[];
  inferred_back_images: Array<{
    filename: string;
    back_filename: string;
  }>;
  rejected_rows: Array<{
    row_number: number;
    filename: string;
    reason: string;
  }>;
};

export type BatchUploadResponse = {
  id: string;
  status: string;
  total_count: number;
  import_summary?: BatchImportSummary;
};

export type AppConfigResponse = {
  review_token_required: boolean;
};

export async function fetchAppConfig(): Promise<AppConfigResponse> {
  const response = await fetch("/api/config");
  if (!response.ok) throw new Error("Unable to load app configuration");
  return response.json();
}

export async function fetchCases(status?: string): Promise<CaseListResponse> {
  const suffix = status ? `?status_filter=${encodeURIComponent(status)}` : "";
  const response = await fetch(`/api/cases${suffix}`);
  if (!response.ok) throw new Error("Unable to load cases");
  return response.json();
}

export async function fetchCase(caseId: string): Promise<CaseDetailResponse> {
  const response = await fetch(`/api/cases/${caseId}`);
  if (!response.ok) throw new Error("Unable to load case");
  return response.json();
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail && typeof payload.detail === "object") {
      const message =
        typeof payload.detail.message === "string" ? payload.detail.message : fallback;
      const rejectedRows = Array.isArray(payload.detail.rejected_rows)
        ? payload.detail.rejected_rows
        : [];
      if (rejectedRows.length > 0) {
        return `${message}: ${formatRejectedRowsForError(rejectedRows)}`;
      }
      return message;
    }
  } catch {
    // Fall back to the generic action message below.
  }
  return fallback;
}

function formatRejectedRowsForError(rows: unknown[], limit = 4): string {
  const visible = rows
    .slice(0, limit)
    .map((row) => {
      if (!row || typeof row !== "object") return "Rejected row";
      const rowData = row as Record<string, unknown>;
      const rowNumber =
        typeof rowData.row_number === "number" ? `Row ${rowData.row_number}` : "Row";
      const filename = typeof rowData.filename === "string" && rowData.filename ? ` ${rowData.filename}` : "";
      const reason = typeof rowData.reason === "string" ? rowData.reason : "Not accepted";
      return `${rowNumber}${filename} - ${reason}`;
    })
    .join("; ");
  const hiddenCount = rows.length - limit;
  return hiddenCount > 0 ? `${visible}; +${hiddenCount} more` : visible;
}

export async function recordDecision(
  caseId: string,
  decision: string,
  note: string,
  reviewToken?: string,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (reviewToken) headers["X-Review-Token"] = reviewToken;
  const response = await fetch(`/api/cases/${caseId}/human-decision`, {
    method: "POST",
    headers,
    body: JSON.stringify({ decision, note, reviewer_label: "demo-agent" }),
  });
  if (response.status === 401) throw new Error("Review token required");
  if (!response.ok) throw new Error("Unable to record decision");
}

export async function queueVerification(caseId: string): Promise<void> {
  const response = await fetch(`/api/cases/${caseId}/verify`, { method: "POST" });
  if (!response.ok) throw new Error("Unable to queue verification");
}

export async function replaceCaseImage(
  caseId: string,
  imageKey: string,
  image: File,
  reviewToken?: string,
): Promise<CaseDetailResponse> {
  const formData = new FormData();
  formData.append("image_key", imageKey);
  formData.append("image", image);
  const headers: Record<string, string> = {};
  if (reviewToken) headers["X-Review-Token"] = reviewToken;
  const response = await fetch(`/api/cases/${caseId}/image`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (response.status === 401) throw new Error("Review token required");
  if (!response.ok) throw new Error(await errorMessage(response, "Unable to replace label image"));
  return response.json();
}

export async function uploadCase(formData: FormData): Promise<{ id: string }> {
  const response = await fetch("/api/cases", { method: "POST", body: formData });
  if (!response.ok) throw new Error(await errorMessage(response, "Unable to upload case"));
  return response.json();
}

export async function uploadBatch(formData: FormData): Promise<BatchUploadResponse> {
  const response = await fetch("/api/batches", { method: "POST", body: formData });
  if (!response.ok) throw new Error(await errorMessage(response, "Unable to upload batch"));
  return response.json();
}

export async function fetchBatches(): Promise<{ items: BatchSummary[] }> {
  const response = await fetch("/api/batches");
  if (!response.ok) throw new Error("Unable to load batches");
  return response.json();
}

export async function fetchAuditEvents(
  params: { limit?: number; offset?: number } = {},
): Promise<{ items: AuditEvent[]; total_count: number; limit: number; offset: number }> {
  const searchParams = new URLSearchParams();
  if (params.limit !== undefined) searchParams.set("limit", String(params.limit));
  if (params.offset !== undefined) searchParams.set("offset", String(params.offset));
  const suffix = searchParams.toString() ? `?${searchParams.toString()}` : "";
  const response = await fetch(`/api/audit-events${suffix}`);
  if (!response.ok) throw new Error("Unable to load audit events");
  return response.json();
}
