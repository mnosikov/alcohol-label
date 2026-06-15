import type { FieldResult } from "../api";
import { formatLabel } from "../format";

type Props = {
  rows: FieldResult[];
};

export default function FieldResultTable({ rows }: Props) {
  if (rows.length === 0) {
    return <div className="field-evidence-empty">No extraction evidence recorded yet.</div>;
  }

  return (
    <div className="field-evidence-list">
      {rows.map((row) => (
        <article className="field-evidence-row" key={row.id}>
          <header className="field-evidence-row__header">
            <div>
              <strong>{formatLabel(row.field_name)}</strong>
              <span className="field-source">Source: {formatLabel(row.source_layer)}</span>
            </div>
            <span className={`verdict verdict-${row.verdict}`}>{formatLabel(row.verdict)}</span>
          </header>
          <dl className="field-comparison">
            <div>
              <dt>Expected</dt>
              <dd>{row.expected_value}</dd>
            </div>
            <div>
              <dt>Extracted</dt>
              <dd>{row.extracted_value ?? "Not found"}</dd>
            </div>
            <div className="field-comparison__confidence">
              <dt>Confidence</dt>
              <dd>{formatConfidence(row.confidence)}</dd>
            </div>
          </dl>
          {row.rationale ? <p className="field-rationale">{row.rationale}</p> : null}
        </article>
      ))}
    </div>
  );
}

function formatConfidence(value: number | null) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "n/a";
}
