#!/usr/bin/env python3
"""Pure scene-helper utilities shared by `common` and `template_engine`.

These helpers operate on scene dicts only — they do not touch voiceover
reliability heuristics, so they can be imported anywhere without pulling
in the larger reporting graph.
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from audiovisual.routing.features import _looks_like_promo_card
from audiovisual.shared import (
    _analysis_rows,
    _safe_text,
    _scene_desc,
    _scene_screenshot,
)


def _scene_refs(scenes: Sequence[Dict], limit: int = 5) -> str:
    refs = []
    for scene in scenes[:limit]:
        num = int(scene.get("scene_number", 0))
        if num > 0:
            refs.append(f"Scene {num:03d}")
    return "、".join(refs) if refs else "暂无明确场景"


def _scene_priority(scene: Dict, *, prefer_impact: bool = False) -> float:
    weighted = float(scene.get("weighted_score") or 0.0)
    impact = float(scene.get("scores", {}).get("impact") or 0.0)
    memorability = float(scene.get("scores", {}).get("memorability") or 0.0)
    shot_size = _safe_text(scene.get("storyboard", {}).get("shot_size"))
    description = _scene_desc(scene)

    score = weighted + impact * 1.2 + memorability * 0.7
    if prefer_impact:
        score += impact * 0.8
    if _looks_like_promo_card(scene):
        score -= 3.0
    if any(word in shot_size for word in ("黑场", "字幕卡", "片名卡", "信息卡")):
        score -= 2.5
    if any(word in description for word in ("纯黑", "黑底")):
        score -= 2.0
    if not _scene_screenshot(scene):
        score -= 5.0
    return score


def _best_representative_scene(scenes: Sequence[Dict], *, prefer_impact: bool = False) -> Dict | None:
    candidates = [scene for scene in scenes if _scene_screenshot(scene)]
    if not candidates:
        return scenes[0] if scenes else None
    return sorted(candidates, key=lambda scene: _scene_priority(scene, prefer_impact=prefer_impact), reverse=True)[0]


def _best_unique_scene(scenes: Sequence[Dict], seen: set[int], *, prefer_impact: bool = False) -> Dict | None:
    candidates = [scene for scene in scenes if _scene_screenshot(scene)]
    ranked = sorted(candidates, key=lambda scene: _scene_priority(scene, prefer_impact=prefer_impact), reverse=True)
    for scene in ranked:
        scene_number = int(scene.get("scene_number", 0))
        if scene_number not in seen:
            return scene
    return None


def _best_scene_refs(scenes: Sequence[Dict], limit: int = 3, *, prefer_impact: bool = False) -> str:
    ranked = sorted(scenes, key=lambda scene: _scene_priority(scene, prefer_impact=prefer_impact), reverse=True)
    return _scene_refs(ranked, limit)


def _scene_phrase(
    scenes: Sequence[Dict],
    limit: int = 2,
    max_length: int = 24,
    *,
    default: str = "",
) -> str:
    parts = [_scene_desc(scene)[:max_length] for scene in scenes[:limit] if _scene_desc(scene)]
    return " / ".join(parts) if parts else default


def _best_scene_phrase(
    scenes: Sequence[Dict],
    limit: int = 2,
    max_length: int = 24,
    *,
    prefer_impact: bool = False,
    default: str = "",
) -> str:
    ranked = sorted(scenes, key=lambda scene: _scene_priority(scene, prefer_impact=prefer_impact), reverse=True)
    return _scene_phrase(ranked, limit=limit, max_length=max_length, default=default)


def _pick_unique_best_scenes(
    seen: set[int],
    scenes: Sequence[Dict],
    limit: int = 2,
    *,
    prefer_impact: bool = False,
) -> List[Dict]:
    ranked = sorted(scenes, key=lambda scene: _scene_priority(scene, prefer_impact=prefer_impact), reverse=True)
    picked: List[Dict] = []
    for scene in ranked:
        scene_number = int(scene.get("scene_number", 0))
        if scene_number in seen:
            continue
        seen.add(scene_number)
        picked.append(scene)
        if len(picked) >= limit:
            break
    return picked


def _ordered_scenes(data: Dict) -> List[Dict]:
    return _analysis_rows(data)
