# Evaluations

The verifier has a deterministic golden eval suite for routing behavior. The suite does not call
OpenAI or any external OCR service; it uses fixture OCR text and fixture vision payloads against the
same `VerificationPipeline` used by the worker.

Run it locally:

```bash
python -m backend.app.evals.golden
```

The manifest lives at `backend/tests/fixtures/evals/golden-label-evals.json`. It covers:

- clean pass after low-confidence OCR escalates to vision;
- required field mismatch;
- missing government warning;
- malformed warning prefix capitalization;
- provider failure in a blocked-network posture;
- uncertain warning bold evidence;
- poor image quality;
- sampled review of an otherwise machine-passed case.

The pytest gate is `backend/tests/test_golden_evals.py`. It asserts that the suite covers `PASS`,
`FAIL`, and `NEEDS_REVIEW`, plus the operational statuses `machine_passed`, `machine_failed`, and
`needs_review`.

## Real-Label Observation Suite

The observed-case suite lives at `backend/tests/fixtures/evals/real-label-evals.json` and is gated by
`backend/tests/test_real_label_evals.py`. These rows are not model training data in the fine-tuning
sense; they are calibration examples that keep the deterministic routing rules aligned with labels
we have actually inspected.

Run it locally:

```bash
python -m pytest backend/tests/test_real_label_evals.py -q
```

The suite currently captures production batch observations for:

- Fathers & Sons: high-fidelity match with bright/vertical label evidence should still machine pass;
- Robin Hood and Casamigos: soft visual-quality flags should not override complete field matches;
- Barenjager: accented label spelling should match unaccented application entry;
- RED DOG: missing alcohol content remains a machine failure;
- Pinnacle Ridge and Oceanside: front-only evidence lacking rear-label fields should fail;
- Paradox Brewery and JALDA: field mismatches stay machine failures;
- all-caps government warning: exact uppercase prefix and matching body can pass without separate
  bold evidence;
- statutory warning punctuation and incomplete warning body failures;
- MB Liquors: matching fields with warning-prefix uncertainty routes to review.

It also includes two adjudicated Beer wording variants from manual review:

- exact `Beer` text anywhere on the label can pass when the application class is Beer;
- a beer style alone, such as India Pale Ale without the exact word Beer, routes to review.

The comparison rule for submitted application fields is evidence-presence based: if the claimed
brand, class/type, alcohol content, or net contents is present anywhere in whole-label extracted
text, that field can match even when another prominent label phrase was extracted as the primary
brand or class. The statutory government warning remains stricter: whitespace/layout artifacts are
ignored, but missing punctuation, missing prefix, or missing warning clauses remain failures.

When adding a production observation, prefer one narrow row with:

- the application fields as submitted;
- the extracted evidence that actually drove the decision;
- the expected routing after human review or team adjudication;
- a tag describing the lesson, such as `accent_tolerant`, `warning_punctuation`, or
  `missing_rear_label_evidence`.

## Production Queue Test Sets

Large manual queue test assets are intentionally excluded from the repository so the submission
stays small and focused. The app itself does not depend on those files at runtime.

During production validation, the balanced generated batch matched current routing:

| Route | Expected | Actual |
| --- | ---: | ---: |
| PASS | 13 | 13 |
| FAIL | 6 | 6 |
| NEEDS_REVIEW | 6 | 6 |

The balanced mixed batch also matched current routing:

| Route | Expected | Actual |
| --- | ---: | ---: |
| PASS | 12 | 12 |
| FAIL | 5 | 5 |
| NEEDS_REVIEW | 3 | 3 |

Both batches are ordered to avoid grouping all passes, failures, or review cases together in the
review queue.

## Human Outcome Loop

Golden evals protect known routing cases. Production improvement should come from reviewer outcomes:

- auto-passed cases selected by `SAMPLED_REVIEW_RATE`;
- provider failures and poor-image escalations;
- human overrides of machine failures;
- labels where a reviewer requests a better image.

Those outcomes can become future manifest rows once they are anonymized and scrubbed of sensitive
submitter data.

## LangSmith Setup

LangSmith tracing is not required for deterministic evals, but it is the right observability path for
provider-backed eval runs and model changes. Configure these in GitHub Actions and `/opt/label/.env`
to enable tracing:

```text
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<LangSmith API key>
LANGSMITH_PROJECT=alcohol-label-verifier
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

Keep the API key in protected variables or VPS environment files only.

Trace spans are sanitized: eval spans log case IDs, tags, expected/actual routing, and status counts;
pipeline spans log field presence, layer decisions, confidence, provider metadata, token counts, and
errors. They do not log raw image bytes or full application text.
