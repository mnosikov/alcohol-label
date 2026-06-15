# Alcohol Label Verifier

Live demo: https://label.af5.org

Alcohol Label Verifier is a production-shaped prototype for TTB-style label review. It compares label artwork against structured application fields, records auditable machine evidence, and routes uncertain cases to a human reviewer.

## What It Does

- Creates single-label cases from an image plus application fields.
- Accepts CSV-plus-images or ZIP batch uploads with `manifest.csv` for importer-style bulk submissions.
- Runs a four-layer verification path: deterministic rules, local OCR, optional vision provider, and human review.
- Persists field-level evidence, provider usage, tier events, human decisions, and audit events.
- Serves an operational React review console, not a marketing landing page.
- Deploys as one Docker image with `api` and `worker` roles behind the VPS Traefik edge.

## Repository Layout

```text
backend/      FastAPI API, worker, pipeline, evals, and backend tests
frontend/     React reviewer console
scripts/      VPS deploy and smoke-test scripts
docs/         Reviewer walkthrough, architecture, evals, performance, and ops notes
.github/      GitHub Actions CI and manual VPS deploy workflow
```

Start with [docs/reviewer-walkthrough.md](docs/reviewer-walkthrough.md) for the live demo path,
then [docs/architecture.md](docs/architecture.md), [docs/evaluations.md](docs/evaluations.md),
and [docs/performance-baseline.md](docs/performance-baseline.md) for engineering evidence.

## Quick Demo

1. Open https://label.af5.org.
2. Upload a single label or batch manifest from local sample data.
3. Review the COLA-style queue, status counts, and searchable case list.
4. Open a case detail page.
5. Inspect the four-layer trail and field evidence.
6. Record a human decision.

Optional demo seeding can be enabled with `SEED_DEMO_DATA=true` when a local fixture queue is useful.

For a reviewer-facing path through the live app, see [docs/reviewer-walkthrough.md](docs/reviewer-walkthrough.md).

Manual sample labels are intentionally kept outside the repository so the submission stays
small and focused. Use the Upload tab with local sample images or a batch `manifest.csv`
when exercising the live app.

## Architecture

The app uses a streamlined production-shaped architecture: one repo, one Docker image, two runtime roles, and clear internal boundaries.

1. Deterministic rules validate uploads, normalize fields, and make exact/fuzzy comparisons.
2. Local OCR provides a no-network extraction path for simple labels.
3. Vision provider extraction is optional and behind a swappable interface.
4. Human review is the final authority for uncertain, failed-provider, poor-quality, or policy-sensitive cases.

The public demo can use server-side OpenAI calls when configured. A production agency deployment can point the same `VisionProvider` interface at an approved in-network or Azure Gov endpoint. If provider access is blocked, cases route to human review instead of silently failing.

See [docs/architecture.md](docs/architecture.md) for the full system map.

## Local Development

Requirements:

- Python 3.12
- Node 22+
- Docker with Compose
- Tesseract, if running OCR outside Docker

