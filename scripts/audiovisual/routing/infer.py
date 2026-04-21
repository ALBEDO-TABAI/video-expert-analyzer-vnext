#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Dict, List, Optional

from audiovisual.routing.features import (
    _apply_profile_route_overrides,
    _base_route_from_axes,
    _build_route_context,
    _count_pattern_hits,
    _has_commentary_intent,
    _has_music_intent,
    _infer_audio_axis,
    _infer_dual_layer,
    _infer_visual_axis,
)
from audiovisual.routing.constants import (
    GRAPHIC_INTENT_MIN_HITS,
    HIGH_FUN_SCORE,
    PROFILE_DIALOGUE_UPPER_BOUND,
    PROFILE_NARRATIVE_MIN_SCORE,
    PROFILE_PROMO_MAX_SCORE,
    PROFILE_TECHNICAL_MARGIN,
    PROFILE_TECHNICAL_MIN_SCORE,
    PROFILE_TRAILER_PROMO_MIN_SCORE,
    PROFILE_VOICEOVER_HIGH_RATIO,
    PROFILE_VOICEOVER_LOW_RATIO,
    PROFILE_VOICEOVER_MEDIUM_RATIO,
)
from audiovisual.shared import _onscreen_text

from audiovisual.shared import _onscreen_text


def _check(name: str, value: Any, op: str, threshold: Any) -> Dict[str, Any]:
    if op == ">=":
        hit = value >= threshold
    elif op == "<=":
        hit = value <= threshold
    elif op == ">":
        hit = value > threshold
    elif op == "<":
        hit = value < threshold
    elif op == "==":
        hit = value == threshold
    elif op == "is":
        hit = bool(value) is bool(threshold)
    elif op == "any_keyword":
        hit = any(keyword in value for keyword in threshold)
    else:
        hit = False
    return {"name": name, "op": op, "value": value, "threshold": threshold, "hit": hit}


def _record_branch(branches: List[Dict[str, Any]], key: str, conditions: List[Dict[str, Any]]) -> bool:
    hit = all(cond.get("hit") for cond in conditions) if conditions else False
    branches.append({"key": key, "hit": hit, "conditions": conditions})
    return hit


_PROFILE_CATALOG = {
    "commentary_analysis": ("评论解析", "标题和画面都更像在围绕现成素材做判断、举证和解释。"),
    "documentary_observation": ("纪实观察", "标题和画面都更像在跟着真实人物、真实现场往前走。"),
    "meme_clip": ("梗视频", "这条内容更靠反差动作、字幕梗和即时反应来打人。"),
    "graphic_explainer": ("信息图讲解", "画面本身就在用图形、箭头和结构示意帮语言一起解释内容。"),
    "technical_explainer": ("技术讲解", "语言里持续出现解释、步骤和原理信号，整体更像在讲清一件事。"),
    "event_brand_ad": ("活动/品牌广告", "标题和画面共同指向品牌活动表达。"),
    "travel_short": ("旅行短片", "标题和画面主题都以旅程体验为中心。"),
    "music_video": ("音乐视频", "标题和文本线索都更接近音乐内容。"),
    "narrative_trailer": (
        "剧情预告",
        "它既有明确的故事推进，又带着清楚的预告标题或上映收口信号，更像在提前卖一个故事前提和高能瞬间。",
    ),
    "generic": ("通用视频", "暂未检测到更明确的内容画像。"),
}


