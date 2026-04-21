"""Tests for host_batching.reset_stale_in_progress_receipts."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from host_batching import (  # noqa: E402
    STALE_IN_PROGRESS_MINUTES,
    STALE_RECOVERY_MARKER,
    reset_stale_in_progress_receipts,
)


def _write_batch(dir_path: Path, batch_id: str, receipt: dict) -> Path:
    path = dir_path / f"{batch_id}-output.json"
    payload = {"batch_id": batch_id, "scenes": [], "receipt": receipt}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@pytest.fixture()
def host_batches_dir(tmp_path: Path) -> Path:
    target = tmp_path / "host_batches"
    target.mkdir()
    return target


def test_fresh_in_progress_is_untouched(host_batches_dir: Path) -> None:
    now = datetime(2026, 4, 18, 12, 0, 0)
    fresh_started = (now - timedelta(minutes=5)).isoformat()
    path = _write_batch(
        host_batches_dir,
        "batch-001",
        {
            "status": "in_progress",
            "has_todo": True,
            "started_at": fresh_started,
            "updated_at": fresh_started,
            "completed_at": "",
            "worker_summary": "scoring",
        },
    )

    recovered = reset_stale_in_progress_receipts(host_batches_dir, now=now)

    assert recovered == []
    receipt = json.loads(path.read_text())["receipt"]
    assert receipt["status"] == "in_progress"
    assert receipt["worker_summary"] == "scoring"


def test_stale_in_progress_is_reset_to_pending(host_batches_dir: Path) -> None:
    now = datetime(2026, 4, 18, 12, 0, 0)
    stale_started = (
        now - timedelta(minutes=STALE_IN_PROGRESS_MINUTES + 1)
    ).isoformat()
    path = _write_batch(
        host_batches_dir,
        "batch-007",
        {
            "status": "in_progress",
            "has_todo": True,
            "started_at": stale_started,
            "updated_at": stale_started,
            "completed_at": "",
            "worker_summary": "scoring",
        },
    )

    recovered = reset_stale_in_progress_receipts(host_batches_dir, now=now)

    assert recovered == ["batch-007"]
    receipt = json.loads(path.read_text())["receipt"]
    assert receipt["status"] == "pending"
    assert receipt["has_todo"] is True
    assert receipt["updated_at"] == ""
    assert receipt["completed_at"] == ""
    assert receipt["worker_summary"].startswith(STALE_RECOVERY_MARKER)
    # Original summary is preserved after the marker.
    assert "scoring" in receipt["worker_summary"]


def test_completed_and_blocked_are_never_touched(host_batches_dir: Path) -> None:
    now = datetime(2026, 4, 18, 12, 0, 0)
    long_ago = (now - timedelta(hours=24)).isoformat()

    completed_path = _write_batch(
        host_batches_dir,
        "batch-100",
        {
            "status": "completed",
            "has_todo": False,
            "started_at": long_ago,
            "updated_at": long_ago,
            "completed_at": long_ago,
            "worker_summary": "done",
        },
    )
    blocked_path = _write_batch(
        host_batches_dir,
        "batch-101",
        {
            "status": "blocked",
            "has_todo": True,
            "started_at": long_ago,
            "updated_at": long_ago,
            "completed_at": "",
            "worker_summary": "stuck",
            "needs_review": [{"scene_number": 3, "error": "timeout"}],
        },
    )

    recovered = reset_stale_in_progress_receipts(host_batches_dir, now=now)

    assert recovered == []
    assert json.loads(completed_path.read_text())["receipt"]["status"] == "completed"
    assert json.loads(blocked_path.read_text())["receipt"]["status"] == "blocked"


def test_missing_directory_returns_empty(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    assert reset_stale_in_progress_receipts(missing) == []


def test_recovery_is_idempotent(host_batches_dir: Path) -> None:
    now = datetime(2026, 4, 18, 12, 0, 0)
    stale_started = (
        now - timedelta(minutes=STALE_IN_PROGRESS_MINUTES + 10)
    ).isoformat()
    _write_batch(
        host_batches_dir,
        "batch-200",
        {
            "status": "in_progress",
            "has_todo": True,
            "started_at": stale_started,
            "updated_at": stale_started,
            "completed_at": "",
            "worker_summary": "scoring",
        },
    )

    first = reset_stale_in_progress_receipts(host_batches_dir, now=now)
    second = reset_stale_in_progress_receipts(host_batches_dir, now=now)

    assert first == ["batch-200"]
    # Second pass has nothing to do because status is now `pending`.
    assert second == []


def test_fresh_heartbeat_keeps_long_running_worker_alive(host_batches_dir: Path) -> None:
    """A worker can keep an old started_at as long as it bumps heartbeat_at —
    that's the documented escape hatch for legitimately long-running batches."""
    now = datetime(2026, 4, 18, 12, 0, 0)
    long_ago = (now - timedelta(hours=24)).isoformat()
    fresh_heartbeat = (now - timedelta(minutes=2)).isoformat()
    path = _write_batch(
        host_batches_dir,
        "batch-heartbeat",
        {
            "status": "in_progress",
            "has_todo": True,
            "started_at": long_ago,
            "updated_at": long_ago,
            "heartbeat_at": fresh_heartbeat,
            "completed_at": "",
            "worker_summary": "long-running scoring",
        },
    )

    recovered = reset_stale_in_progress_receipts(host_batches_dir, now=now)

    assert recovered == []
    receipt = json.loads(path.read_text())["receipt"]
    assert receipt["status"] == "in_progress"
    assert receipt["heartbeat_at"] == fresh_heartbeat


