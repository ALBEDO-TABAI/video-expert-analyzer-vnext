from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import text_model_runtime


def test_retry_retries_on_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(text_model_runtime, "_max_retries_for_attempts", lambda: 2)
    monkeypatch.setattr(text_model_runtime.time, "sleep", lambda _: None)

    calls = {"count": 0}

    def flaky() -> str:
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("Rate limit hit, retry later")
        return "ok"

    result = text_model_runtime._retry_with_backoff(flaky, model_ref="x/y")
    assert result == "ok"
    assert calls["count"] == 3


def test_retry_gives_up_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(text_model_runtime, "_max_retries_for_attempts", lambda: 1)
    monkeypatch.setattr(text_model_runtime.time, "sleep", lambda _: None)

    def always_fail() -> str:
        raise RuntimeError("429 Too Many Requests")

    with pytest.raises(RuntimeError, match="429"):
        text_model_runtime._retry_with_backoff(always_fail, model_ref="x/y")


def test_retry_does_not_retry_on_non_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(text_model_runtime, "_max_retries_for_attempts", lambda: 3)
    monkeypatch.setattr(text_model_runtime.time, "sleep", lambda _: None)

    calls = {"count": 0}

    def permanent() -> str:
        calls["count"] += 1
        raise ValueError("invalid api key")

    with pytest.raises(ValueError):
        text_model_runtime._retry_with_backoff(permanent, model_ref="x/y")
    assert calls["count"] == 1


def test_is_transient_error_recognizes_keywords() -> None:
    assert text_model_runtime._is_transient_error(RuntimeError("Rate Limit exceeded"))
    assert text_model_runtime._is_transient_error(RuntimeError("request timed out"))
    assert text_model_runtime._is_transient_error(RuntimeError("503 Service Unavailable"))
    assert not text_model_runtime._is_transient_error(ValueError("bad credentials"))
