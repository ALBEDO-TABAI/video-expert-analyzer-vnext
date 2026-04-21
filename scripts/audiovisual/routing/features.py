#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
import re
from typing import Dict, List, Optional, Sequence

from audiovisual.routing.constants import (
    AUDIO_AXIS_LABELS,
    AUDIO_AXIS_TIE_DELTA,
    AUDIO_COMPLEMENTARY_L_WEIGHT,
    AUDIO_COUNTERPOINT_LM_WEIGHT,
    AUDIO_COUNTERPOINT_M_WEIGHT,
    AUDIO_FORCE_WEAK_RATIO,
    AUDIO_INFORMATION_FUNCTION_WEIGHT,
    AUDIO_LANGUAGE_TITLE_WEIGHT,
    AUDIO_LM_BALANCED_VOICEOVER_WEIGHT,
    AUDIO_LM_DIALOGUE_RATIO,
    AUDIO_LM_MUSIC_FUNCTION_WEIGHT,
    AUDIO_LM_MUSIC_TITLE_WEIGHT,
    AUDIO_LM_NARRATIVE_FUNCTION_WEIGHT,
    AUDIO_LM_VOICEOVER_RATIO,
    AUDIO_LOW_VOICEOVER_MUSIC_WEIGHT,
    AUDIO_MEME_TITLE_WEIGHT,
    AUDIO_MUSIC_DIALOGUE_WEIGHT,
    AUDIO_MUSIC_FUNCTION_WEIGHT,
    AUDIO_MUSIC_TITLE_WEIGHT,
    AUDIO_NARRATIVE_FUNCTION_WEIGHT,
    AUDIO_TECHNICAL_LANGUAGE_WEIGHT,
    AUDIO_TRAILER_BALANCED_VOICEOVER_WEIGHT,
    AUDIO_TRAILER_LM_WEIGHT,
    AUDIO_TRAILER_NONVOICE_LM_WEIGHT,
    AUDIO_TRAILER_NONVOICE_M_WEIGHT,
    AUDIO_VOICEOVER_RATIO_WEIGHT,
    AUDIO_WEAK_AUDIO_WEIGHT,
    AUDIO_WEAK_PARTICIPATION_RATIO,
    COMMENTARY_TITLE_KEYWORDS,
    COMMENTARY_VISUAL_KEYWORDS,
    EXPLANATORY_PATTERNS,
    HIGH_IMPACT_SCORE,
    MUSIC_INTENT_PATTERNS,
    NARRATIVE_AUTHORED_BONUS,
    NARRATIVE_AUTHORED_RATIO,
    NARRATIVE_DIALOGUE_BONUS,
    NARRATIVE_DIALOGUE_RATIO,
    NARRATIVE_NONVOICE_BONUS,
    NARRATIVE_NONVOICE_RATIO,
    NARRATIVE_SCENE_BONUS,
    NARRATIVE_SCENE_RATIO,
    PROMO_CARD_SIGNAL_BONUS,
    PROMO_COMMERCIAL_SIGNAL_BONUS,
    PROMO_RELEASE_SIGNAL_BONUS,
    PROMO_TITLE_SIGNAL_BONUS,
    RELEASE_TEXT_PATTERNS,
    ROUTE_FRAMEWORKS,
    TECHNICAL_DIALOGUE_LIGHT_BONUS,
    TECHNICAL_DIALOGUE_LIGHT_RATIO,
    TECHNICAL_EXPLANATORY_HIT_MIN,
    TECHNICAL_EXPLANATORY_LINE_BONUS,
    TECHNICAL_EXPLANATORY_LINE_RATIO,
    TECHNICAL_EXPLANATORY_SIGNAL_BONUS,
    TECHNICAL_TITLE_SIGNAL_BONUS,
    TRAILER_TITLE_PATTERNS,
    VISUAL_ACTION_KEYWORD_WEIGHT,
    VISUAL_ATMOSPHERE_P_WEIGHT,
    VISUAL_ATMOSPHERE_R_WEIGHT,
    VISUAL_AUTHORED_WEIGHT,
    VISUAL_AXIS_LABELS,
    VISUAL_COLOR_GRADING_WEIGHT,
    VISUAL_COMMERCIAL_WEIGHT,
    VISUAL_INFORMATION_WEIGHT,
    VISUAL_LOW_CONFIDENCE,
    VISUAL_MIX_DELTA,
    VISUAL_MIX_MIN_SCORE,
    VISUAL_MOVEMENT_WEIGHT,
    VISUAL_NARRATIVE_WEIGHT,
    VISUAL_SCENE_KEYWORD_WEIGHT,
    VISUAL_STYLE_CONSISTENCY_D_WEIGHT,
    VISUAL_STYLE_CONSISTENCY_P_WEIGHT,
    VISUAL_TECHNICAL_PROFILE_WEIGHT,
    VISUAL_TITLE_KEYWORD_WEIGHT,
    VISUAL_TRAILER_PROFILE_WEIGHT,
    VISUAL_WIDE_SHOT_WEIGHT,
)
from audiovisual.shared import (
    _analysis_rows,
    _avg,
    _onscreen_text,
    _safe_text,
    _scene_desc,
    _title_text,
    _voiceover,
)