def test_explicit_stale_after_minutes_overrides_env(
    host_batches_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests that pass a hard-coded stale_after_minutes must not be perturbed
    by environments that happen to have VNEXT_STALE_MINUTES set."""
    monkeypatch.setenv("VNEXT_STALE_MINUTES", "1")
    now = datetime(2026, 4, 18, 12, 0, 0)
    started = (now - timedelta(minutes=10)).isoformat()
    _write_batch(
        host_batches_dir,
        "batch-explicit",
        {
            "status": "in_progress",
            "has_todo": True,
            "started_at": started,
            "updated_at": started,
            "completed_at": "",
            "worker_summary": "scoring",
        },
    )

    # Explicit threshold (60min) is stricter than env (1min) → batch stays.
    recovered = reset_stale_in_progress_receipts(
        host_batches_dir, now=now, stale_after_minutes=60
    )
    assert recovered == []


def test_env_var_lowers_stale_threshold_when_no_explicit_arg(
    host_batches_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VNEXT_STALE_MINUTES lets oncall tighten the reaper without code changes."""
    monkeypatch.setenv("VNEXT_STALE_MINUTES", "5")
    now = datetime(2026, 4, 18, 12, 0, 0)
    started = (now - timedelta(minutes=10)).isoformat()
    _write_batch(
        host_batches_dir,
        "batch-env",
        {
            "status": "in_progress",
            "has_todo": True,
            "started_at": started,
            "updated_at": started,
            "completed_at": "",
            "worker_summary": "scoring",
        },
    )

    # 10min > 5min env threshold → reaped, even though default would be 30min.
    recovered = reset_stale_in_progress_receipts(host_batches_dir, now=now)
    assert recovered == ["batch-env"]


def test_corrupt_batch_file_does_not_block_other_recoveries(host_batches_dir: Path) -> None:
    """One garbage file in the directory must not poison the whole sweep —
    other stale batches should still get recovered."""
    now = datetime(2026, 4, 18, 12, 0, 0)
    stale = (now - timedelta(minutes=STALE_IN_PROGRESS_MINUTES + 5)).isoformat()

    bad = host_batches_dir / "batch-bad-output.json"
    bad.write_text("not valid json{{{", encoding="utf-8")

    _write_batch(
        host_batches_dir,
        "batch-good",
        {
            "status": "in_progress",
            "has_todo": True,
            "started_at": stale,
            "updated_at": stale,
            "completed_at": "",
            "worker_summary": "scoring",
        },
    )

    recovered = reset_stale_in_progress_receipts(host_batches_dir, now=now)

    assert recovered == ["batch-good"]


def test_recovery_returns_batches_in_sorted_order(host_batches_dir: Path) -> None:
    """Output ordering must be deterministic so dispatch logs are reproducible."""
    now = datetime(2026, 4, 18, 12, 0, 0)
    stale = (now - timedelta(minutes=STALE_IN_PROGRESS_MINUTES + 1)).isoformat()
    receipt = {
        "status": "in_progress",
        "has_todo": True,
        "started_at": stale,
        "updated_at": stale,
        "completed_at": "",
        "worker_summary": "scoring",
    }
    for batch_id in ("batch-c", "batch-a", "batch-b"):
        _write_batch(host_batches_dir, batch_id, dict(receipt))

    recovered = reset_stale_in_progress_receipts(host_batches_dir, now=now)

    assert recovered == ["batch-a", "batch-b", "batch-c"]


def test_worker_completing_between_reads_is_not_overwritten(
    host_batches_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Race: the reaper sees in_progress on the first read, but between the
    decision and the rewrite, the worker writes status=completed. The reaper
    must NOT clobber that to pending — the second read guards against it."""
    from host_batching import _read_json as _real_read_json
    import host_batching

    now = datetime(2026, 4, 18, 12, 0, 0)
    stale = (now - timedelta(minutes=STALE_IN_PROGRESS_MINUTES + 5)).isoformat()
    path = _write_batch(
        host_batches_dir,
        "batch-race",
        {
            "status": "in_progress",
            "has_todo": True,
            "started_at": stale,
            "updated_at": stale,
            "completed_at": "",
            "worker_summary": "scoring",
        },
    )

    call_count = {"n": 0}

    def racing_read_json(target: Path, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2 and Path(target) == path:
            # Second read = the safety re-check; simulate the worker having
            # finished the batch in the meantime.
            payload = _real_read_json(target, *args, **kwargs)
            payload["receipt"]["status"] = "completed"
            payload["receipt"]["completed_at"] = now.isoformat()
            payload["receipt"]["has_todo"] = False
            payload["receipt"]["worker_summary"] = "completed by worker"
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return payload
        return _real_read_json(target, *args, **kwargs)

    monkeypatch.setattr(host_batching, "_read_json", racing_read_json)

    recovered = reset_stale_in_progress_receipts(host_batches_dir, now=now)

    assert recovered == []
    receipt = json.loads(path.read_text())["receipt"]
    assert receipt["status"] == "completed"
    assert receipt["worker_summary"] == "completed by worker"


def test_recovery_does_not_double_prefix_marker_on_re_stale(host_batches_dir: Path) -> None:
    """If a recovered batch goes stale again, the marker should not stack —
    'recovered: recovered: scoring' is noise."""
    now = datetime(2026, 4, 18, 12, 0, 0)
    stale = (now - timedelta(minutes=STALE_IN_PROGRESS_MINUTES + 1)).isoformat()
    path = _write_batch(
        host_batches_dir,
        "batch-restale",
        {
            "status": "in_progress",
            "has_todo": True,
            "started_at": stale,
            "updated_at": stale,
            "completed_at": "",
            # Already carries the marker from a prior recovery.
            "worker_summary": f"{STALE_RECOVERY_MARKER}scoring",
        },
    )

    recovered = reset_stale_in_progress_receipts(host_batches_dir, now=now)

    assert recovered == ["batch-restale"]
    summary = json.loads(path.read_text())["receipt"]["worker_summary"]
    # Marker appears exactly once.
    assert summary.count(STALE_RECOVERY_MARKER) == 1
    assert "scoring" in summary
