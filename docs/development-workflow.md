# Development Workflow

GitHub is the source of truth for source control, CI, and deploy history. Docker Compose is used locally and on the VPS. Beads was used as a local issue slicing tool during implementation; it is not part of the application runtime.

## Verification Commands

```bash
pytest backend/tests -q
ruff check backend
npm --prefix frontend run build
docker compose build
./scripts/smoke-local.sh
```

## Deployment Commands

```bash
bash scripts/deploy-label-vps.sh
BASE_URL=https://label.af5.org bash scripts/smoke-production.sh
```

The GitHub Actions `Deploy VPS` job runs these scripts manually after backend tests, frontend build, and Docker build complete.
For a clean presentation queue, run the same workflow with `purge_cases=true`.

## Beads Commands

```bash
bd list
bd show <issue-id>
bd update <issue-id> --claim
bd update <issue-id> --status in_progress
bd close <issue-id>
bd ready
```

Beads records implementation slicing only. It is intentionally separate from the app runtime, database, and reviewer UI.
