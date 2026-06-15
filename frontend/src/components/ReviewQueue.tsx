import { AlertCircle, CheckCircle2, Clock3, Search } from "lucide-react";
import { useMemo, useState } from "react";
import type { CaseSummary } from "../api";
import { formatLabel, statusTone } from "../format";

type Props = {
  cases: CaseSummary[];
  statusFilter: string | null;
  selectedCaseId: string | null;
  onSelect: (caseId: string) => void;
};

export default function ReviewQueue({
  cases,
  statusFilter,
  selectedCaseId,
  onSelect,
}: Props) {
  const [query, setQuery] = useState("");
  const visibleCases = useMemo(() => filterCases(cases, statusFilter, query), [cases, statusFilter, query]);

  return (
    <aside className="queue-pane">
      <div className="queue-header">
        <h1>Label Review Queue</h1>
        <div className="queue-search">
          <Search size={16} />
          <input
            id="queue-search"
            name="queue-search"
            aria-label="Search cases"
            autoComplete="off"
            placeholder="Search brand, status, or issue"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>
      <div className="case-list">
        {visibleCases.length === 0 ? <div className="case-list-empty">No matching cases.</div> : null}
        {visibleCases.map((item) => (
          <button
            className={`case-row ${item.id === selectedCaseId ? "is-selected" : ""}`}
            key={item.id}
            onClick={() => onSelect(item.id)}
          >
            <span className="case-icon">{iconForStatus(item.status)}</span>
            <span className="case-main">
              <strong>{item.application_fields.brand_name}</strong>
              <span>{item.application_fields.class_type}</span>
            </span>
            <span className="case-issue">{item.issue_summary}</span>
            <span className="case-status" data-tone={statusTone(item.status)}>
              {formatLabel(item.status)}
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function filterCases(cases: CaseSummary[], statusFilter: string | null, query: string) {
  const normalizedQuery = query.trim().toLowerCase();

  return cases.filter((item) => {
    if (statusFilter && item.status !== statusFilter) return false;
    if (!normalizedQuery) return true;

    const fieldValues = Object.values(item.application_fields).join(" ");
    return `${item.id} ${item.status} ${item.current_recommendation ?? ""} ${item.issue_summary} ${fieldValues}`
      .toLowerCase()
      .includes(normalizedQuery);
  });
}

function iconForStatus(status: string) {
  const tone = statusTone(status);
  if (tone === "fail") return <AlertCircle size={18} />;
  if (tone === "pass") return <CheckCircle2 size={18} />;
  return <Clock3 size={18} />;
}
