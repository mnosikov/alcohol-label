import base64
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from backend.app.config import Settings
from backend.app.pipeline.openai_vision import OpenAIVisionProvider
from backend.app.pipeline.types import CANONICAL_GOVERNMENT_WARNING
from backend.app.pipeline.vision import NoopVisionProvider, VisionExtraction, VisionProvider


class FakeVisionProvider(VisionProvider):
    def extract(self, image_path: Path) -> VisionExtraction:
        return VisionExtraction(
            provider="fake",
            model="fake-vision",
            latency_ms=12,
            extracted={
                "brand_name": "OLD TOM DISTILLERY",
                "class_type": "Kentucky Straight Bourbon Whiskey",
                "alcohol_content": "45% Alc./Vol. (90 Proof)",
                "net_contents": "750 mL",
                "government_warning": CANONICAL_GOVERNMENT_WARNING,
                "warning_prefix_bold": True,
                "image_quality": "clear",
                "field_confidence": {"brand_name": 0.98},
            },
        )


def test_fake_vision_provider_contract() -> None:
    result = FakeVisionProvider().extract(Path("label.png"))

    assert result.provider == "fake"
    assert result.extracted["warning_prefix_bold"] is True
    assert result.latency_ms == 12


def test_noop_vision_provider_routes_to_error_contract() -> None:
    result = NoopVisionProvider().extract(Path("label.png"))

    assert result.provider == "noop"
    assert result.error == "Vision provider disabled or not configured"


def test_openai_provider_uses_default_base_url_when_env_is_blank(monkeypatch) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    captured: dict[str, Any] = {}

    class FakeOpenAI:
        def __init__(
            self,
            *,
            api_key: str | None,
            base_url: str | None,
            timeout: float,
            max_retries: int,
        ) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["timeout"] = timeout
            captured["max_retries"] = max_retries

    monkeypatch.setattr("backend.app.pipeline.openai_vision.OpenAI", FakeOpenAI)

    OpenAIVisionProvider(
        Settings(openai_api_key="test-key", openai_base_url="", openai_model="gpt-5.4-mini")
    )

    assert captured == {
        "api_key": "test-key",
        "base_url": None,
        "timeout": 10.0,
        "max_retries": 0,
    }


def test_openai_provider_wraps_client_for_langsmith_tracing(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    created_client = object()
    wrapped_client = object()

    class FakeOpenAI:
        def __init__(
            self,
            *,
            api_key: str | None,
            base_url: str | None,
            timeout: float,
            max_retries: int,
        ) -> None:
            assert api_key == "test-key"
            assert base_url is None
            assert timeout == 10.0
            assert max_retries == 0

    def fake_openai(
        *,
        api_key: str | None,
        base_url: str | None,
        timeout: float,
        max_retries: int,
    ):
        FakeOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        return created_client

    monkeypatch.setattr("backend.app.pipeline.openai_vision.OpenAI", fake_openai)
    monkeypatch.setattr(
        "backend.app.pipeline.openai_vision.wrap_openai_client",
        lambda client: wrapped_client if client is created_client else client,
    )

    provider = OpenAIVisionProvider(Settings(openai_api_key="test-key", openai_base_url=""))

    assert provider.client is wrapped_client


def test_openai_provider_returns_error_on_timeout(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    image_path = tmp_path / "label.png"
    Image.new("RGB", (800, 600), "#ffffff").save(image_path)

    class FakeResponses:
        def create(self, **kwargs) -> object:
            assert kwargs["timeout"] == 1.25
            raise TimeoutError("model took too long")

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("backend.app.pipeline.openai_vision.OpenAI", FakeOpenAI)

    provider = OpenAIVisionProvider(
        Settings(openai_api_key="test-key", openai_timeout_seconds=1.25)
    )
    result = provider.extract(image_path)

    assert result.provider == "openai"
    assert result.model == "gpt-5.4-mini"
    assert result.error == "TimeoutError: model took too long"
    assert result.latency_ms >= 0


def test_openai_provider_normalizes_image_payload(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    image_path = tmp_path / "large-label.png"
    Image.new("RGB", (2400, 1600), "#ffffff").save(image_path)
    captured: dict[str, Any] = {}

    class FakeResponse:
        output_text = '{"brand_name":"OLD TOM DISTILLERY"}'
        usage = None

    class FakeResponses:
        def create(self, **kwargs) -> FakeResponse:
            image_url = kwargs["input"][0]["content"][1]["image_url"]
            header, encoded = image_url.split(",", 1)
            payload = base64.b64decode(encoded)
            image = Image.open(BytesIO(payload))
            captured["header"] = header
            captured["format"] = image.format
            captured["size"] = image.size
            return FakeResponse()

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("backend.app.pipeline.openai_vision.OpenAI", FakeOpenAI)

    provider = OpenAIVisionProvider(
        Settings(openai_api_key="test-key", openai_image_max_side=800)
    )
    result = provider.extract(image_path)

    assert result.error is None
    assert result.extracted["brand_name"] == "OLD TOM DISTILLERY"
    assert captured["header"] == "data:image/jpeg;base64"
    assert captured["format"] == "JPEG"
    assert max(captured["size"]) <= 800


def test_openai_provider_prompt_requires_exact_visible_field_casing(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    image_path = tmp_path / "label.png"
    Image.new("RGB", (800, 600), "#ffffff").save(image_path)
    captured: dict[str, str] = {}

    class FakeResponse:
        output_text = '{"net_contents":"50ML"}'
        usage = None

    class FakeResponses:
        def create(self, **kwargs) -> FakeResponse:
            captured["instructions"] = kwargs["instructions"]
            return FakeResponse()

    class FakeOpenAI:
        def __init__(self, **kwargs) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr("backend.app.pipeline.openai_vision.OpenAI", FakeOpenAI)

    OpenAIVisionProvider(Settings(openai_api_key="test-key")).extract(image_path)

    assert "Preserve the exact visible spelling, casing, punctuation, and spacing" in captured[
        "instructions"
    ]
    assert "50ML" in captured["instructions"]
