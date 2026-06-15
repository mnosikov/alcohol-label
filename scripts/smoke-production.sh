#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-https://label.af5.org}"

curl_args=(--retry 12 --retry-delay 5 --retry-connrefused --retry-all-errors --fail)

curl "${curl_args[@]}" "$BASE_URL/api/health"
curl "${curl_args[@]}" "$BASE_URL/api/cases"