def _build_route_context(data: Dict) -> Dict[str, object]:
    title = _title_text(data)
    rows = _analysis_rows(data)
    voiceovers = [_voiceover(scene) for scene in rows if _voiceover(scene)]
    onscreen_texts = [_onscreen_text(scene) for scene in rows if _onscreen_text(scene)]
    descriptions = [_scene_desc(scene) for scene in rows if _scene_desc(scene)]
    return {
        "title": title,
        "title_lower": title.lower(),
        "rows": rows,
        "voiceovers": voiceovers,
        "onscreen_texts": onscreen_texts,
        "descriptions": descriptions,
        "signals": _compute_content_signals(
            data,
            rows=rows,
            title=title,
            voiceovers=voiceovers,
            onscreen_texts=onscreen_texts,
            descriptions=descriptions,
        ),
        "avg_fun": _avg([float(scene.get("scores", {}).get("fun_interest") or 0.0) for scene in rows]) if rows else 0.0,
        "avg_credibility": _avg([float(scene.get("scores", {}).get("credibility") or 0.0) for scene in rows]) if rows else 0.0,
    }


def _count_pattern_hits(text: str, patterns: Sequence[str]) -> int:
    lowered = text.lower()
    return sum(1 for pattern in patterns if re.search(pattern, lowered, re.IGNORECASE))


def _matches_any(text: str, patterns: Sequence[str]) -> bool:
    return _count_pattern_hits(text, patterns) > 0


def _text_units(text: str) -> int:
    if re.search(r"[\u4e00-\u9fff]", text):
        return len(re.sub(r"\s+", "", text))
    return len(re.findall(r"[A-Za-z0-9']+", text))


def _is_explanatory_line(text: str) -> bool:
    cleaned = _safe_text(text)
    if not cleaned:
        return False
    hits = _count_pattern_hits(cleaned, EXPLANATORY_PATTERNS)
    return hits >= 1 and _text_units(cleaned) >= 8


def _is_dialogue_like(text: str) -> bool:
    cleaned = _safe_text(text)
    if not cleaned or _is_explanatory_line(cleaned):
        return False
    return _text_units(cleaned) <= 14 or any(mark in cleaned for mark in ("?", "!", "？", "！"))


def _looks_like_release_text(text: str) -> bool:
    cleaned = _safe_text(text)
    if not cleaned:
        return False
    return _count_pattern_hits(cleaned, RELEASE_TEXT_PATTERNS) > 0


def _looks_like_promo_card(scene: Dict) -> bool:
    shot_size = _safe_text(scene.get("storyboard", {}).get("shot_size"))
    technique = _safe_text(scene.get("storyboard", {}).get("technique"))
    onscreen_text = _onscreen_text(scene)
    return (
        any(word in shot_size for word in ("字幕卡", "片名卡", "信息卡"))
        or any(word in technique for word in ("片名", "档期", "署名", "收口", "宣传"))
        or _looks_like_release_text(onscreen_text)
    )


