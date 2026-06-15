from backend.app.observability import langsmith


def test_traceable_is_noop_when_langsmith_sdk_is_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setattr(langsmith, "_load_traceable", lambda: None)

    @langsmith.traceable(name="test span", run_type="tool")
    def double(value: int) -> int:
        return value * 2

    assert double(3) == 6
    assert double.__name__ == "double"


def test_traceable_forwards_redaction_processors_when_langsmith_is_available(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    captured: dict[str, object] = {}

    def fake_traceable(**kwargs):
        captured.update(kwargs)

        def decorator(func):
            return func

        return decorator

    monkeypatch.setattr(langsmith, "_load_traceable", lambda: fake_traceable)

    def process_inputs(inputs: dict) -> dict:
        return {"keys": sorted(inputs)}

    def process_outputs(output: object) -> dict:
        return {"type": type(output).__name__}

    @langsmith.traceable(
        name="redacted",
        run_type="chain",
        process_inputs=process_inputs,
        process_outputs=process_outputs,
    )
    def identity(value: str) -> str:
        return value

    assert identity("ok") == "ok"
    assert captured["name"] == "redacted"
    assert captured["run_type"] == "chain"
    assert captured["process_inputs"] is process_inputs
    assert captured["process_outputs"] is process_outputs


def test_wrap_openai_client_returns_original_client_without_langsmith(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key")
    monkeypatch.setattr(langsmith, "_load_wrap_openai", lambda: None)
    client = object()

    assert langsmith.wrap_openai_client(client) is client


def test_wrap_openai_client_returns_original_client_when_tracing_is_disabled(
    monkeypatch,
) -> None:
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    client = object()

    assert langsmith.wrap_openai_client(client) is client
