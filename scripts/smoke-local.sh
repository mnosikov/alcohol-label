#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"

curl --fail "$BASE_URL/api/health"
curl --fail "$BASE_URL/api/cases"
