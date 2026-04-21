from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audiovisual.reporting.handoff import (
    AudiovisualHandoffCoordinator,
    AudiovisualHandoffPending,
)


def test_request_body_returns_cached_output_when_prompt_matches(tmp_path: Path) -> None:
    coordinator = AudiovisualHandoffCoordinator(tmp_path, "video-1")
    with pytest.raises(AudiovisualHandoffPending):
        coordinator.request_body("sys", "usr")

    (tmp_path / "audiovisual_handoff" / "body" / "output.md").write_text(
        "# 正文内容", encoding="utf-8"
    )

    result = coordinator.request_body("sys", "usr")
    assert result == "# 正文内容"

    receipt = json.loads((tmp_path / "audiovisual_handoff" / "receipt.json").read_text(encoding="utf-8"))
    task = receipt["tasks"]["body"]
    assert task["status"] == "completed"
    assert task["input_hash"]
    assert task["output_hash"]


def test_pending_exception_carries_task_path_and_video_id(tmp_path: Path) -> None:
    coordinator = AudiovisualHandoffCoordinator(tmp_path, "video-xyz")
    with pytest.raises(AudiovisualHandoffPending) as excinfo:
        coordinator.request_body("sys", "usr")

    pending = excinfo.value
    assert pending.pending_task == "body"
    assert pending.video_id == "video-xyz"
    assert pending.task_path == tmp_path / "audiovisual_handoff" / "body" / "task.md"
    assert "video-xyz" in str(pending)
    assert "`body`" in str(pending)
    assert "audiovisual_handoff/body/task.md" in str(pending)


def test_request_body_reissues_packet_when_prompt_changes(tmp_path: Path) -> None:
    coordinator = AudiovisualHandoffCoordinator(tmp_path, "video-1")
    with pytest.raises(AudiovisualHandoffPending):
        coordinator.request_body("sys", "usr")

    (tmp_path / "audiovisual_handoff" / "body" / "output.md").write_text(
        "# 旧正文", encoding="utf-8"
    )

    with pytest.raises(AudiovisualHandoffPending):
        coordinator.request_body("sys", "usr-changed")

    receipt = json.loads((tmp_path / "audiovisual_handoff" / "receipt.json").read_text(encoding="utf-8"))
    task = receipt["tasks"]["body"]
    assert task["status"] == "pending"
