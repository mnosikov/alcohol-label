#!/usr/bin/env bash
set -euo pipefail

HOST="${VPS_HOST:?VPS_HOST must be set}"
USER="${VPS_USER:-labeldeploy}"
APP_ROOT="${APP_ROOT:-/opt/label}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-label}"
ARCHIVE_DIR="$(mktemp -d)"
ARCHIVE="$ARCHIVE_DIR/label-source.tar.gz"
ENV_UPDATE="$ARCHIVE_DIR/label-ci-env"

cleanup() {
  rm -rf "$ARCHIVE_DIR"
}
trap cleanup EXIT

tar \
  --exclude='./.git' \
  --exclude='./.agents' \
  --exclude='./.beads' \
  --exclude='./.claude' \
  --exclude='./.codex' \
  --exclude='./.env' \
  --exclude='./.env.local' \
  --exclude='./.env.production' \
  --exclude='./.env.development' \
  --exclude='./.codegraph' \
  --exclude='./.venv' \
  --exclude='./.worktrees' \
  --exclude='./node_modules' \
  --exclude='./frontend/node_modules' \
  --exclude='./frontend/dist' \
  --exclude='./.pytest_cache' \
  --exclude='./.ruff_cache' \
  --exclude='./.superpowers' \
  --exclude='./tmp' \
  --exclude='./.tmp' \
  --exclude='./docs' \
  --exclude='./backend/tests' \
  --exclude='./CLAUDE.md' \
  --exclude='./alcohol_label_verifier.egg-info' \
  --exclude='./*.egg-info' \
  -czf "$ARCHIVE" .

write_env_update() {
  local key="$1"
  if [ "${!key+x}" = "x" ] && [ -n "${!key}" ]; then
    printf '%s=%q\n' "$key" "${!key}" >> "$ENV_UPDATE"
  fi
}

for key in \
  VISION_PROVIDER \
  OPENAI_API_KEY \
  OPENAI_BASE_URL \
  OPENAI_MODEL \
  OPENAI_TIMEOUT_SECONDS \
  OPENAI_IMAGE_MAX_SIDE \
  OPENAI_IMAGE_JPEG_QUALITY \
  WORKER_IDLE_SLEEP_SECONDS \
  SEED_DEMO_DATA \
  REVIEW_TOKEN \
  PUBLIC_REVIEW_ENABLED \
  LANGSMITH_TRACING \
  LANGSMITH_API_KEY \
  LANGSMITH_PROJECT \
  LANGSMITH_ENDPOINT; do
  write_env_update "$key"
done

scp "$ARCHIVE" "$USER@$HOST:/tmp/label-source.tar.gz"
if [ -s "$ENV_UPDATE" ]; then
  scp "$ENV_UPDATE" "$USER@$HOST:/tmp/label-ci-env"
fi

ssh "$USER@$HOST" "APP_DIR='$APP_ROOT' COMPOSE_PROJECT_NAME='$COMPOSE_PROJECT_NAME' bash -s" <<'REMOTE'
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/label}"
APP_SOURCE="$APP_DIR/app"
RELEASE_DIR="$APP_DIR/app.release"
PREVIOUS_DIR="$APP_DIR/app.previous"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-label}"
COMPOSE=(docker compose --project-name "$COMPOSE_PROJECT_NAME" --env-file "$APP_DIR/.env" -f docker-compose.production.yml)

test -f "$APP_DIR/.env"
mkdir -p "$APP_DIR/shared/uploads" "$APP_DIR/shared/postgres" "$APP_DIR/backups"

update_env_var() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp)"
  awk -v key="$key" -v value="$value" '
    $0 ~ "^" key "=" {
      print key "=" value
      updated = 1
      next
    }
    { print }
    END {
      if (!updated) {
        print key "=" value
      }
    }
  ' "$APP_DIR/.env" > "$tmp"
  cat "$tmp" > "$APP_DIR/.env"
  rm -f "$tmp"
  chmod 600 "$APP_DIR/.env"
}

if [ -f /tmp/label-ci-env ]; then
  set -a
  # shellcheck disable=SC1091
  . /tmp/label-ci-env
  set +a
  for key in \
    VISION_PROVIDER \
    OPENAI_API_KEY \
    OPENAI_BASE_URL \
    OPENAI_MODEL \
    OPENAI_TIMEOUT_SECONDS \
    OPENAI_IMAGE_MAX_SIDE \
    OPENAI_IMAGE_JPEG_QUALITY \
    WORKER_IDLE_SLEEP_SECONDS \
    SEED_DEMO_DATA \
    REVIEW_TOKEN \
    PUBLIC_REVIEW_ENABLED \
    LANGSMITH_TRACING \
    LANGSMITH_API_KEY \
    LANGSMITH_PROJECT \
    LANGSMITH_ENDPOINT; do
    if [ "${!key+x}" = "x" ]; then
      update_env_var "$key" "${!key}"
    fi
  done
  rm -f /tmp/label-ci-env
fi

rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
tar -xzf /tmp/label-source.tar.gz -C "$RELEASE_DIR"
rm -f /tmp/label-source.tar.gz

rm -rf "$PREVIOUS_DIR"
if [ -d "$APP_SOURCE" ]; then
  mv "$APP_SOURCE" "$PREVIOUS_DIR"
fi
mv "$RELEASE_DIR" "$APP_SOURCE"

cd "$APP_SOURCE"
"${COMPOSE[@]}" build
"${COMPOSE[@]}" up -d postgres api worker
"${COMPOSE[@]}" ps
REMOTE
