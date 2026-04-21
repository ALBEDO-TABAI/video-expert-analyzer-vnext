from pathlib import Path
import json
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import openclaw_dispatch


def test_resolve_scores_path_accepts_directory_and_scores_file(tmp_path: Path) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text("{}", encoding="utf-8")

    assert openclaw_dispatch._resolve_scores_path(str(tmp_path)) == scores_path.resolve()
    assert openclaw_dispatch._resolve_scores_path(str(scores_path)) == scores_path.resolve()


def test_load_batch_receipt_derives_in_progress_from_scene_content(tmp_path: Path) -> None:
    output_path = tmp_path / "batch-001-output.json"
    output_path.write_text(
        json.dumps(
            {
                "scenes": [
                    {
                        "scene_number": 1,
                        "description": "已有内容",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    batch = {
        "batch_id": "batch-001",
        "scene_numbers": [1],
        "output": str(output_path),
    }

    receipt = openclaw_dispatch._load_batch_receipt(batch)

    assert receipt is not None
    assert receipt["batch_id"] == "batch-001"
    assert receipt["output_path"] == "batch-001-output.json"
    assert receipt["status"] == "in_progress"


@pytest.mark.parametrize(
    ("state", "receipt", "next_batch", "expected"),
    [
        ({"status": "completed", "current_stage": "completed"}, None, None, "done"),
        ({"status": "blocked", "current_stage": "score_batches"}, None, None, "resolve_blocker"),
        ({"status": "running", "current_stage": "score_batches"}, {"status": "completed"}, {"batch_id": "batch-001"}, "resume_orchestrator"),
        ({"status": "running", "current_stage": "score_batches"}, {"status": "in_progress"}, {"batch_id": "batch-001"}, "wait_current_worker"),
        ({"status": "running", "current_stage": "score_batches"}, {"status": "blocked"}, {"batch_id": "batch-001"}, "repair_current_batch"),
        ({"status": "ready_to_finalize", "current_stage": "score_batches", "can_finalize": True}, None, None, "run_finalize"),
    ],
)
def test_controller_action_covers_receipt_and_finalize_branches(
    state: dict,
    receipt: dict | None,
    next_batch: dict | None,
    expected: str,
) -> None:
    assert openclaw_dispatch._controller_action(state, receipt, next_batch) == expected


def test_controller_action_resolves_blocker_when_next_batch_resource_invalid() -> None:
    state = {"status": "running", "current_stage": "score_batches"}
    next_batch = {"batch_id": "batch-999", "resource_invalid": True, "index_missing": True}
    assert (
        openclaw_dispatch._controller_action(state, {"status": "pending"}, next_batch)
        == "resolve_blocker"
    )


def test_controller_action_resolves_blocker_when_all_batches_blocked() -> None:
    state = {"status": "running", "current_stage": "score_batches"}
    assert (
        openclaw_dispatch._controller_action(state, None, None, all_batches_blocked=True)
        == "resolve_blocker"
    )


def test_controller_action_diagnose_environment_when_score_stage_has_no_next_batch() -> None:
    state = {"status": "running", "current_stage": "score_batches"}
    assert (
        openclaw_dispatch._controller_action(state, None, None)
        == "diagnose_environment"
    )


@pytest.mark.parametrize(
    ("receipt",),
    [
        (None,),
        ({"status": "pending"},),
        ({"status": "unknown_status_marker"},),
        ({},),
    ],
)
def test_controller_action_spawns_worker_when_next_batch_has_no_active_receipt(receipt: dict | None) -> None:
    """Default branch: any next_batch whose receipt isn't completed/in_progress/blocked
    must trigger a fresh worker spawn, regardless of whether the receipt is
    missing entirely (None / {}) or carries an unrecognized status."""
    state = {"status": "running", "current_stage": "score_batches"}
    next_batch = {"batch_id": "batch-001"}
    assert (
        openclaw_dispatch._controller_action(state, receipt, next_batch)
        == "spawn_batch_worker"
    )


def test_controller_action_returns_run_prepare_when_stage_is_prepare() -> None:
    state = {"status": "running", "current_stage": "prepare"}
    assert openclaw_dispatch._controller_action(state, None, None) == "run_prepare"


def test_controller_action_falls_back_to_resume_orchestrator_when_stage_unrecognized() -> None:
    """Catch-all branch: when no stage/status hint applies, the controller
    must defer to a fresh orchestrator run rather than picking arbitrarily."""
    state = {"status": "running", "current_stage": "merge_validate"}
    assert openclaw_dispatch._controller_action(state, None, None) == "resume_orchestrator"


def test_controller_action_resolve_blocker_for_resource_invalid_overrides_receipt_status() -> None:
    """resource_invalid on the next_batch must short-circuit the receipt
    status check — even if the receipt looks healthy, the broken resource
    has to be fixed first."""
    state = {"status": "running", "current_stage": "score_batches"}
    next_batch = {"batch_id": "batch-002", "resource_invalid": True}
    healthy_receipt = {"status": "completed"}
    assert (
        openclaw_dispatch._controller_action(state, healthy_receipt, next_batch)
        == "resolve_blocker"
    )


def test_controller_action_completed_status_wins_over_blocked_stage() -> None:
    """Once the run is marked completed, no other branch should fire — even
    if a stale next_batch packet or blocked flag is still hanging around."""
    state = {"status": "completed", "current_stage": "blocked"}
    assert (
        openclaw_dispatch._controller_action(
            state,
            {"status": "blocked"},
            {"batch_id": "stale-batch"},
            all_batches_blocked=True,
        )
        == "done"
    )


def test_build_dispatch_packet_resolves_relative_batch_paths_and_prompt(tmp_path: Path) -> None:
    video_dir = tmp_path / "video"
    host_batches = video_dir / "host_batches"
    host_batches.mkdir(parents=True)
    scores_path = video_dir / "scene_scores.json"
    scores_path.write_text("{}", encoding="utf-8")

    batch_output = host_batches / "batch-001-output.json"
    batch_output.write_text(json.dumps({"scenes": []}, ensure_ascii=False), encoding="utf-8")
    (host_batches / "index.json").write_text(
        json.dumps(
            {
                "batches": [
                    {
                        "batch_id": "batch-001",
                        "scene_numbers": [1, 2],
                        "brief": "batch-001-brief.md",
                        "contact_sheet": "batch-001-contact-sheet.png",
                        "input": "batch-001-input.json",
                        "output": "batch-001-output.json",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (video_dir / "run_state.json").write_text(
        json.dumps(
            {
                "current_stage": "score_batches",
                "status": "running",
                "next_batch": {"batch_id": "batch-001"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    packet = openclaw_dispatch.build_dispatch_packet(scores_path)

    assert packet["controller_action"] == "spawn_batch_worker"
    assert packet["next_batch"]["output"] == str(batch_output.resolve())
    assert "primary, start, mid, and end frames" in packet["worker_prompt"]
    assert "Do not rely on the contact sheet alone" in packet["worker_prompt"]
