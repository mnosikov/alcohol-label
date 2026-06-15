import { useEffect, useState } from "react";
import { fetchAppConfig, fetchCases, type CaseSummary } from "./api";
import AuditHistory from "./components/AuditHistory";
import BatchMonitor from "./components/BatchMonitor";
import CaseDetail from "./components/CaseDetail";
import ReviewQueue from "./components/ReviewQueue";
import UploadPanel from "./components/UploadPanel";
import { formatLabel, statusTone } from "./format";

type Tab = "queue" | "upload" | "activity";

const queueStatusFilters = [
  "queued",
  "processing",
  "needs_review",
  "machine_passed",
  "machine_failed",
  "approved",
  "rejected",
];

export default function App() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [reviewTokenRequired, setReviewTokenRequired] = useState(false);
  const [tab, setTab] = useState<Tab>("queue");
  const [uploadedCaseId, setUploadedCaseId] = useState<string | null>(null);
  const [uploadedBatchId, setUploadedBatchId] = useState<string | null>(null);
  const [completedBatchId, setCompletedBatchId] = useState<string | null>(null);
  const [batchRefreshKey, setBatchRefreshKey] = useState(0);

  async function refreshCases(filter = statusFilter, preferredCaseId?: string) {
    const response = await fetchCases(filter ?? undefined);
    setCases(response.items);
    setCounts(response.counts);
    setSelectedCaseId((current) => {
      if (preferredCaseId && response.items.some((item) => item.id === preferredCaseId)) {
        return preferredCaseId;
      }
      if (current && response.items.some((item) => item.id === current)) return current;
      return response.items[0]?.id ?? null;
    });
  }

  useEffect(() => {
    refreshCases(statusFilter);
  }, [statusFilter]);

  useEffect(() => {
    const activeCaseCount = (counts.queued ?? 0) + (counts.processing ?? 0);
    if (activeCaseCount === 0) return;

    const intervalId = window.setInterval(() => {
      void refreshCases(statusFilter);
    }, 3000);
    return () => window.clearInterval(intervalId);
  }, [counts.queued, counts.processing, statusFilter]);

  useEffect(() => {
    fetchAppConfig()
      .then((config) => setReviewTokenRequired(config.review_token_required))
      .catch(() => setReviewTokenRequired(false));
  }, []);

  function toggleStatusFilter(status: string) {
    const nextStatus = statusFilter === status ? null : status;
    setStatusFilter(nextStatus);
    setUploadedCaseId(null);

    if (!nextStatus) return;
    const nextCases = cases.filter((item) => item.status === nextStatus);
    if (nextCases.length > 0 && !nextCases.some((item) => item.id === selectedCaseId)) {
      setSelectedCaseId(nextCases[0].id);
    }
  }

  function openCaseFromActivity(caseId: string) {
    setStatusFilter(null);
    setSelectedCaseId(caseId);
    setUploadedCaseId(null);
    setTab("queue");
  }

  function openUploadedCase(caseId: string) {
    setStatusFilter(null);
    setSelectedCaseId(caseId);
    setUploadedCaseId(caseId);
    setTab("queue");
    void refreshCases(null, caseId);
  }

  function openBatchFromActivity() {
    setTab("upload");
  }

  function openUploadedBatch(batchId: string) {
    setUploadedBatchId(batchId);
    setCompletedBatchId(null);
    setBatchRefreshKey((current) => current + 1);
    void refreshCases(null);
  }

  function reviewUploadedBatch() {
    setStatusFilter(null);
    setUploadedCaseId(null);
    setTab("queue");
    void refreshCases(null);
  }

  function selectTab(nextTab: Tab) {
    setTab(nextTab);
    if (nextTab === "queue") {
      setStatusFilter(null);
      setUploadedCaseId(null);
      void refreshCases(null);
    }
  }

  const content =
    tab === "queue" ? (
      <>
        <StatusStrip counts={counts} statusFilter={statusFilter} onToggle={toggleStatusFilter} />
        <div className="app-shell">
          <ReviewQueue
            cases={cases}
            statusFilter={statusFilter}
            selectedCaseId={selectedCaseId}
            onSelect={(caseId) => {
              setSelectedCaseId(caseId);
              setUploadedCaseId(null);
            }}
          />
          <CaseDetail
            caseId={selectedCaseId}
            onDecisionRecorded={refreshCases}
            reviewTokenRequired={reviewTokenRequired}
            uploadNotice={
              selectedCaseId && selectedCaseId === uploadedCaseId
                ? "New upload opened for automatic verification"
                : null
            }
          />
        </div>
      </>
    ) : tab === "upload" ? (
      <div className="tool-stack">
        <UploadPanel
          completedBatchId={completedBatchId}
          onUploaded={refreshCases}
          onCaseUploaded={openUploadedCase}
          onBatchUploaded={openUploadedBatch}
          onReviewBatch={reviewUploadedBatch}
        />
        <BatchMonitor
          highlightedBatchId={uploadedBatchId}
          refreshKey={batchRefreshKey}
          onHighlightedBatchComplete={setCompletedBatchId}
          onReviewBatch={reviewUploadedBatch}
        />
      </div>
    ) : (
      <AuditHistory onOpenCase={openCaseFromActivity} onOpenBatch={openBatchFromActivity} />
    );

  return (
    <main className="app-root">
      <header className="app-header">
        <div className="app-header-inner">
          <a className="app-brand" href="https://label.af5.org/">
            <img alt="" className="app-logo" src="/logo.png" />
            <span>Alcohol Label Verifier</span>
          </a>
          <nav className="tab-bar" aria-label="Primary views">
            {(["queue", "upload", "activity"] as Tab[]).map((item) => (
              <button
                className={tab === item ? "is-active" : ""}
                key={item}
                onClick={() => selectTab(item)}
              >
                {tabLabel(item)}
              </button>
            ))}
          </nav>
        </div>
      </header>
      {content}
    </main>
  );
}

function tabLabel(tab: Tab): string {
  if (tab === "queue") return "Review";
  if (tab === "upload") return "Upload";
  return "Activity";
}

function StatusStrip({
  counts,
  statusFilter,
  onToggle,
}: {
  counts: Record<string, number>;
  statusFilter: string | null;
  onToggle: (status: string) => void;
}) {
  return (
    <div className="status-strip" aria-label="Queue status filters">
      {queueStatusFilters.map((status) => (
        <button
          className={`status-pill ${statusFilter === status ? "is-selected" : ""}`}
          data-tone={statusTone(status)}
          key={status}
          aria-pressed={statusFilter === status}
          title={`Filter ${formatLabel(status)} cases`}
          onClick={() => onToggle(status)}
        >
          <span>{formatLabel(status)}</span>
          <strong>{counts[status] ?? 0}</strong>
        </button>
      ))}
    </div>
  );
}