def _compute_content_signals(
    data: Dict,
    *,
    rows: Optional[Sequence[Dict]] = None,
    title: Optional[str] = None,
    voiceovers: Optional[Sequence[str]] = None,
    onscreen_texts: Optional[Sequence[str]] = None,
    descriptions: Optional[Sequence[str]] = None,
) -> Dict[str, float]:
    rows = list(rows) if rows is not None else _analysis_rows(data)
    title = title if title is not None else _title_text(data)
    title_lower = title.lower()
    voiceovers = list(voiceovers) if voiceovers is not None else [_voiceover(scene) for scene in rows if _voiceover(scene)]
    onscreen_texts = list(onscreen_texts) if onscreen_texts is not None else [_onscreen_text(scene) for scene in rows if _onscreen_text(scene)]
    descriptions = list(descriptions) if descriptions is not None else [_scene_desc(scene) for scene in rows if _scene_desc(scene)]
    type_counter = Counter(_safe_text(scene.get("type_classification")) for scene in rows if _safe_text(scene.get("type_classification")))
    voiceover_ratio = len(voiceovers) / max(len(rows), 1)

    explanatory_hits = sum(_count_pattern_hits(text, EXPLANATORY_PATTERNS) for text in [title, *voiceovers, *onscreen_texts])
    dialogue_like = sum(1 for text in voiceovers if _is_dialogue_like(text))
    explanatory_lines = sum(1 for text in voiceovers if _is_explanatory_line(text))
    question_lines = sum(1 for text in voiceovers if any(mark in text for mark in ("?", "？", "为什么", "怎麼", "怎么", "如何")))
    promo_cards = sum(1 for scene in rows if _looks_like_promo_card(scene))
    release_cards = sum(1 for text in [title, *onscreen_texts] if _looks_like_release_text(text))
    trailer_title_hits = _count_pattern_hits(title_lower, TRAILER_TITLE_PATTERNS)
    narrative_scene_count = type_counter.get("TYPE-A Hook", 0) + type_counter.get("TYPE-B Narrative", 0)
    atmosphere_scene_count = type_counter.get("TYPE-C Aesthetic", 0)
    authored_scene_count = narrative_scene_count + atmosphere_scene_count
    non_voiceover_high_impact = sum(
        1
        for scene in rows
        if not _voiceover(scene) and float(scene.get("scores", {}).get("impact") or 0.0) >= HIGH_IMPACT_SCORE
    )

    technical_score = 0.0
    if _count_pattern_hits(title, EXPLANATORY_PATTERNS) > 0:
        technical_score += TECHNICAL_TITLE_SIGNAL_BONUS
    if explanatory_hits >= TECHNICAL_EXPLANATORY_HIT_MIN:
        technical_score += TECHNICAL_EXPLANATORY_SIGNAL_BONUS
    if explanatory_lines >= max(2, len(voiceovers) * TECHNICAL_EXPLANATORY_LINE_RATIO):
        technical_score += TECHNICAL_EXPLANATORY_LINE_BONUS
    if dialogue_like <= max(1, len(voiceovers) * TECHNICAL_DIALOGUE_LIGHT_RATIO):
        technical_score += TECHNICAL_DIALOGUE_LIGHT_BONUS

    narrative_score = 0.0
    if authored_scene_count >= max(2, len(rows) * NARRATIVE_AUTHORED_RATIO):
        narrative_score += NARRATIVE_AUTHORED_BONUS
    if narrative_scene_count >= max(2, len(rows) * NARRATIVE_SCENE_RATIO):
        narrative_score += NARRATIVE_SCENE_BONUS
    if dialogue_like >= max(2, len(voiceovers) * NARRATIVE_DIALOGUE_RATIO):
        narrative_score += NARRATIVE_DIALOGUE_BONUS
    if non_voiceover_high_impact >= max(1, len(rows) * NARRATIVE_NONVOICE_RATIO):
        narrative_score += NARRATIVE_NONVOICE_BONUS

    promo_score = 0.0
    if _count_pattern_hits(title_lower, TRAILER_TITLE_PATTERNS) > 0:
        promo_score += PROMO_TITLE_SIGNAL_BONUS
    if promo_cards >= 1:
        promo_score += PROMO_CARD_SIGNAL_BONUS
    if release_cards >= 1:
        promo_score += PROMO_RELEASE_SIGNAL_BONUS
    if type_counter.get("TYPE-D Commercial", 0) >= 1:
        promo_score += PROMO_COMMERCIAL_SIGNAL_BONUS

    return {
        "technical": technical_score,
        "narrative": narrative_score,
        "promo": promo_score,
        "explanatory_hits": explanatory_hits,
        "explanatory_lines": float(explanatory_lines),
        "question_lines": float(question_lines),
        "dialogue_like": float(dialogue_like),
        "promo_cards": float(promo_cards),
        "release_cards": float(release_cards),
        "trailer_title_hits": float(trailer_title_hits),
        "voiceover_ratio": voiceover_ratio,
        "non_voiceover_high_impact": float(non_voiceover_high_impact),
    }


def _has_music_intent(data: Dict) -> bool:
    title = _safe_text(data.get("title") or data.get("video_title") or data.get("video_id")).lower()
    return any(word in title for word in MUSIC_INTENT_PATTERNS)


def _has_commentary_intent(title: str, visual_text: str) -> bool:
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in COMMENTARY_TITLE_KEYWORDS) or any(
        keyword in visual_text for keyword in COMMENTARY_VISUAL_KEYWORDS
    )


def _has_commercial_intent(data: Dict) -> bool:
    title = _safe_text(data.get("title") or data.get("video_title") or data.get("video_id"))
    return any(word in title for word in ("广告", "品牌", "产品", "宣传", "发布", "种草"))


def _has_persona_intent(data: Dict) -> bool:
    title = _safe_text(data.get("title") or data.get("video_title") or data.get("video_id")).lower()
    return any(word in title for word in ("vlog", "日常", "一天", "我的", "跟我"))



def _infer_language_function(text: str, title: str) -> str:
    if not text:
        return "语言弱参与"
    if _has_music_intent({"title": title}) and len(text) >= 4:
        return "歌词抒情"
    if any(word in text for word in ("点击", "打开", "选择", "查看", "步骤", "需要")):
        return "指令说明"
    if any(word in text for word in ("原因", "结果", "因为", "所以", "问题", "信息")):
        return "信息说明"
    if any(word in text for word in ("突然", "后来", "终于", "发现", "原来")):
        return "叙事推进"
    return "表达补充"


