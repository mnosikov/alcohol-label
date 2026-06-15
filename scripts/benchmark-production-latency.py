#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import statistics
import sys
import urllib.request
from typing import Any

BASE_URL = os.environ.get("BASE_URL", "https://label.af5.org").rstrip("/")
CASE_LIMIT = int(os.environ.get("CASE_LIMIT", "100"))


def get_json(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=20) as response:
        return json.load(response)


def main() -> int:
    cases = get_json("/api/cases").get("items", [])[:CASE_LIMIT]
    rows: list[dict[str, Any]] = []
    for case in cases:
        detail = get_json(f"/api/cases/{case['id']}")
        provider_latencies = [
            usage["latency_ms"]
            for usage in detail.get("provider_usage", [])
            if isinstance(usage.get("latency_ms"), int)
        ]
        rows.append(
            {
                "id": case["id"][:8],
                "brand": case["application_fields"].get("brand_name", "Untitled"),
                "status": case["status"],
                "recommendation": case.get("current_recommendation"),
                "provider_latency_ms": sum(provider_latencies),
                "provider_calls": len(provider_latencies),
                "model": next(
                    (
                        usage.get("model")
                        for usage in detail.get("provider_usage", [])
                        if usage.get("model")
                    ),
                    None,
                ),
            }
        )

    provider_rows = [row for row in rows if row["provider_calls"]]
    latencies = [row["provider_latency_ms"] for row in provider_rows]
    payload = {
        "base_url": BASE_URL,
        "cases_seen": len(cases),
        "cases_with_provider_usage": len(provider_rows),
        "models": sorted({row["model"] for row in provider_rows if row["model"]}),
        "provider_latency_ms": summarize(latencies),
        "slowest": sorted(provider_rows, key=lambda row: row["provider_latency_ms"], reverse=True)[
            :10
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0


def summarize(values: list[int]) -> dict[str, int | float | None]:
    if not values:
        return {
            "min": None,
            "median": None,
            "mean": None,
            "p95": None,
            "max": None,
            "over_5000_count": 0,
        }
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "min": min(values),
        "median": statistics.median(values),
        "mean": round(statistics.mean(values), 1),
        "p95": ordered[p95_index],
        "max": max(values),
        "over_5000_count": sum(value > 5000 for value in values),
    }


if __name__ == "__main__":
    sys.exit(main())
