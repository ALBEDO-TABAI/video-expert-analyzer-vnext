from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audiovisual.reporting.template_engine import _assemble_final_report


def test_missing_sections_drops_validation_errors_json(tmp_path: Path) -> None:
    agent_text = "## A\n内容 A\n"

    with pytest.raises(ValueError, match="Missing required sections"):
        _assemble_final_report(
            agent_text,
            context={"generated_at": "2026-04-20 10:00:00"},
            python_direct_blocks=[],
            data={"audiovisual_route": {}},
            route={},
            report_dir=tmp_path,
            required_sections=("## A", "## B"),
            source="template",
            validation_rules={},
        )

    sidecar = tmp_path / "audiovisual_handoff" / "body" / "validation_errors.json"
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "## B" in payload["missing_sections"]
    assert "## A" in payload["present_sections"]
    assert "Missing required sections" in payload["error"]