def _evaluate_profile_branches(
    *,
    title: str,
    rows: list,
    visual_text: str,
    signals: Dict[str, float],
    avg_fun: float,
    avg_credibility: float,
    graphic_intent: int,
    music_intent: bool,
    commentary_intent: bool,
) -> List[Dict[str, Any]]:
    """Evaluate each profile branch and record per-condition hit data.

    OR-style branches use a list of sub-condition groups; the branch hits
    when any group passes. Each condition records (name, op, value,
    threshold, hit) so a misroute can be traced to the exact threshold.
    """
    branches: List[Dict[str, Any]] = []

    branches.append({
        "key": "commentary_analysis",
        "groups": [[
            _check("commentary_intent", commentary_intent, "is", True),
            _check("voiceover_ratio", signals["voiceover_ratio"], ">=", 0.5),
            _check("music_intent", music_intent, "is", False),
        ]],
    })
    branches.append({
        "key": "documentary_observation",
        "groups": [
            [_check("title_keywords", title, "any_keyword", ("纪录", "纪实", "跟拍", "实录"))],
            [
                _check("avg_credibility", avg_credibility, ">=", 8.0),
                _check("technical_signal", signals["technical"], "<", PROFILE_TECHNICAL_MIN_SCORE),
                _check("voiceover_ratio", signals["voiceover_ratio"], ">=", PROFILE_VOICEOVER_LOW_RATIO),
                _check(
                    "visual_keywords",
                    visual_text,
                    "any_keyword",
                    ("码头", "现场", "街头", "采访", "出海", "记录", "工地", "工作"),
                ),
            ],
        ],
    })
    has_onscreen = any(_onscreen_text(scene) for scene in rows)
    branches.append({
        "key": "meme_clip",
        "groups": [
            [
                _check("avg_fun", avg_fun, ">=", HIGH_FUN_SCORE),
                _check("voiceover_ratio", signals["voiceover_ratio"], "<=", PROFILE_VOICEOVER_MEDIUM_RATIO),
                _check("has_onscreen_text", has_onscreen, "is", True),
            ],
            [
                _check("avg_fun", avg_fun, ">=", HIGH_FUN_SCORE),
                _check(
                    "visual_keywords",
                    visual_text,
                    "any_keyword",
                    ("愣住", "爆笑", "反差", "监控", "猫", "狗", "表情"),
                ),
            ],
        ],
    })
    branches.append({
        "key": "graphic_explainer",
        "groups": [[
            _check("graphic_intent", graphic_intent, ">=", GRAPHIC_INTENT_MIN_HITS),
            _check("voiceover_ratio", signals["voiceover_ratio"], ">=", PROFILE_VOICEOVER_MEDIUM_RATIO),
        ]],
    })
    branches.append({
        "key": "technical_explainer",
        "groups": [
            [
                _check("technical_signal", signals["technical"], ">=", PROFILE_TECHNICAL_MIN_SCORE),
                _check("promo_signal", signals["promo"], "<=", PROFILE_PROMO_MAX_SCORE),
                _check(
                    "technical_margin",
                    signals["technical"] - signals["narrative"],
                    ">=",
                    PROFILE_TECHNICAL_MARGIN,
                ),
            ],
            [
                _check("technical_signal", signals["technical"], ">=", PROFILE_TECHNICAL_MIN_SCORE),
                _check("promo_signal", signals["promo"], "<=", PROFILE_PROMO_MAX_SCORE),
                _check("voiceover_ratio", signals["voiceover_ratio"], ">=", PROFILE_VOICEOVER_HIGH_RATIO),
                _check(
                    "explanatory_or_question_lines",
                    max(signals["explanatory_lines"], signals["question_lines"]),
                    ">=",
                    1.0,
                ),
                _check("dialogue_like", signals["dialogue_like"], "<=", PROFILE_DIALOGUE_UPPER_BOUND),
            ],
        ],
    })
    branches.append({
        "key": "event_brand_ad",
        "groups": [
            [_check("title_keywords", title, "any_keyword", ("cm", "广告", "campaign", "brand"))],
            [
                _check("title_has_chorus", "大合唱" in title, "is", True),
                _check("visual_has_crowd", "人群" in visual_text, "is", True),
            ],
        ],
    })
    branches.append({
        "key": "travel_short",
        "groups": [[_check("title_keywords", title, "any_keyword", ("journey", "travel", "trip", "旅程"))]],
    })
    branches.append({
        "key": "music_video",
        "groups": [[_check("music_intent", music_intent, "is", True)]],
    })
    branches.append({
        "key": "narrative_trailer",
        "groups": [[
            _check("narrative_signal", signals["narrative"], ">=", PROFILE_NARRATIVE_MIN_SCORE),
            _check("promo_signal", signals["promo"], ">=", PROFILE_TRAILER_PROMO_MIN_SCORE),
            _check(
                "trailer_or_release",
                max(signals["trailer_title_hits"], signals["release_cards"]),
                ">=",
                1.0,
            ),
        ]],
    })

    for branch in branches:
        groups = branch.pop("groups")
        branch["conditions"] = [c for group in groups for c in group]
        branch["hit"] = any(all(c["hit"] for c in group) for group in groups)
    return branches


