#!/usr/bin/env python3
from __future__ import annotations

from typing import Dict

from audiovisual.routing.features import _infer_language_function, _infer_relation, _infer_visual_function, _scene_dimension_scores
from audiovisual.routing.infer import infer_audiovisual_route, infer_content_profile
from audiovisual.shared import _safe_text, _voiceover


def _apply_external_classification_route(data: Dict) -> bool:
    classification_result = data.get("classification_result") or {}
    if not isinstance(classification_result, dict):
        return False

    route = dict(classification_result.get("applied_route") or {})
    if not isinstance(route, dict) or not _safe_text(route.get("framework")):
        return False

    classification = classification_result.get("classification") or {}
    if isinstance(classification, dict):
        route.setdefault("child_type", _safe_text(classification.get("type")))
        route.setdefault("child_type_cn", _safe_text(classification.get("type_cn")))

    data["content_profile"] = dict(route.get("content_profile") or {})
    data["audiovisual_route"] = route
    return True


def enrich_audiovisual_layers(data: Dict) -> Dict:
    title = _safe_text(data.get("title") or data.get("video_title") or data.get("video_id"))
    for scene in data.get("scenes", []):
        scene["content_analysis"] = {
            "visual_function": _infer_visual_function(scene),
            "language_function": _infer_language_function(_voiceover(scene), title),
            "audio_visual_relation": _infer_relation(scene, title),
        }
        scene["analysis_dimensions"] = _scene_dimension_scores(scene)
    if _apply_external_classification_route(data):
        return data
    existing_route = data.get("audiovisual_route") or {}
    if isinstance(existing_route, dict) and _safe_text(existing_route.get("framework")):
        if isinstance(existing_route.get("content_profile"), dict) and existing_route.get("content_profile"):
            data["content_profile"] = dict(existing_route.get("content_profile") or {})
        elif not isinstance(data.get("content_profile"), dict) or not data.get("content_profile"):
            data["content_profile"] = infer_content_profile(data)
        data["audiovisual_route"] = dict(existing_route)
        return data
    data["content_profile"] = infer_content_profile(data)
    data["audiovisual_route"] = infer_audiovisual_route(data)
    return data
