import os
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

Processor = Callable[[Any], dict[str, Any]]


def tracing_enabled() -> bool:
    return os.getenv("LANGSMITH_TRACING", "").lower() == "true" and bool(
        os.getenv("LANGSMITH_API_KEY")
    )


def _load_traceable() -> Callable[..., Callable[[Callable[P, R]], Callable[P, R]]] | None:
    try:
        from langsmith import traceable as langsmith_traceable
    except ImportError:
        return None
    return langsmith_traceable


def _load_wrap_openai() -> Callable[[Any], Any] | None:
    try:
        from langsmith.wrappers import wrap_openai
    except ImportError:
        return None
    return wrap_openai


def traceable(
    *,
    name: str | None = None,
    run_type: str | None = None,
    process_inputs: Processor | None = None,
    process_outputs: Processor | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    if not tracing_enabled():

        def disabled_decorator(func: Callable[P, R]) -> Callable[P, R]:
            return func

        return disabled_decorator

    langsmith_traceable = _load_traceable()
    if langsmith_traceable is None:

        def decorator(func: Callable[P, R]) -> Callable[P, R]:
            return func

        return decorator

    kwargs: dict[str, Any] = {}
    if name is not None:
        kwargs["name"] = name
    if run_type is not None:
        kwargs["run_type"] = run_type
    if process_inputs is not None:
        kwargs["process_inputs"] = process_inputs
    if process_outputs is not None:
        kwargs["process_outputs"] = process_outputs
    return langsmith_traceable(**kwargs)


def wrap_openai_client(client: Any) -> Any:
    if not tracing_enabled():
        return client
    wrap_openai = _load_wrap_openai()
    if wrap_openai is None:
        return client
    return wrap_openai(client)
