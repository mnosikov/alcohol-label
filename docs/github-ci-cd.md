# GitHub CI/CD

GitHub Actions is the CI/CD path for this project. The manual VPS deploy job has
been proven in production and is the supported deployment route.

## Workflows

- Pushes and pull requests to `main` run backend tests, frontend build, and a
  production Docker image build.
- Manual deploys run from **Actions > CI and Deploy > Run workflow** on `main`.
  The deploy job waits for the same backend, frontend, and Docker checks before
  SSHing to the VPS.
- The manual workflow has a `purge_cases` input. Set it to `true` for presentation
  resets; it clears cases, batches, jobs, evidence, and audit rows after a successful
  deploy, then restarts the worker.

## Required GitHub Secrets

Set these in **Settings > Secrets and variables > Actions > Secrets**:

- `VPS_SSH_PRIVATE_KEY`: private key for the `labeldeploy` deploy user

## Required GitHub Variables

Set these in **Settings > Secrets and variables > Actions > Variables**:

- `VPS_HOST`: `51.81.83.107`
- `VPS_USER`: `labeldeploy`
- `BASE_URL`: `https://label.af5.org`
- `APP_ROOT`: `/opt/label`
- `COMPOSE_PROJECT_NAME`: `label`

`VPS_HOST` and `VPS_USER` may also be configured as secrets, but variables are
fine because neither value is sensitive.

## Recommended Variables

Set these in **Settings > Secrets and variables > Actions > Variables**:

- `VISION_PROVIDER`: `openai`
- `OPENAI_MODEL`: the production OpenAI vision model
- `OPENAI_TIMEOUT_SECONDS`: optional provider latency budget, default `10.0`
- `OPENAI_IMAGE_MAX_SIDE`: optional vision image max side, default `1600`
- `OPENAI_IMAGE_JPEG_QUALITY`: optional vision JPEG quality, default `82`
- `WORKER_IDLE_SLEEP_SECONDS`: optional worker queue polling interval, default `0.5`
- `PUBLIC_REVIEW_ENABLED`: `true` or `false`
- `LANGSMITH_TRACING`: `true`
- `LANGSMITH_PROJECT`: production LangSmith project name

## Optional Secrets

Set only the values that should be updated on the VPS during deploy:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `REVIEW_TOKEN`
- `LANGSMITH_API_KEY`
- `LANGSMITH_ENDPOINT`

Blank optional values are ignored by `scripts/deploy-label-vps.sh` so missing
GitHub secrets cannot wipe existing production settings from `/opt/label/.env`.