def _infer_visual_function(scene: Dict) -> str:
    text = " ".join(
        [
            _scene_desc(scene),
            _safe_text(scene.get("storyboard", {}).get("shot_size")),
            _safe_text(scene.get("storyboard", {}).get("visual_style")),
            _safe_text(scene.get("storyboard", {}).get("technique")),
        ]
    )
    if any(word in text for word in ("特写", "表情", "眼神", "脸")):
        return "人物情绪呈现"
    if any(word in text for word in ("远景", "全景", "空间", "街景", "环境")):
        return "空间环境建立"
    if any(word in text for word in ("奔跑", "走", "追", "打开", "冲出", "举起", "对峙")):
        return "动作行为推进"
    if any(word in text for word in ("氛围", "逆光", "剪影", "暖色", "冷色", "质感")):
        return "氛围质感营造"
    return "信息与状态交代"


def _infer_relation(scene: Dict, title: str) -> str:
    voiceover = _voiceover(scene)
    if not voiceover:
        return "视觉主导"
    visual = _scene_desc(scene) + _safe_text(scene.get("storyboard", {}).get("visual_style"))
    if any(word and word in visual and word in voiceover for word in ("爱", "梦", "夜", "光", "心", "自由")):
        return "强化"
    if any(word in voiceover for word in ("因为", "所以", "结果", "发现", "步骤", "点击")):
        return "互补"
    if any(word in visual for word in ("欢笑", "庆祝", "明亮")) and any(word in voiceover for word in ("孤独", "痛", "黑夜")):
        return "对位"
    if _has_music_intent({"title": title}):
        return "互补"
    return "互补"


def _scene_dimension_scores(scene: Dict) -> Dict[str, float]:
    scores = scene.get("scores", {})
    weighted = float(scene.get("weighted_score") or 0.0)
    aesthetic = float(scores.get("aesthetic_beauty") or 0.0)
    credibility = float(scores.get("credibility") or 0.0)
    impact = float(scores.get("impact") or 0.0)
    memorability = float(scores.get("memorability") or 0.0)
    fun_interest = float(scores.get("fun_interest") or 0.0)
    voiceover = _voiceover(scene)
    duration = max(float(scene.get("duration_seconds") or 0.0), 1.0)
    info_density = min(len(voiceover.replace(" ", "")) / duration / 6.0 * 10.0, 10.0) if voiceover else weighted
    return {
        "technical_quality": round((aesthetic + credibility) / 2.0, 2),
        "narrative_function": round((credibility * 0.35 + memorability * 0.30 + impact * 0.35), 2),
        "emotional_effect": round((impact * 0.6 + memorability * 0.4), 2),
        "information_efficiency": round((info_density * 0.55 + weighted * 0.45), 2),
        "clip_usability": round((weighted * 0.7 + fun_interest * 0.3), 2),
    }