def infer_content_profile(data: Dict, context: Optional[Dict[str, object]] = None) -> Dict[str, str]:
    context = context or _build_route_context(data)
    title = str(context["title_lower"])
    rows = list(context["rows"])
    onscreen_text = " ".join(str(text) for text in context["onscreen_texts"]).lower()
    visual_text = " ".join(str(text) for text in context["descriptions"]).lower()
    signals = dict(context["signals"])
    avg_fun = float(context["avg_fun"])
    avg_credibility = float(context["avg_credibility"])
    graphic_intent = _count_pattern_hits(
        " ".join([title, visual_text, onscreen_text]),
        (r"信息图", r"图解", r"箭头", r"图标", r"示意", r"动画", r"graphic", r"diagram", r"heat", r"fan", r"sink", r"pipe"),
    )
    music_intent = _has_music_intent(data)
    commentary_intent = _has_commentary_intent(title, visual_text)

    branches = _evaluate_profile_branches(
        title=title,
        rows=rows,
        visual_text=visual_text,
        signals=signals,
        avg_fun=avg_fun,
        avg_credibility=avg_credibility,
        graphic_intent=graphic_intent,
        music_intent=music_intent,
        commentary_intent=commentary_intent,
    )
    selected_key = next((b["key"] for b in branches if b["hit"]), "generic")
    label, reason = _PROFILE_CATALOG[selected_key]

    trace = {
        "selected": selected_key,
        "branches": branches,
        "signals": {
            **{k: v for k, v in signals.items()},
            "avg_fun": avg_fun,
            "avg_credibility": avg_credibility,
            "graphic_intent": graphic_intent,
            "music_intent": music_intent,
            "commentary_intent": commentary_intent,
        },
    }
    data["_content_profile_trace"] = trace
    return {"key": selected_key, "label": label, "reason": reason}



def infer_audiovisual_route(data: Dict) -> Dict[str, object]:
    context = _build_route_context(data)
    profile = infer_content_profile(data, context=context)
    data["content_profile"] = profile
    visual = _infer_visual_axis(data, context=context)
    audio = _infer_audio_axis(data, context=context)
    route = _base_route_from_axes(data, visual, audio)
    route = _apply_profile_route_overrides(route, profile, data)
    route["dual_layer"] = _infer_dual_layer(route, data, context=context)
    route["visual_rationale"] = visual["rationale"]
    route["visual_confidence"] = visual.get("confidence", 0.0)
    route["audio_rationale"] = audio["rationale"]
    route["voiceover_ratio"] = audio["voiceover_ratio"]
    route["content_profile"] = profile
    if profile["key"] == "event_brand_ad":
        route["dual_layer"] = {
            "enabled": True,
            "primary": "节庆氛围层",
            "secondary": "品牌记忆层",
            "reason": "它一边在放大现场气氛和群体共鸣，一边把品牌符号稳稳钉在所有人的记忆里。",
        }
    elif profile["key"] == "travel_short":
        route["dual_layer"] = {
            "enabled": True,
            "primary": "旅程体验层",
            "secondary": "品牌气质层",
            "reason": "它表面在带人上路，底层在慢慢把品牌气质、人物状态和地点意象揉成同一股感觉。",
        }
    elif profile["key"] == "technical_explainer":
        route["dual_layer"] = {
            "enabled": True,
            "primary": "信息解释层",
            "secondary": "观看快感层",
            "reason": "它一边在把复杂动作或原理讲清楚，一边也在用慢放、顶视和细节镜头给观众看懂之后的爽感。",
        }
    elif profile["key"] == "narrative_trailer":
        if not route["dual_layer"].get("enabled"):
            route["dual_layer"] = {
                "enabled": True,
                "primary": "故事前提层",
                "secondary": "发行传播层",
                "reason": "它既要把故事前提和危险感卖出去，也要在结尾把片名、档期和品牌记忆钉住。",
            }
    route["fallback"] = route["framework"] == "experimental"
    trace = data.pop("_content_profile_trace", None)
    if trace:
        route["routing_trace"] = trace
    return route

