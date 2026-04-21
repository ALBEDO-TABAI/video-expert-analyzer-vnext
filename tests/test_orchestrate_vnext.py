from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import orchestrate_vnext


def _write_run_state(
    video_dir: Path,
    *,
    current_stage: str = "score_batches",
    status: str = "running",
    coverage_ratio: float = 0.5,
    next_batch: dict | None = None,
    can_finalize: bool = False,
) -> None:
    payload = {
        "current_stage": current_stage,
        "status": status,
        "coverage_ratio": coverage_ratio,
        "next_batch": next_batch or {},
        "can_finalize": can_finalize,
    }
    (video_dir / "run_state.json").write_text(json.dumps(payload), encoding="utf-8")


def test_scores_mode_runs_ai_main_and_prints_run_state(tmp_path: Path, monkeypatch, capsys) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text("{}", encoding="utf-8")
    _write_run_state(tmp_path, status="ready_to_finalize", coverage_ratio=1.0, can_finalize=True)

    recorded: list[list[str]] = []

    def fake_ai_main(argv: list[str]) -> int:
        recorded.append(argv)
        return 7

    monkeypatch.setattr(orchestrate_vnext, "ai_main", fake_ai_main)

    result = orchestrate_vnext.main(
        [
            str(scores_path),
            "--batch-size",
            "12",
            "--storyboard-formats",
            "md",
            "--payload-style",
            "full",
            "--no-openclaw-mode",
        ]
    )

    assert result == 7
    assert recorded == [
        [
            str(scores_path),
            "--mode",
            "auto",
            "--batch-size",
            "12",
            "--storyboard-formats",
            "md",
            "--payload-style",
            "full",
            "--no-openclaw-mode",
        ]
    ]
    output = capsys.readouterr().out
    assert "当前阶段: score_batches" in output
    assert "当前状态: ready_to_finalize" in output
    assert "100.0%" in output
    assert "当前可以直接 finalize" in output


def test_scores_dispatch_json_suppresses_ai_stdout(tmp_path: Path, monkeypatch, capsys) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text("{}", encoding="utf-8")

    def fake_ai_main(argv: list[str]) -> int:
        print("noisy-ai-output")
        return 3

    monkeypatch.setattr(orchestrate_vnext, "ai_main", fake_ai_main)
    monkeypatch.setattr(
        orchestrate_vnext,
        "build_dispatch_packet",
        lambda path: {"scores_path": str(path), "controller_action": "resume_orchestrator"},
    )

    result = orchestrate_vnext.main([str(scores_path), "--dispatch-json"])

    assert result == 3
    output = capsys.readouterr().out
    assert "noisy-ai-output" not in output
    payload = json.loads(output)
    assert payload["scores_path"] == str(scores_path)
    assert payload["controller_action"] == "resume_orchestrator"


def test_video_source_dispatch_json_runs_pipeline_once_and_uses_default_output_dir(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    default_output_dir = tmp_path / "generated-output"
    pipeline_calls: list[dict[str, object]] = []

    class FakePipeline:
        def __init__(
            self,
            *,
            url: str,
            output_dir: str,
            scene_threshold: float,
            best_threshold: float,
            openclaw_mode: bool,
        ) -> None:
            pipeline_calls.append(
                {
                    "url": url,
                    "output_dir": output_dir,
                    "scene_threshold": scene_threshold,
                    "best_threshold": best_threshold,
                    "openclaw_mode": openclaw_mode,
                }
            )
            self.scores_path = tmp_path / "video-job" / "scene_scores.json"

        def run(self) -> None:
            print("pipeline-noise")

    monkeypatch.setattr(orchestrate_vnext, "VideoAnalysisPipeline", FakePipeline)
    monkeypatch.setattr(orchestrate_vnext, "get_output_directory", lambda: str(default_output_dir))
    monkeypatch.setattr(orchestrate_vnext, "ai_main", lambda argv: 0)
    monkeypatch.setattr(
        orchestrate_vnext,
        "build_dispatch_packet",
        lambda path: {"scores_path": str(path), "controller_action": "dispatch_batch"},
    )

    result = orchestrate_vnext.main(["https://example.com/video", "--dispatch-json"])

    assert result == 0
    assert pipeline_calls == [
        {
            "url": "https://example.com/video",
            "output_dir": str(default_output_dir),
            "scene_threshold": 27.0,
            "best_threshold": 7.5,
            "openclaw_mode": True,
        }
    ]
    output = capsys.readouterr().out
    assert "pipeline-noise" not in output
    payload = json.loads(output)
    assert payload["controller_action"] == "dispatch_batch"


def test_main_rejects_mutually_exclusive_openclaw_flags(tmp_path: Path, monkeypatch, capsys) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(orchestrate_vnext, "ai_main", lambda argv: 0)

    result = orchestrate_vnext.main(
        [str(scores_path), "--openclaw-mode", "--no-openclaw-mode"]
    )

    assert result == 2
    err = capsys.readouterr().err
    assert "不能同时指定" in err


def test_main_accepts_video_dir_as_source(tmp_path: Path, monkeypatch, capsys) -> None:
    scores_path = tmp_path / "scene_scores.json"
    scores_path.write_text("{}", encoding="utf-8")
    _write_run_state(tmp_path, status="running", coverage_ratio=0.5)

    recorded: list[list[str]] = []

    def fake_ai_main(argv: list[str]) -> int:
        recorded.append(argv)
        return 0

    monkeypatch.setattr(orchestrate_vnext, "ai_main", fake_ai_main)

    result = orchestrate_vnext.main([str(tmp_path)])

    assert result == 0
    assert recorded and recorded[0][0] == str(scores_path)