def _infer_visual_axis(data: Dict, context: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    context = context or _build_route_context(data)
    title = str(context["title"])
    title_lower = str(context["title_lower"])
    scenes = list(context["rows"])
    profile = data.get("content_profile") or infer_content_profile(data, context=context)
    scores = {"R": 0.0, "P": 0.0, "S": 0.0, "D": 0.0}

    # 标题关键词（权重降至40%）
    if any(word in title_lower or word in title for word in ("mv", "剧情", "短片", "广告", "品牌", "宣传", "官方mv")):
        scores["P"] += VISUAL_TITLE_KEYWORD_WEIGHT
    if any(word in title_lower or word in title for word in ("纪录", "访谈", "采访", "新闻", "vlog", "日常", "教程")):
        scores["R"] += VISUAL_TITLE_KEYWORD_WEIGHT
    if any(word in title_lower or word in title for word in ("混剪", "amv", "鬼畜", "游戏", "影视", "电影", "电视剧", "动漫", "解说", "影评")):
        scores["S"] += VISUAL_TITLE_KEYWORD_WEIGHT
    if any(word in title_lower or word in title for word in ("动态", "动效", "mg", "图形", "排版", "设计", "抽象")):
        scores["D"] += VISUAL_TITLE_KEYWORD_WEIGHT

    # 场景内容分析（权重提升至60%）
    joined = "\n".join(_scene_desc(scene) for scene in scenes)
    if any(word in joined for word in ("歌者", "侦探", "嫌疑人", "角色", "舞台", "表演")):
        scores["P"] += VISUAL_SCENE_KEYWORD_WEIGHT
    if any(word in joined for word in ("采访", "实拍", "记录", "现场", "教程")):
        scores["R"] += VISUAL_SCENE_KEYWORD_WEIGHT
    if any(word in joined for word in ("原片", "素材", "片段", "游戏", "电影", "动漫")):
        scores["S"] += VISUAL_SCENE_KEYWORD_WEIGHT
    if any(word in joined for word in ("图形", "字效", "排版", "抽象")):
        scores["D"] += VISUAL_SCENE_KEYWORD_WEIGHT

    # 视觉功能分布分析
    visual_funcs = [_infer_visual_function(scene) for scene in scenes]
    func_counter = Counter(visual_funcs)
    type_counter = Counter(_safe_text(scene.get("type_classification")) for scene in scenes if _safe_text(scene.get("type_classification")))
    authored_scenes = type_counter.get("TYPE-A Hook", 0) + type_counter.get("TYPE-B Narrative", 0) + type_counter.get("TYPE-C Aesthetic", 0)
    if authored_scenes >= len(scenes) * 0.6:
        scores["P"] += VISUAL_AUTHORED_WEIGHT
    if type_counter.get("TYPE-A Hook", 0) + type_counter.get("TYPE-B Narrative", 0) >= len(scenes) * 0.45:
        scores["P"] += VISUAL_NARRATIVE_WEIGHT
    if type_counter.get("TYPE-D Commercial", 0) >= 1 and type_counter.get("TYPE-D Commercial", 0) <= len(scenes) * 0.25 and authored_scenes >= len(scenes) * 0.5:
        scores["P"] += VISUAL_COMMERCIAL_WEIGHT
    if func_counter.get("空间环境建立", 0) + func_counter.get("氛围质感营造", 0) >= len(scenes) * 0.4:
        scores["P"] += VISUAL_ATMOSPHERE_P_WEIGHT
        scores["R"] += VISUAL_ATMOSPHERE_R_WEIGHT
    if func_counter.get("信息与状态交代", 0) >= len(scenes) * 0.5:
        scores["R"] += VISUAL_INFORMATION_WEIGHT

    # storyboard特征分析
    shot_sizes = [_safe_text(s.get("storyboard", {}).get("shot_size")) for s in scenes]
    movements = [_safe_text(s.get("storyboard", {}).get("camera_movement")) for s in scenes]
    if any("特写" in s or "中景" in s for s in shot_sizes) and len([m for m in movements if m and m != "静止"]) >= len(scenes) * 0.3:
        scores["P"] += VISUAL_MOVEMENT_WEIGHT
    if any("远景" in s or "全景" in s for s in shot_sizes):
        scores["R"] += VISUAL_WIDE_SHOT_WEIGHT

    # 动作类型检测
    action_keywords = {"表演": "P", "记录": "R", "设计": "D", "素材": "S"}
    for keyword, axis in action_keywords.items():
        if joined.count(keyword) >= 2:
            scores[axis] += VISUAL_ACTION_KEYWORD_WEIGHT

    # 视觉风格一致性检测
    aesthetics = [float(s.get("scores", {}).get("aesthetic_beauty") or 0.0) for s in scenes if s.get("scores")]
    if aesthetics and len(aesthetics) >= 3:
        variance = sum((x - _avg(aesthetics)) ** 2 for x in aesthetics) / len(aesthetics)
        if variance < 1.5:  # 低方差=风格统一
            scores["P"] += VISUAL_STYLE_CONSISTENCY_P_WEIGHT
            scores["D"] += VISUAL_STYLE_CONSISTENCY_D_WEIGHT

    # color_grading一致性
    gradings = [_safe_text(s.get("storyboard", {}).get("color_grading")) for s in scenes]
    grading_counter = Counter(g for g in gradings if g)
    if grading_counter and grading_counter.most_common(1)[0][1] >= len(scenes) * 0.6:
        scores["P"] += VISUAL_COLOR_GRADING_WEIGHT

    if profile["key"] == "narrative_trailer":
        scores["P"] += VISUAL_TRAILER_PROFILE_WEIGHT
    elif profile["key"] == "technical_explainer":
        scores["R"] += VISUAL_TECHNICAL_PROFILE_WEIGHT

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    axis, top_score = ordered[0]
    second_score = ordered[1][1]
    total_score = sum(scores.values())

    # 改进置信度计算
    dimensions = sum(1 for s in scores.values() if s > 0)
    confidence = round(top_score / total_score * (1 + 0.1 * dimensions / 4), 2) if total_score > 0 else 0.0
    confidence = min(confidence, 0.99)
    strong_axes = [score for _, score in ordered if score >= VISUAL_MIX_MIN_SCORE]

    if confidence < VISUAL_LOW_CONFIDENCE:
        print(f"警告: 视觉主体分类置信度较低 ({confidence})，建议人工复核。")

    if top_score < VISUAL_MIX_MIN_SCORE or (
        second_score >= VISUAL_MIX_MIN_SCORE
        and abs(top_score - second_score) <= VISUAL_MIX_DELTA
        and len(strong_axes) >= 2
    ):
        return {"axis": "H", "label": VISUAL_AXIS_LABELS["H"], "confidence": confidence, "rationale": "视觉主体线索分散，按混合型处理。"}
    return {"axis": axis, "label": VISUAL_AXIS_LABELS[axis], "confidence": confidence, "rationale": f"视觉主体更接近 {VISUAL_AXIS_LABELS[axis]}。"}


def _infer_audio_axis(data: Dict, context: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    context = context or _build_route_context(data)
    title = str(context["title"])
    title_lower = str(context["title_lower"])
    scenes = list(context["rows"])
    profile = data.get("content_profile") or infer_content_profile(data, context=context)
    signals = dict(context["signals"])
    voiceover_ratio = sum(1 for scene in scenes if _voiceover(scene)) / max(len(scenes), 1)
    scores = {"L": 0.0, "M": 0.0, "E": 0.0, "LM": 0.0, "N": 0.0}

    # 标题关键词
    if _has_music_intent(data):
        scores["M"] += AUDIO_MUSIC_TITLE_WEIGHT
        scores["LM"] += AUDIO_LM_MUSIC_TITLE_WEIGHT
    if any(word in title_lower or word in title for word in ("鬼畜", "梗", "搞笑", "整蛊", "表情包")):
        scores["E"] += AUDIO_MEME_TITLE_WEIGHT
    if any(word in title_lower or word in title for word in ("解说", "影评", "评测", "讲解", "教程", "评论")):
        scores["L"] += AUDIO_LANGUAGE_TITLE_WEIGHT

    # 语言功能分布分析
    lang_funcs = [_infer_language_function(_voiceover(s), title) for s in scenes if _voiceover(s)]
    func_counter = Counter(lang_funcs)
    if lang_funcs and func_counter.get("歌词抒情", 0) >= len(lang_funcs) * 0.5:
        scores["M"] += AUDIO_MUSIC_FUNCTION_WEIGHT
        scores["LM"] += AUDIO_LM_MUSIC_FUNCTION_WEIGHT
    if lang_funcs and func_counter.get("信息说明", 0) + func_counter.get("指令说明", 0) >= len(lang_funcs) * 0.5:
        scores["L"] += AUDIO_INFORMATION_FUNCTION_WEIGHT
    if lang_funcs and func_counter.get("叙事推进", 0) >= len(lang_funcs) * 0.3:
        scores["L"] += AUDIO_NARRATIVE_FUNCTION_WEIGHT
        scores["LM"] += AUDIO_LM_NARRATIVE_FUNCTION_WEIGHT

    # voiceover_ratio基础分析
    scores["L"] += voiceover_ratio * AUDIO_VOICEOVER_RATIO_WEIGHT
    if voiceover_ratio >= AUDIO_LM_VOICEOVER_RATIO and _has_music_intent(data):
        scores["LM"] += AUDIO_LM_BALANCED_VOICEOVER_WEIGHT
    if voiceover_ratio < AUDIO_WEAK_PARTICIPATION_RATIO and not _has_music_intent(data):
        scores["N"] += AUDIO_WEAK_AUDIO_WEIGHT
    if voiceover_ratio < AUDIO_LM_VOICEOVER_RATIO and _has_music_intent(data):
        scores["M"] += AUDIO_LOW_VOICEOVER_MUSIC_WEIGHT

    # audio_visual_relation分布
    relations = [_infer_relation(s, title) for s in scenes]
    relation_counter = Counter(relations)
    if scenes and relation_counter.get("对位", 0) >= len(scenes) * 0.4:
        scores["M"] += AUDIO_COUNTERPOINT_M_WEIGHT
        scores["LM"] += AUDIO_COUNTERPOINT_LM_WEIGHT
    if scenes and relation_counter.get("互补", 0) >= len(scenes) * 0.5:
        scores["L"] += AUDIO_COMPLEMENTARY_L_WEIGHT

    if profile["key"] == "narrative_trailer":
        scores["LM"] += AUDIO_TRAILER_LM_WEIGHT
        if 0.2 <= voiceover_ratio <= 0.85:
            scores["LM"] += AUDIO_TRAILER_BALANCED_VOICEOVER_WEIGHT
        if signals["non_voiceover_high_impact"] >= max(1.0, len(scenes) * 0.15):
            scores["M"] += AUDIO_TRAILER_NONVOICE_M_WEIGHT
            scores["LM"] += AUDIO_TRAILER_NONVOICE_LM_WEIGHT
    elif profile["key"] == "technical_explainer":
        scores["L"] += AUDIO_TECHNICAL_LANGUAGE_WEIGHT

    # 改进LM判断：检测语言功能类型
    lyric_ratio = func_counter.get("歌词抒情", 0) / max(len(lang_funcs), 1) if lang_funcs else 0
    dialogue_ratio = (func_counter.get("叙事推进", 0) + func_counter.get("表达补充", 0)) / max(len(lang_funcs), 1) if lang_funcs else 0
    if voiceover_ratio >= AUDIO_LM_DIALOGUE_RATIO and _has_music_intent(data) and lyric_ratio < 0.7:
        scores["LM"] += AUDIO_MUSIC_DIALOGUE_WEIGHT

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    axis, top_score = ordered[0]
    second_axis, second_score = ordered[1]
    total_score = sum(scores.values())

    if total_score == 0 or (voiceover_ratio <= AUDIO_FORCE_WEAK_RATIO and not _has_music_intent(data)):
        axis = "N"
    elif axis in {"L", "M"} and second_axis in {"L", "M", "LM"} and abs(top_score - second_score) <= AUDIO_AXIS_TIE_DELTA and voiceover_ratio >= 0.2:
        axis = "LM"
    elif axis == "L" and _has_music_intent(data) and voiceover_ratio >= AUDIO_LM_VOICEOVER_RATIO and dialogue_ratio >= AUDIO_LM_DIALOGUE_RATIO:
        axis = "LM"

    return {
        "axis": axis,
        "label": AUDIO_AXIS_LABELS[axis],
        "rationale": f"听觉主体更接近 {AUDIO_AXIS_LABELS[axis]}。",
        "voiceover_ratio": round(voiceover_ratio, 3),
    }


def _base_route_from_axes(data: Dict, visual: Dict[str, object], audio: Dict[str, object]) -> Dict[str, object]:
    pair = (visual["axis"], audio["axis"])
    base = ROUTE_FRAMEWORKS.get(pair)
    if visual["axis"] == "H" or base is None:
        return {
            "visual_axis": visual["axis"],
            "visual_label": visual["label"],
            "audio_axis": audio["axis"],
            "audio_label": audio["label"],
            "route_code": f"{visual['axis']} + {audio['axis']}",
            "framework": "experimental",
            "route_label": "形式实验型 / 边界模糊型",
            "reference": "不强行套现有框架，直接分析视听实验本身",
            "route_subtype": "",
        }

    framework, label, reference = base
    subtype = ""
    if framework == "narrative_performance" and _has_music_intent(data):
        subtype = "剧情化 MV"
    elif framework == "narrative_performance" and _has_commercial_intent(data):
        subtype = "剧情广告 / 叙事型品牌片"
    return {
        "visual_axis": visual["axis"],
        "visual_label": visual["label"],
        "audio_axis": audio["axis"],
        "audio_label": audio["label"],
        "route_code": f"{visual['axis']} + {audio['axis']}",
        "framework": framework,
        "route_label": label,
        "reference": reference,
        "route_subtype": subtype,
    }


def _infer_dual_layer(route: Dict[str, object], data: Dict, context: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    dual_layer = {"enabled": False}
    context = context or _build_route_context(data)
    scenes = list(context["rows"])

    if route["framework"] == "narrative_performance" and _has_music_intent(data):
        dual_layer = {"enabled": True, "primary": "叙事层", "secondary": "音乐表达层", "reason": "它既在讲故事，也明显依托音乐和歌词完成情绪表达。"}
    elif route["framework"] == "narrative_performance" and _has_commercial_intent(data):
        dual_layer = {"enabled": True, "primary": "叙事层", "secondary": "商业功能层", "reason": "它既在讲故事，也承担了明确的品牌或产品传递任务。"}
    elif route["framework"] == "documentary_generic" and _has_commercial_intent(data):
        dual_layer = {"enabled": True, "primary": "纪实层", "secondary": "品牌植入层", "reason": "纪实表达之外，还存在独立的品牌功能层。"}
    elif route["framework"] == "meme" and _has_commercial_intent(data):
        dual_layer = {"enabled": True, "primary": "娱乐层", "secondary": "带货功能层", "reason": "娱乐外壳之外，底层仍有明确的转化意图。"}
    elif route["framework"] == "documentary_generic" and _has_persona_intent(data):
        dual_layer = {"enabled": True, "primary": "生活内容层", "secondary": "人设塑造层", "reason": "生活记录之外，还在持续建构创作者的人设。"}

    if not dual_layer["enabled"] and scenes:
        visual_funcs = [_infer_visual_function(s) for s in scenes]
        func_counter = Counter(visual_funcs)
        scene_types = [_safe_text(s.get("type_classification")) for s in scenes]
        type_counter = Counter(t for t in scene_types if t)
        narrative_funcs = func_counter.get("动作行为推进", 0) + func_counter.get("人物情绪呈现", 0)
        aesthetic_funcs = func_counter.get("氛围质感营造", 0)

        if narrative_funcs >= len(scenes) * 0.3 and aesthetic_funcs >= len(scenes) * 0.3:
            dual_layer = {"enabled": True, "primary": "叙事层", "secondary": "意象层", "reason": "既有明确的叙事推进，也有大量意象化的氛围营造。"}
        elif len(type_counter) >= 3 and type_counter.most_common(1)[0][1] < len(scenes) * 0.6:
            dual_layer = {"enabled": True, "primary": "主体内容层", "secondary": "形式实验层", "reason": "场景类型混合度高，存在多种表达手法的交织。"}
        elif route["framework"] == "cinematic_life" and _has_commercial_intent(data):
            dual_layer = {"enabled": True, "primary": "生活美学层", "secondary": "商业转化层", "reason": "生活美学呈现之外，底层存在明确的商业转化意图。"}
        elif route["framework"] == "concept_mv" and narrative_funcs >= len(scenes) * 0.25:
            dual_layer = {"enabled": True, "primary": "意象层", "secondary": "叙事层", "reason": "意象化表达之外，还存在隐含的叙事线索。"}
        elif route["framework"] == "mix_music" and narrative_funcs >= len(scenes) * 0.3:
            dual_layer = {"enabled": True, "primary": "音乐节奏层", "secondary": "叙事层", "reason": "音乐节奏主导之外，还存在明确的叙事线索。"}
        elif route["framework"] == "commentary_mix" and aesthetic_funcs >= len(scenes) * 0.3:
            dual_layer = {"enabled": True, "primary": "评论层", "secondary": "美学呈现层", "reason": "评论解说之外，还有独立的美学呈现追求。"}
        elif len(scenes) >= 5:
            impacts = [float(s.get("scores", {}).get("impact") or 0.0) for s in scenes]
            if impacts:
                high_impact = sum(1 for i in impacts if i >= 7.0)
                low_impact = sum(1 for i in impacts if i <= 4.0)
                if high_impact >= 2 and low_impact >= 2:
                    dual_layer = {"enabled": True, "primary": "主体表达层", "secondary": "情绪调节层", "reason": "情绪曲线呈现明显的多层次起伏，存在刻意的节奏设计。"}

    return dual_layer


def _apply_profile_route_overrides(route: Dict[str, object], profile: Dict[str, str], data: Dict) -> Dict[str, object]:
    updated = dict(route)
    if profile["key"] == "event_brand_ad":
        updated.update(
            {
                "framework": "event_brand_ad",
                "route_label": "节庆 / 活动品牌广告",
                "route_subtype": "群体共唱 / 品牌奇观",
                "reference": "品牌活动片 / 节庆广告 / 群体情绪广告",
            }
        )
    elif profile["key"] == "travel_short":
        updated.update(
            {
                "framework": "journey_brand_film",
                "route_label": "旅程型品牌短片",
                "route_subtype": "人物随行 / 地点意象",
                "reference": "抒情旅程广告 / 品牌人物短片 / 风格化随行片",
            }
        )
    elif profile["key"] == "documentary_observation":
        updated.update(
            {
                "framework": "documentary_generic",
                "route_label": "纪实 / 讲述型内容",
                "route_subtype": "跟拍观察 / 现场记录",
                "reference": "纪录片 / 纪实观察 / 跟拍讲述",
            }
        )
    elif profile["key"] == "meme_clip":
        updated.update(
            {
                "framework": "meme",
                "route_label": "梗视频 / 反差短片",
                "route_subtype": "反差动作 / 字幕梗",
                "reference": "梗视频 / 反应视频 / 反差短片",
            }
        )
    elif profile["key"] == "graphic_explainer":
        updated.update(
            {
                "framework": "infographic_animation",
                "route_label": "信息图动画 / 图解讲解",
                "route_subtype": "结构示意 / 图形解释",
                "reference": "信息图动画 / 图解讲解 / 结构示意视频",
            }
        )
    elif profile["key"] == "commentary_analysis":
        updated.update(
            {
                "framework": "commentary_mix",
                "route_label": "评论向素材二创",
                "route_subtype": "观点拆解 / 证据对照",
                "reference": "评论分析 / 素材举证 / 观点拆解",
            }
        )
    elif profile["key"] == "technical_explainer":
        updated.update(
            {
                "framework": "technical_explainer",
                "route_label": "技术讲解 / 原理拆解",
                "route_subtype": "问题抛出 / 步骤拆解 / 结论回看",
                "reference": "知识讲解视频 / 原理拆解 / 过程演示",
            }
        )
    elif profile["key"] == "narrative_trailer":
        updated.update(
            {
                "framework": "narrative_trailer",
                "route_label": "剧情预告 / 叙事预告",
                "route_subtype": "世界观与高能卖点预告",
                "reference": "电影 / 剧集预告片的前提搭建、悬念升级和记忆点编排",
            }
        )
    elif profile["key"] == "travel_short" and updated["framework"] == "documentary_generic":
        updated["route_subtype"] = "旅行短片"

    updated["fallback"] = updated["framework"] == "experimental"
    return updated
