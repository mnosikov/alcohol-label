# Architecture

Alcohol Label Verifier uses a streamlined production-shaped design: one deployable app with clear
internal boundaries, durable storage, asynchronous verification, and auditable human review.

## Runtime Shape

One Docker image supports two roles:

- `api`: FastAPI service, React static assets, uploads, review queue, case detail, audit API, and health checks.
- `worker`: Postgres-backed job poller for queued case verification.

Supporting services:

- `postgres`: durable case, batch, evidence, and audit storage.
- VPS filesystem volume: content-addressed uploaded label images under `/opt/label/shared/uploads`.
- Dokploy Traefik: public TLS routing for `label.af5.org`.

## Four-Layer Verification

Layer 1, deterministic rules:

- Validates upload type and size.
- Normalizes application fields.
- Compares extracted fields using exact and fuzzy rules.
- Performs exact government warning checks after extraction evidence exists.

Layer 2, local OCR:

- Uses the `OcrProvider` protocol.
- Tesseract extracts raw text locally, reducing provider dependency for clear cases.
- High-confidence OCR can terminally fail clear numeric mismatches without a cloud provider call.
- Low confidence routes forward instead of producing false certainty.
- Matching OCR text without visual warning-style evidence still routes forward; OCR preserves the
  all-caps warning prefix but does not claim bold/emphasis from text alone.

Layer 3, local image quality gate:

- Uses Pillow-based checks for blur, low contrast, glare, border crop/damage, and skew.
- Runs before provider automation so degraded scans route to review without needing network egress.
- Stores metrics and out-of-distribution flags in tier evidence for reviewer and audit visibility.

Layer 4, vision provider:

- Uses the `VisionProvider` protocol.
- The public demo can use OpenAI through server-side calls.
- `OPENAI_BASE_URL` allows an approved OpenAI-compatible endpoint later.
- Provider errors, missing keys, and low confidence route to human review.

Layer 5, human review:

- Reviewers approve, reject, request a better image, or override with a note.
- Human decisions are persisted separately from machine recommendations.
- Every decision writes audit history.

## Routing Policy

The pipeline only produces a final machine `PASS` or `FAIL` when evidence is strong. Cases route to `NEEDS_REVIEW` when:

- OCR confidence is below threshold.
- OCR text matches but visual warning-style evidence is unavailable.
- Local image quality indicates blur, glare, low contrast, crop/damage, or skew.
- The vision provider is unavailable or errors.
- Warning text, caps, or bold evidence is uncertain.
- Required fields are missing.
- The image is poor quality.
- Extraction and application fields do not provide enough support for automation.

This is intentional for a regulated workflow: the machine accelerates review but does not hide uncertainty.
The app does not auto-fail degraded scans even when a missing warning appears likely; those cases
remain human-review decisions because the evidence quality itself is uncertain and the reviewer may
request a better image.

## Confidence, Provenance, And Sampling

Tier `confidence` values are operational routing scores, not automatically calibrated probabilities.
Each tier event stores a `confidence_assessment` evidence object with raw score, calibrated
confidence when available, calibration context, calibration status, and out-of-distribution flags.
Until real human outcomes are accumulated, calibrated confidence is intentionally `null`.

Tier evidence also records source references for derived claims. Field comparisons are claims about
the preserved uploaded label image and the submitted COLA-style application fields; the source image
and application data remain authoritative if the derived result disagrees.

Production can enable random sampled review of machine-passed cases with `SAMPLED_REVIEW_RATE`.
Selected auto-passed cases keep their machine recommendation but move to `needs_review`, with an
audit event explaining that the case was selected to measure the blind spot. This avoids treating
automation rate as the goal and creates an unbiased path to estimate confidently-wrong auto passes.

Golden evals in `backend/tests/fixtures/evals/golden-label-evals.json` exercise the core routing
matrix offline with fixture OCR and vision outputs. They are intentionally small and reviewable, so
new policy edge cases can be added as human-reviewed outcomes accumulate.

LangSmith tracing is optional and controlled by environment. When enabled, sanitized spans cover the
pipeline, golden evals, and OpenAI provider calls without making LangSmith a dependency for routing
or evidence persistence.

## Data Model

Tables:

- `batches`: uploaded batch metadata, status, counts, and errors.
- `cases`: application fields, image hash/path, status, recommendation, and final decision.
- `verification_jobs`: queued async work for single and batch cases.
- `tier_events`: layer-by-layer decision trail with confidence, rationale, evidence, latency, and errors.
- `field_results`: expected value, extracted value, verdict, confidence, rationale, and source layer.
- `provider_usage`: provider/model, latency, token counts, estimated cost, and provider errors.
- `human_decisions`: reviewer decision, note, reviewer label, and timestamp.
- `audit_events`: append-style operational history for case and batch events.

Image bytes are not embedded in audit records. Audit rows reference the case plus stored image hash/path.

## API Endpoints

- `GET /api/health`: smoke and readiness health.
- `POST /api/cases`: create a single case from form fields and one image.
- `POST /api/cases/{case_id}/verify`: requeue verification.
- `GET /api/cases`: list queue items with status counts.
- `GET /api/cases/{case_id}`: case detail with events, fields, provider usage, and decisions.
- `GET /api/cases/{case_id}/image`: serve stored label artwork.
- `POST /api/batches`: create cases from a CSV-plus-images upload or ZIP plus `manifest.csv`.
- `GET /api/batches`: list batch progress.
- `POST /api/cases/{case_id}/human-decision`: record final reviewer action.
- `GET /api/audit-events`: list recent audit events.

## Network And Provider Posture

The assignment warns that agency networks may block outbound ML endpoints. The app handles that directly:

- Local OCR runs before provider calls.
- `VISION_PROVIDER=noop` keeps the app functional without cloud egress.
- OpenAI is optional and server-side only.
- `OPENAI_BASE_URL` supports later migration to an approved endpoint.
- Provider failures create reviewable audit evidence rather than broken UI states.

## Deployment Posture

Production compose uses `/opt/label/.env` on the VPS, mounts durable Postgres and upload directories, and attaches only the API container to `dokploy-network`. Public traffic is owned by the existing `dokploy-traefik` container on ports `80` and `443`.