Setup:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
npm --prefix frontend ci
cp .env.example .env
```

Run checks:

```bash
pytest backend/tests -q
python -m backend.app.evals.golden
ruff check backend
npm --prefix frontend run build
```

Run with Docker:

```bash
docker compose build
docker compose up -d
./scripts/smoke-local.sh
```

The local API is available at http://localhost:8000. The production Docker image builds the React app into `frontend/dist` and FastAPI serves it at `/`.

## Batch Upload Format

On the Upload screen, provide a CSV manifest plus selected image files, or provide a ZIP containing
`manifest.csv` plus image files. Each row creates one case. Required manifest
columns:

```text
filename,brand_name,class_type,alcohol_content,net_contents,applicant_name_address,source_of_product
```

`applicant_name_address` is the responsible party name/address from TTB F 5100.31
Item 8; it must include at least a U.S. state. `source_of_product` must be
`Domestic` or `Imported`. Imported products also require `country_of_origin`.

Use the optional `back_filename` column when a product has a rear label:

```text
filename,back_filename,brand_name,fanciful_name,class_type,alcohol_content,net_contents,applicant_name_address,source_of_product,country_of_origin
front-label.jpg,back-label.jpg,Example Brand,Optional name,Beer,5% Alc./Vol.,12 fl oz,"Example Brewing Co, Denver, CO",Domestic,
```

The importer treats one CSV row as one product. Extra selected images are reported and
ignored unless they are explicitly referenced or can be deterministically inferred as the
unique rear label, such as `pinnacle-ridge-01.png` plus `pinnacle-ridge-02.png`.
Do not add a rear filename as an unquoted extra comma-separated value; use
`back_filename` instead. Images are stored by SHA-256 under the configured upload
directory.

If individual manifest rows are incomplete, reference missing image files, or still contain
the sample template row, valid rows are accepted and invalid rows are listed in the upload
summary with row numbers and reasons. If no rows are valid, the upload is rejected without
creating an empty batch.

## API Surface

- `GET /api/health`
- `GET /api/config`
- `POST /api/cases`
- `POST /api/cases/{case_id}/verify`
- `GET /api/cases`
- `GET /api/cases/{case_id}`
- `GET /api/cases/{case_id}/image`
- `POST /api/batches`
- `GET /api/batches`
- `POST /api/cases/{case_id}/human-decision`
- `GET /api/audit-events`

## Configuration

Important environment variables:

```text
DATABASE_URL=postgresql+psycopg://label:label@postgres:5432/label
UPLOAD_DIR=/data/uploads
STATIC_DIR=/app/frontend/dist
VISION_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=gpt-5.4-mini
OPENAI_TIMEOUT_SECONDS=10.0
REVIEW_TOKEN=
PUBLIC_REVIEW_ENABLED=true
OCR_ENABLED=true
SEED_DEMO_DATA=false
RUN_DB_STARTUP=true
SAMPLED_REVIEW_RATE=0.0
LANGSMITH_TRACING=false
LANGSMITH_PROJECT=alcohol-label-verifier
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=
```

`VISION_PROVIDER=noop` keeps the app fully usable in a blocked-network environment. `VISION_PROVIDER=openai` enables the OpenAI-backed provider when `OPENAI_API_KEY` is configured.

The public demo sets `PUBLIC_REVIEW_ENABLED=true` so reviewers can exercise the human-in-the-loop
workflow without credentials, even when a deployment secret exists. When `PUBLIC_REVIEW_ENABLED=false`
and `REVIEW_TOKEN` is set, human decision writes require `X-Review-Token`; the review UI detects that
mode and shows a local reviewer-token field without exposing the secret in the bundle.

`SAMPLED_REVIEW_RATE` can route a deterministic random sample of machine-passed cases back to human
review, so the team can measure confidently-wrong auto passes instead of optimizing automation rate.

Golden routing evals are documented in [docs/evaluations.md](docs/evaluations.md). They run offline
with fixture OCR and vision outputs, covering passing, failing, human-review, provider-failure,
poor-image, warning-format, OCR-escalation, and sampled-review cases.

When `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` is set, the pipeline, golden evals, and OpenAI
provider calls emit sanitized traces. The trace processors intentionally record routing metadata,
model names, token counts, and decisions rather than raw image bytes or full application text.

## Deployment

Production target: `https://label.af5.org` on VPS `51.81.83.107`.

The VPS uses Dokploy Traefik:

```text
TRAEFIK_NETWORK=dokploy-network
TRAEFIK_ENTRYPOINT=websecure
TRAEFIK_CERTRESOLVER=letsencrypt
```

GitHub Actions variables and secrets required for manual VPS deploy:

```text
Variables:
  VPS_HOST=51.81.83.107
  VPS_USER=labeldeploy
  BASE_URL=https://label.af5.org
  VISION_PROVIDER=openai
  OPENAI_MODEL=gpt-5.4-mini
  OPENAI_TIMEOUT_SECONDS=10.0
  LANGSMITH_TRACING=true
  LANGSMITH_PROJECT=alcohol-label-verifier

Secrets:
  VPS_SSH_PRIVATE_KEY=<private deploy key contents>
  OPENAI_API_KEY=<OpenAI API key>
  LANGSMITH_API_KEY=<LangSmith API key>
```

Keep `OPENAI_API_KEY`, `LANGSMITH_API_KEY`, `POSTGRES_PASSWORD`, and operational app secrets out of
workflow logs. The deploy script syncs protected CI values for `VISION_PROVIDER`, OpenAI,
LangSmith, `REVIEW_TOKEN`, and `PUBLIC_REVIEW_ENABLED` into `/opt/label/.env` before restarting
containers.

Manual deploys run from GitHub Actions: **Actions > CI and Deploy > Run workflow** on `main`.
The underlying scripts remain runnable for emergency local deploys:

```bash
bash scripts/deploy-label-vps.sh
bash scripts/smoke-production.sh
```

The production compose file attaches only the `api` container to `dokploy-network`; app containers do not publish public host ports.

## Reviewer Notes

- Machine output is a recommendation: `PASS`, `FAIL`, or `NEEDS_REVIEW`.
- Human action is the final decision when routed to review.
- The review UI is the product surface: searchable queue, label viewer, field evidence, layer trail, batch monitor, and audit log.
- Government warning text is compared against the canonical required warning, including the all-caps prefix.
- Provider failures and low-confidence extraction become reviewable work items with audit evidence.
- Current reliability and speed tuning notes are tracked in [docs/reliability-and-speed-notes.md](docs/reliability-and-speed-notes.md), including the 5-second processing goal and recent OCR/vision edge cases.
- Beads was used as a lightweight local build workflow and is documented in [docs/agents/beads.md](docs/agents/beads.md); it is not part of the application runtime.
