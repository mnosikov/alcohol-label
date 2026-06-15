from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class VisionExtraction:
    provider: str
    model: str
    latency_ms: int
    extracted: dict[str, Any] = field(default_factory=dict)
    tokens_input: int | None = None
    tokens_output: int | None = None
    estimated_cost_usd: float | None = None
    error: str | None = None


class VisionProvider(Protocol):
    def extract(self, image_path: Path) -> VisionExtraction:
        pass


class NoopVisionProvider:
    def extract(self, image_path: Path) -> VisionExtraction:
        return VisionExtraction(
            provider="noop",
            model="none",
            latency_ms=0,
            error="Vision provider disabled or not configured",
        )
