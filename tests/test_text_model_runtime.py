from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import text_model_runtime


def _runtime_config(api_style: str, fallback_models: list[str] | None = None) -> dict:
    return {
        "providers": {
            "openai": {
                "apiKey": "test-openai-key",
                "baseUrl": "https://api.openai.test/v1",
                "api": api_style,
                "models": [
                    {"id": "gpt-test", "api": api_style},
                    {"id": "gpt-fallback", "api": "openai-completions"},
                ],
            },
            "anthropic": {
                "apiKey": "test-anthropic-key",
                "baseUrl": "https://api.anthropic.test/v1",
                "api": "anthropic-messages",
                "models": [
                    {"id": "claude-test", "api": "anthropic-messages"},
                ],
            },
        },
        "preferred_model": "openai/gpt-test" if api_style != "anthropic-messages" else "anthropic/claude-test",
        "fallback_models": fallback_models or [],
    }


def test_request_text_with_runtime_uses_openai_completions(monkeypatch) -> None:
    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **call_kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="completion output"))],
                        call_kwargs=call_kwargs,
                    )
                )
            )

    monkeypatch.setattr(text_model_runtime, "OpenAI", FakeOpenAI)

    output = text_model_runtime.request_text_with_runtime(
        "system prompt",
        "user prompt",
        _runtime_config("openai-completions"),
    )

    assert output == "completion output"


def test_request_text_with_runtime_uses_openai_responses(monkeypatch) -> None:
    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.responses = SimpleNamespace(
                create=lambda **call_kwargs: SimpleNamespace(
                    output_text="responses output",
                    call_kwargs=call_kwargs,
                )
            )

    monkeypatch.setattr(text_model_runtime, "OpenAI", FakeOpenAI)

    output = text_model_runtime.request_text_with_runtime(
        "system prompt",
        "user prompt",
        _runtime_config("openai-responses"),
    )

    assert output == "responses output"


def test_request_text_with_runtime_uses_anthropic_messages(monkeypatch) -> None:
    class FakeAnthropic:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.messages = SimpleNamespace(
                create=lambda **call_kwargs: SimpleNamespace(
                    content=[SimpleNamespace(type="text", text="anthropic output")],
                    call_kwargs=call_kwargs,
                )
            )

    monkeypatch.setattr(text_model_runtime, "Anthropic", FakeAnthropic)

    output = text_model_runtime.request_text_with_runtime(
        "system prompt",
        "user prompt",
        _runtime_config("anthropic-messages"),
    )

    assert output == "anthropic output"


def test_request_text_with_runtime_falls_back_to_next_model(monkeypatch) -> None:
    attempts: list[str] = []

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.chat = SimpleNamespace(
                completions=SimpleNamespace(create=self._create)
            )

        def _create(self, **call_kwargs):
            attempts.append(call_kwargs["model"])
            if call_kwargs["model"] == "gpt-test":
                raise RuntimeError("preferred failed")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="fallback output"))])

    monkeypatch.setattr(text_model_runtime, "OpenAI", FakeOpenAI)

    output = text_model_runtime.request_text_with_runtime(
        "system prompt",
        "user prompt",
        _runtime_config("openai-completions", fallback_models=["openai/gpt-fallback"]),
    )

    assert output == "fallback output"
    assert attempts == ["gpt-test", "gpt-fallback"]
