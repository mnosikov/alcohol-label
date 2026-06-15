export function formatLabel(value: string | null | undefined): string {
  if (!value) return "Pending";

  const normalized = value.trim();
  const upper = normalized.toUpperCase();
  if (upper === "PASS" || upper === "FAIL") return upper;

  return normalized
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatTopBadge(value: string | null | undefined): string {
  if (!value) return "Pending";

  const upper = value.trim().toUpperCase();
  if (upper === "PASS" || upper === "FAIL" || upper === "NEEDS_REVIEW") {
    return upper.replaceAll("_", " ");
  }

  return formatLabel(value);
}

export function statusTone(value: string | null | undefined): string {
  if (!value) return "pending";

  const normalized = value.toLowerCase();
  if (normalized === "pass" || normalized === "machine_passed" || normalized === "approved") {
    return "pass";
  }
  if (
    normalized === "fail" ||
    normalized === "machine_failed" ||
    normalized === "rejected" ||
    normalized === "override_rejected" ||
    normalized === "error"
  ) {
    return "fail";
  }
  if (
    normalized === "needs_review" ||
    normalized === "better_image_requested" ||
    normalized === "override_approved"
  ) {
    return "review";
  }
  return "pending";
}

export function isVerificationActive(status: string | null | undefined): boolean {
  return status === "queued" || status === "processing";
}

export function shortId(value: string): string {
  return value.slice(0, 8);
}

export function caseDisplayIdentifier(caseLike: {
  id: string;
  application_fields: Record<string, string>;
}): string {
  const fields = caseLike.application_fields;
  const identifier = fields.cola_id || fields.ttb_id || fields.serial_number;
  return identifier ? `COLA ${identifier}` : `Case ${shortId(caseLike.id)}`;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;
}
