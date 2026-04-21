#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Dict, List, Sequence, Tuple

from audiovisual.routing.constants import (
    ATMOSPHERIC_FRAMEWORKS,
    AUDIO_FORCE_WEAK_RATIO,
    DETAIL_KEYWORDS,
    GENERAL_CLOSING_START_RATIO,
    GENERAL_OPENING_RATIO,
    GRAPHIC_FRAMEWORKS,
    LANGUAGE_LED_FRAMEWORKS,
    MEME_FRAMEWORKS,
    OVERVIEW_KEYWORDS,
    QUESTION_PATTERNS,
    RECAP_PATTERNS,
    STEP_PATTERNS,
    TECH_EARLY_RATIO,
    TECH_LATE_START_RATIO,
    TECH_MIDDLE_END_RATIO,
    TECH_MIDDLE_START_RATIO,
    TECH_OPENING_RATIO,
    VISUAL_LOW_CONFIDENCE,
)
from audiovisual.routing.features import (
    _infer_visual_function,
    _looks_like_promo_card,
    _looks_like_release_text,
    _matches_any,
)
from audiovisual.shared import (
    _analysis_rows,
    _avg,
    _group_scenes_by_count,
    _onscreen_text,
    _markdown_media_path,
    _relative_media_path,
    _safe_text,
    _scene_desc,
    _scene_haystack,
    _scene_screenshot,
    _scene_slice,
    _top_text,
    _voiceover,
)
from audiovisual.reporting.scene_utils import (
    _best_representative_scene,
    _best_scene_phrase,
    _best_scene_refs,
    _best_unique_scene,
    _ordered_scenes,
    _pick_unique_best_scenes,
    _scene_phrase,
    _scene_priority,
    _scene_refs,
)


def _pick_scenes(data: Dict, limit: int = 3, require_voiceover: bool = False) -> List[Dict]:
    scenes = sorted(data.get("scenes", []), key=lambda scene: float(scene.get("weighted_score") or 0.0), reverse=True)
    picked: List[Dict] = []
    for scene in scenes:
        if require_voiceover and not _report_voiceover(scene):
            continue
        picked.append(scene)
        if len(picked) >= limit:
            break
    return picked


def _scene_list_text(scenes: Sequence[Dict], use_voiceover: bool = False) -> str:
    parts = []
    for scene in scenes:
        text = _report_voiceover(scene) if use_voiceover else _scene_desc(scene)
        if text:
            parts.append(f"Scene {int(scene.get('scene_number', 0)):03d}：{text[:40]}")
    return "；".join(parts) if parts else "暂无足够样本。"


def _find_scene_matches(
    data: Dict,
    keywords: Sequence[str],
    start_ratio: float = 0.0,
    end_ratio: float = 1.0,
    limit: int = 8,
) -> List[Dict]:
    ordered = _ordered_scenes(data)
    if not ordered:
        return []
    subset = _scene_slice(ordered, start_ratio, end_ratio)
    hits = []
    for scene in subset:
        haystack = _scene_haystack(scene)
        if any(keyword in haystack for keyword in keywords):
            hits.append(scene)
    return hits[:limit]


def _mix_music_rhythm_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "节奏数据不足。"
    durations = [float(s.get("duration_seconds") or 0.0) for s in scenes]
    avg_duration = _avg(durations)
    short_cuts = [s for s in scenes if float(s.get("duration_seconds") or 0.0) < avg_duration * 0.6]
    beat_hits = [s for s in short_cuts if float(s.get("scores", {}).get("impact") or 0.0) >= 7.0]
    rhythm_consistency = 1.0 - (max(durations) - min(durations)) / (max(durations) + 0.1) if durations else 0.0
    text = f"场景切换频率：平均 {avg_duration:.1f}s/镜，短切镜头占比 {len(short_cuts)/len(scenes)*100:.0f}%。"
    if beat_hits:
        text += f"识别到 {len(beat_hits)} 个卡点场景（高冲击+短时长），代表段落 {_scene_refs(beat_hits[:4], 4)}，这些镜头踩在节奏点上，视觉冲击和音乐转折同步爆发。"
    else:
        text += "未检测到明显卡点场景，剪辑节奏更偏向平滑过渡而非强节奏冲击。"
    text += f"节奏一致性评分 {rhythm_consistency*10:.1f}/10，"
    if rhythm_consistency >= 0.7:
        text += "剪辑节奏稳定，镜头时长分布均匀，适合音乐主导型内容。"
    else:
        text += "镜头时长波动较大，节奏感不够统一，可能影响音乐节奏的传递。"
    return text


def _mix_music_source_quality(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "素材数据不足。"
    high_quality = [s for s in scenes if float(s.get("weighted_score") or 0.0) >= 7.0]
    aesthetic_scores = [float(s.get("scores", {}).get("aesthetic_beauty") or 0.0) for s in scenes]
    avg_aesthetic = _avg(aesthetic_scores)
    style_keywords = [_safe_text(s.get("storyboard", {}).get("visual_style")) for s in scenes]
    style_diversity = len(set(style_keywords)) / len(scenes) if scenes else 0.0
    text = f"高分场景（≥7.0）占比 {len(high_quality)/len(scenes)*100:.0f}%，平均美学分 {avg_aesthetic:.1f}/10。"
    if len(high_quality) / len(scenes) >= 0.6:
        text += f"素材精华度高，代表段落 {_scene_refs(high_quality[:5], 5)}，说明二创者对原素材的筛选能力强，提取的都是高光时刻。"
    else:
        text += "高分场景占比偏低，素材筛选不够精准，部分镜头未达到精华标准，可能拉低整体观感。"
    text += f"风格一致性：{(1-style_diversity)*10:.1f}/10，"
    if style_diversity < 0.3:
        text += "素材风格统一，视觉连贯性强。"
    else:
        text += "素材风格较为多样，可能来自不同源，需要更强的剪辑节奏来统一观感。"
    return text


def _mix_music_creative_value(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "情绪数据不足。"
    emotional_curve = [float(s.get("analysis_dimensions", {}).get("emotional_effect") or 0.0) for s in scenes]
    peak_moments = [i for i, score in enumerate(emotional_curve) if score >= 7.5]
    curve_variance = max(emotional_curve) - min(emotional_curve) if emotional_curve else 0.0
    memorability_scores = [float(s.get("scores", {}).get("memorability") or 0.0) for s in scenes]
    avg_memorability = _avg(memorability_scores)
    text = f"情绪曲线波动幅度 {curve_variance:.1f}，峰值时刻出现在 {len(peak_moments)} 个场景。"
    if curve_variance >= 3.0 and peak_moments:
        peak_scenes = [scenes[i] for i in peak_moments[:4] if i < len(scenes)]
        text += f"情绪曲线有明显起伏，高潮段落 {_scene_refs(peak_scenes, 4)} 形成新的节奏价值，不只是素材拼接，而是通过重组创造了新的情绪体验。"
    elif curve_variance >= 2.0:
        text += "情绪曲线有一定起伏，但峰值不够突出，二创立意偏向氛围营造而非情绪爆发。"
    else:
        text += "情绪曲线平缓，更像是把高光片段顺手拼起来，缺少对原素材的节奏重构，二创价值有限。"
    text += f"记忆度均值 {avg_memorability:.1f}/10，"
    if avg_memorability >= 7.0:
        text += "素材本身记忆点强，二创成功放大了这些高光时刻。"
    else:
        text += "素材记忆点不足，二创未能通过节奏重组提升记忆度。"
    return text


def _meme_density_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "梗密度数据不足。"
    fun_scores = [float(s.get("scores", {}).get("fun_interest") or 0.0) for s in scenes]
    high_fun = [s for s in scenes if float(s.get("scores", {}).get("fun_interest") or 0.0) >= 7.5]
    avg_fun = _avg(fun_scores)
    durations = [float(s.get("duration_seconds") or 0.0) for s in scenes]
    total_duration = sum(durations)
    high_fun_duration = sum([float(s.get("duration_seconds") or 0.0) for s in high_fun])
    density = len(high_fun) / (total_duration / 60) if total_duration > 0 else 0.0
    text = f"梗密度：{density:.1f} 个爆梗/分钟，平均趣味分 {avg_fun:.1f}/10。"
    if density >= 3.0:
        text += f"梗密度极高，{_scene_refs(high_fun[:5], 5)} 这些段落持续输出笑点，观众注意力被高频刺激占据，适合短视频快节奏消费。"
    elif density >= 1.5:
        text += f"梗密度适中，{_scene_refs(high_fun[:4], 4)} 这些段落形成笑点峰值，节奏有张有弛，不会让观众疲劳。"
    else:
        text += "梗密度偏低，笑点分布稀疏，可能导致观众中途流失，需要更密集的趣味刺激。"
    text += f"高趣味场景占总时长 {high_fun_duration/total_duration*100:.0f}%，"
    if high_fun_duration / total_duration >= 0.5:
        text += "梗向内容占据主体，娱乐价值充分。"
    else:
        text += "梗向内容占比不足，部分时段缺少笑点支撑。"
    return text


def _meme_timing_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "时机数据不足。"
    contrast_scenes = [s for s in scenes if float(s.get("scores", {}).get("fun_interest") or 0.0) >= 7.0 and float(s.get("scores", {}).get("credibility") or 0.0) <= 4.0]
    voiceover_scenes = [s for s in scenes if _voiceover(s)]
    visual_audio_sync = len([s for s in voiceover_scenes if float(s.get("scores", {}).get("fun_interest") or 0.0) >= 7.0]) / len(voiceover_scenes) if voiceover_scenes else 0.0
    text = f"视听同步率 {visual_audio_sync*100:.0f}%，"
    if visual_audio_sync >= 0.7:
        text += "视觉梗和听觉梗高度同步，笑点在同一时刻从两个维度爆发，效果叠加。"
    elif visual_audio_sync >= 0.4:
        text += "视听梗有一定同步，但部分场景视觉和听觉笑点错位，削弱了爆梗强度。"
    else:
        text += "视听梗同步性差，视觉和听觉各自为战，未能形成合力。"
    if contrast_scenes:
        text += f"检测到 {len(contrast_scenes)} 个反差效果场景（高趣味+低可信度），{_scene_refs(contrast_scenes[:4], 4)} 这些段落通过荒诞、夸张或错位制造笑点，是典型的梗向手法。"
    else:
        text += "未检测到明显反差效果，梗的制造更依赖直接的趣味元素而非错位感。"
    return text


def _meme_subculture_markers(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "圈层标记数据不足。"
    descriptions = [_scene_desc(s) for s in scenes]
    voiceovers = [_voiceover(s) for s in scenes]
    all_text = " ".join(descriptions + voiceovers)
    subculture_keywords = {
        "二次元": ["动漫", "番剧", "二次元", "ACG", "萌", "宅"],
        "游戏": ["游戏", "电竞", "主机", "手游", "玩家", "通关"],
        "鬼畜": ["鬼畜", "空耳", "MAD", "音MAD", "循环"],
        "网络梗": ["梗", "表情包", "弹幕", "网络用语", "热梗"],
        "亚文化": ["亚文化", "小众", "圈层", "社区", "粉丝"],
    }
    detected = {label: sum(1 for kw in keywords if kw in all_text) for label, keywords in subculture_keywords.items()}
    dominant = max(detected, key=detected.get) if any(detected.values()) else None
    text = "圈层识别："
    if dominant and detected[dominant] >= 3:
        text += f"明确定位于 {dominant} 圈层，内容标记密集（{detected[dominant]} 次），目标受众清晰，适合圈内传播。"
    elif any(detected.values()):
        markers = [label for label, count in detected.items() if count > 0]
        text += f"检测到 {', '.join(markers)} 等圈层标记，但未形成单一圈层主导，内容更偏向泛娱乐受众。"
    else:
        text += "未检测到明显亚文化标记，内容更偏向大众娱乐，圈层识别度低。"
    fun_avg = _avg([float(s.get("scores", {}).get("fun_interest") or 0.0) for s in scenes])
    text += f"整体趣味分 {fun_avg:.1f}/10，"
    if fun_avg >= 7.5:
        text += "即使圈层标记不明显，高趣味度也能支撑泛娱乐传播。"
    elif dominant:
        text += "圈层定位清晰可以弥补趣味度不足，但需要精准触达目标受众。"
    else:
        text += "既缺少圈层定位又缺少高趣味度，传播力可能受限。"
    return text


def _meme_failure_points(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "暂时还看不到明确失效点。"
    low_fun = [s for s in scenes if float(s.get("scores", {}).get("fun_interest") or 0.0) < 7.0]
    static = [s for s in scenes if _safe_text(s.get("storyboard", {}).get("camera_movement")) in {"", "静止镜头"}]
    refs = _scene_refs(low_fun[:3], 3)
    if low_fun:
        return f"{refs} 这些地方梗点不够密，容易让笑点掉下来。通常不是素材不行，而是反差、反应和音效没有在同一拍上顶住。"
    if len(static) >= len(scenes) * 0.5:
        return f"{_scene_refs(static[:3], 3)} 这些地方镜头太稳，笑点来得不够狠。梗片一旦反应速度慢下来，观众就容易先看懂套路、后收到笑点。"
    return "这条片主要不是梗太少，而是需要把强笑点再往前收一点，让爆点来得更直接。"


def _meme_viewing_advice(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "可以先看最有反差的几个段落，再回头看整条节奏有没有托住。"
    high_fun = [s for s in scenes if float(s.get("scores", {}).get("fun_interest") or 0.0) >= 7.5]
    focus = high_fun or scenes[:2]
    return f"先看 {_scene_refs(focus[:3], 3)} 这些高密度段落，判断笑点是不是一到动作点就爆开；再回头看中间几段有没有塌速。如果前后都能顶住，这条梗片就算成立。"


def _experimental_route_diagnosis(data: Dict, route: Dict[str, object]) -> str:
    scenes = _ordered_scenes(data)
    reasons: List[str] = []
    if route.get("visual_axis") == "H":
        reasons.append("视觉主体本身就是混合的，实拍、图形或多种表达手法没有稳定让出一个主导位置")
    if route.get("visual_confidence", 0.0) < VISUAL_LOW_CONFIDENCE:
        reasons.append(f"视觉判断把握不高（{route.get('visual_confidence', 0.0):.2f}），说明几条线索都在抢主导权")
    if route.get("voiceover_ratio", 0.0) <= AUDIO_FORCE_WEAK_RATIO:
        reasons.append("语言参与很弱，报告很难靠台词直接把作品钉进讲述类或叙事类")
    if route.get("content_profile", {}).get("key") == "generic":
        reasons.append("标题和文本线索也没有给出足够清楚的内容意图")
    if not reasons:
        reasons.append("它的线索分布更像在故意打散常规类型，而不是老老实实走某一条成熟模板")
    refs = _scene_refs(scenes[:3], 3)
    return f"{'；'.join(reasons)}。像 {refs} 这些段落，观众会更先感到“它在试一种关系”，而不是立刻认出它属于哪一类。"


def _experimental_focus_advice(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "先看画面和声音各自在做什么，再看它们有没有在同一个点上相互放大。"
    impact_refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get('scores', {}).get('impact') or 0.0), reverse=True)[:3], 3)
    return f"可以先抓住哪几层看：先看 {impact_refs} 这些高冲击段落里，画面到底是在推信息、推情绪，还是只是在做形式碰撞；再看声音有没有跟着同一股力走。如果两条轨道一直在顶同一件事，这种实验才站得住。"


def _experimental_viewing_advice(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "建议先找最能代表整体手感的 1 到 2 段，再判断整条片有没有把这个规则守住。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("weighted_score") or 0.0), reverse=True)[:3], 3)
    return f"观看建议：先看 {refs} 这些代表段落，优先观察它是不是一直用同一套视听规则在推进；如果每段都在换玩法却没有共同目标，实验感会留下，但成立感会掉下去。"


def _silent_reality_pacing_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "画面节奏信息不足。"
    durations = [float(s.get("duration_seconds") or 0.0) for s in scenes]
    avg_duration = _avg(durations)
    moving = [s for s in scenes if _safe_text(s.get("storyboard", {}).get("camera_movement")) not in {"", "静止镜头"}]
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("weighted_score") or 0.0), reverse=True)[:3], 3)
    return (
        f"这类内容的节奏主要落在镜头停留和空间变化上。全片平均镜头时长约 {avg_duration:.1f} 秒，"
        f"{refs} 这些段落最能看出它是不是在靠环境、动作和距离变化慢慢把人带进去。"
        f"{' 有运动的镜头占比够高，说明观察不是死看。' if len(moving) >= max(1, len(scenes) // 2) else ' 运动变化偏少，观看时更依赖构图和现场细节撑住。'}"
    )


def _silent_reality_failure_risk(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "暂时看不到明确风险。"
    static = [s for s in scenes if _safe_text(s.get("storyboard", {}).get("camera_movement")) in {"", "静止镜头"}]
    wide = [s for s in scenes if "景" in _safe_text(s.get("storyboard", {}).get("shot_size"))]
    if len(static) >= len(scenes) * 0.7:
        return "最大的风险不是安静，而是太平。没有对白时，如果镜头连续不动、信息也不换，观众会先感到节奏停住，再开始掉线。"
    if not wide:
        return "如果一直没有空间建立镜头，这类内容会只剩局部动作，现场感容易立不起来。"
    return "这类片最怕的是把“克制”拍成“没东西”。只要空间、动作和观察顺序还能一层层推进，安静本身反而会是优点。"


def _silent_reality_viewing_advice(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "先看最能代表空间变化的几段，再判断后面有没有把观察继续往前送。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("weighted_score") or 0.0), reverse=True)[:3], 3)
    return f"观看建议：先看 {refs} 这些代表段落，重点看它有没有让你在没有台词的情况下，依然明白人在做什么、空间怎样变化、情绪往哪边走。"


def _lecture_performance_groups(data: Dict) -> Dict[str, List[Dict]]:
    ordered = _ordered_scenes(data)
    if not ordered:
        return {"opening": [], "story": [], "performance": [], "interaction": [], "closing": []}
    opening = _scene_slice(ordered, 0.0, GENERAL_OPENING_RATIO)
    story = [scene for scene in ordered if _voiceover(scene)]
    performance = [scene for scene in ordered if any(word in _scene_haystack(scene) for word in ("表情", "动作", "手势", "舞台", "观众", "笑", "模仿", "反应"))]
    interaction = [scene for scene in ordered if any(word in _scene_haystack(scene) for word in ("观众", "笑声", "掌声", "回应", "提问", "起哄"))]
    closing = _scene_slice(ordered, GENERAL_CLOSING_START_RATIO, 1.0)
    return {
        "opening": opening or ordered[:1],
        "story": story or ordered[:1],
        "performance": performance or ordered[:1],
        "interaction": interaction or performance or ordered[:1],
        "closing": closing or ordered[-1:],
    }


def _lecture_performance_stage_analysis(data: Dict) -> str:
    groups = _lecture_performance_groups(data)
    return (
        f"{_best_scene_refs(groups['story'], 2)} 这些段落负责把话说清楚，"
        f"{_best_scene_refs(groups['performance'], 2, prefer_impact=True)} 则负责把讲述从“听懂”抬到“看进去”。"
        "这类内容成立的关键，不是段子多不多，而是表演动作有没有真的帮内容加压。"
    )


def _lecture_performance_failure_risk(data: Dict) -> str:
    groups = _lecture_performance_groups(data)
    if groups["performance"] == groups["story"]:
        return "如果表演层始终没有从讲述里分出来，整条片会只剩“有人在说”，感染力会明显不够。"
    if not groups["interaction"]:
        return "没有互动不一定失败，但少了观众反应或节奏回弹时，这类内容更容易像普通独白而不是舞台讲述。"
    return "最常见的失效点，是讲述和表演各做各的。只要动作、停顿和观众反应还在托同一条主线，这类内容就站得住。"


def _abstract_sfx_sync_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "音画同步信息不足。"
    peaks = sorted(scenes, key=lambda s: (float(s.get("scores", {}).get("impact") or 0.0), float(s.get("weighted_score") or 0.0)), reverse=True)[:3]
    return (
        f"{_scene_refs(peaks, 3)} 这些段落最值得先看。抽象音效设计不靠故事成立，而是看声音一变、图形和节奏有没有一起跟着变。"
        "如果每次冲击都能同时落在听觉和视觉上，观众就会把它当成一次完整的感知体验。"
    )


def _abstract_sfx_failure_risk(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "暂时看不到明确风险。"
    static = [s for s in scenes if _safe_text(s.get("storyboard", {}).get("camera_movement")) in {"", "静止镜头"}]
    if len(static) >= len(scenes) * 0.6:
        return "这类内容最怕只有漂亮图形、没有真正的节奏反应。画面如果太稳，音效再强也容易变成各唱各的。"
    return "它最容易失效的地方，不是抽象，而是抽象得没有规则。只要音画之间还能反复遵守同一套变化逻辑，这类内容就不会散。"


def _motion_graphics_flow_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "动态图形节奏信息不足。"
    durations = [float(s.get("duration_seconds") or 0.0) for s in scenes]
    avg_duration = _avg(durations)
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("weighted_score") or 0.0), reverse=True)[:3], 3)
    return (
        f"{refs} 这些段落最能看出动态图形是不是顺。平均镜头时长约 {avg_duration:.1f} 秒，"
        "这类内容最关键的是转场、节奏和视觉注意力有没有一直被往前送，而不是每个镜头单看都挺好。"
    )


def _motion_graphics_failure_risk(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "暂时看不到明确风险。"
    styles = {_safe_text(s.get("storyboard", {}).get("visual_style")) for s in scenes if _safe_text(s.get("storyboard", {}).get("visual_style"))}
    if len(styles) >= max(3, len(scenes)):
        return "这类内容最容易输在风格一直换，结果每一段都像新的开始，观众来不及形成连贯感。"
    return "真正的风险不是没声音，而是视觉注意力断掉。只要转场、层级和运动方向还能持续带路，纯视觉内容就不会空。"


def _hybrid_narrative_layering_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "混合叙事层次信息不足。"
    visual_funcs = Counter(_infer_visual_function(scene) for scene in scenes)
    dominant = visual_funcs.most_common(2)
    labels = "、".join(label for label, _ in dominant) if dominant else "多层表达"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("weighted_score") or 0.0), reverse=True)[:3], 3)
    return f"{refs} 这些段落最能看出它怎么把不同手法拧成一条叙事线。现在主导的两层任务大多落在 {labels}，重点不是素材有多杂，而是这些任务有没有在推同一件事。"


def _hybrid_narrative_failure_risk(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "暂时看不到明确风险。"
    types = Counter(_safe_text(scene.get("type_classification")) for scene in scenes if _safe_text(scene.get("type_classification")))
    if len(types) >= 3 and types.most_common(1)[0][1] < len(scenes) * 0.5:
        return "这类内容最容易散在“每种手法都想要一点”。如果没有一条主线把不同段落串起来，观众会记得风格很多，却记不住片子到底在推进什么。"
    return "只要不同手法最后都在给同一条叙事线加压，混合不是问题；真正的问题是层次多了，但方向不统一。"


def _hybrid_music_failure_risk(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "暂时看不到明确风险。"
    styles = [_safe_text(scene.get("storyboard", {}).get("visual_style")) for scene in scenes if _safe_text(scene.get("storyboard", {}).get("visual_style"))]
    if len(set(styles)) >= max(2, len(scenes)):
        return "这类内容最容易失效在“每换一次音乐层，就顺手换一次片子”。风格如果每次都重启，观众会感到丰富，但不一定会感到统一。"
    return "真正的问题不是混得多，而是每次切换之后有没有继续把同一股情绪往上托。只要音乐和画面都还在推同一个方向，混合反而会加分。"


def _hybrid_commentary_mix_value(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "多素材价值信息不足。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("weighted_score") or 0.0), reverse=True)[:3], 3)
    return f"{refs} 这些段落最能看出混合是不是在帮观点加力。真正成立时，不同素材不是为了显得多，而是各自承担举证、补情绪、补背景的不同任务。"


def _hybrid_commentary_failure_risk(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "暂时看不到明确风险。"
    if len(scenes) <= 2:
        return "素材少不是问题，问题是每一次切换有没有新增信息。只要换一种来源却没增加论证力度，观众就会觉得只是热闹。"
    return "这类内容最容易失效在素材切换很勤，但论点没有更清楚。多来源如果只是堆热闹，不会自动变成更强的论证。"


def _hybrid_commentary_viewing_advice(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "先看观点最清楚的一段，再看后面的素材切换有没有真的帮它站稳。"
    refs = _scene_refs(sorted(scenes, key=lambda s: len(_voiceover(s)), reverse=True)[:3], 3)
    return f"观看建议：先看 {refs} 这些语言最密的段落，确认主判断是什么；再回头看每次素材切换有没有补证据，而不是只换气氛。"


def _hybrid_ambient_layering_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "氛围层次信息不足。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("scores", {}).get("aesthetic_beauty") or 0.0), reverse=True)[:3], 3)
    return f"{refs} 这些段落最能看出它怎样把不同质地的画面和声音叠成同一种气压。氛围片的关键不是元素多，而是这些元素最后有没有往同一种感觉上收。"


def _hybrid_ambient_failure_risk(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "暂时看不到明确风险。"
    return "这类内容最容易从氛围变成散，不是因为慢，而是因为每层感觉都在各走各的。只要颜色、节奏和空间手感开始互相打架，观众就会先出戏。"


def _hybrid_ambient_viewing_advice(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "先看最有代表性的几段，再判断整条片有没有一直守住那股感觉。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("weighted_score") or 0.0), reverse=True)[:3], 3)
    return f"观看建议：先看 {refs} 这些代表段落，注意它是在慢慢加压，还是只是在堆漂亮质感。前者会留下余味，后者通常只留下素材感。"


def _narrative_mix_story_reframing(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "二创叙事信息不足。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("analysis_dimensions", {}).get("narrative_function") or 0.0), reverse=True)[:3], 3)
    return f"{refs} 这些段落最能看出它不是在复述原素材，而是在重排顺序、重设重点、重写观众该怎么理解这些画面。只要新主线能被看出来，这种重组就成立。"


def _narrative_mix_integrity(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "故事完整性信息不足。"
    with_voice = [scene for scene in scenes if _voiceover(scene)]
    if with_voice and len(with_voice) >= max(1, len(scenes) // 2):
        return "这条重组后的故事线基本站得住，因为语言、画面和节奏都在给同一个解释方向加码。真正要看的，不是它忠不忠于原素材，而是新故事有没有一口气讲顺。"
    return "新故事线能不能站住，关键看重组后的段落是不是在往同一个方向收。如果只有漂亮片段，没有新的因果或情绪推进，它就更像拼接，不像重写。"


def _narrative_mix_failure_risk(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "暂时看不到明确风险。"
    return "这类内容最容易失效在“每段都好看，但连不成一句话”。素材重组真正难的，不是找高光，而是让新的顺序真的生成新的意义。"


def _silent_performance_body_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "身体表达信息不足。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("scores", {}).get("impact") or 0.0), reverse=True)[:3], 3)
    return f"{refs} 这些段落最能看出身体表达在推什么。没有对白时，转身、停顿、眼神和动作力度就会接管节奏，观众能不能继续跟下去，全看这些动作有没有清楚地往外送情绪。"


def _silent_performance_failure_risk(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "暂时看不到明确风险。"
    return "最容易失效的地方，是动作有了，但信息没有。只要肢体和表情只剩姿态、不再继续推进情绪或关系，这类表演就会从“有戏”滑成“好看但空”。"


def _silent_performance_viewing_advice(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "先看动作最重的一两段，再判断整条片有没有持续把情绪送出来。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("weighted_score") or 0.0), reverse=True)[:3], 3)
    return f"观看建议：先看 {refs} 这些强动作段落，确认身体表达是在推进情绪、关系还是只是摆造型。前者能带人入戏，后者很快就会泄气。"


def _hybrid_meme_mix_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "混合梗法信息不足。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("scores", {}).get("fun_interest") or 0.0), reverse=True)[:3], 3)
    return f"{refs} 这些段落最能看出它混的不是素材类型本身，而是反应梗、贴图梗、音效梗这些不同笑点机制。真正成立时，观众感到的是笑点层层加码，而不是元素单纯变多。"


def _hybrid_meme_failure_risk(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "暂时看不到明确风险。"
    return "最容易乱的地方，是每种梗法都想抢第一拍。只要贴图、音效、表情和剪辑节奏开始互相抢位置，观众会先感到吵，再感到乱。"


def _hybrid_meme_viewing_advice(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "先看最猛的一两段，再判断后面有没有继续托住笑点。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("weighted_score") or 0.0), reverse=True)[:3], 3)
    return f"观看建议：先看 {refs} 这些高密度段落，确认几种梗法是在同一拍上往前顶，还是各自抢戏。前者会叠加，后者会打架。"


def _reality_sfx_distortion_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "现实音效反差信息不足。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("scores", {}).get("impact") or 0.0), reverse=True)[:3], 3)
    return f"{refs} 这些段落最能看出现实感是怎么被音效拧歪的。关键不是音效夸不夸张，而是现实动作还在不在，观众能不能同时感到“这是真动作”和“这被故意拧坏了”。"


def _reality_sfx_failure_risk(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "暂时看不到明确风险。"
    return "这类内容最怕只剩噱头。要是音效每次都很响，但现实动作没有被重新解释，观众会先被吓一下，然后很快知道套路。"


def _reality_sfx_viewing_advice(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "先看反差最强的一两段，再判断后面有没有继续玩出新的关系。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("weighted_score") or 0.0), reverse=True)[:3], 3)
    return f"观看建议：先看 {refs} 这些反差最高的段落，重点看现实动作有没有被音效重新定义；如果只是同一个惊吓反复来，后面就会很快掉劲。"


def _narrative_motion_graphics_story_role(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "图形叙事信息不足。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("analysis_dimensions", {}).get("narrative_function") or 0.0), reverse=True)[:3], 3)
    return f"{refs} 这些段落最能看出图形不是装饰，而是在替故事做结构、方向和关系说明。只要观众能通过运动、层级和变化看懂“发生了什么”，图形就真正参与了叙事。"


def _narrative_motion_graphics_integrity(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "叙事完整性信息不足。"
    return "这类内容真正难的，不是把图做顺，而是让图和语言一起把故事讲顺。只要每一次变化都在推进同一条线，观众就会跟着它走，而不是只把它当成好看的说明动画。"


def _narrative_motion_graphics_failure_risk(data: Dict) -> str:
    return "最容易失效的地方，是图形做得很热闹，但叙事关系没有更清楚。只要视觉变化开始只负责好看、不再负责推进，故事就会散。"


def _infographic_clarity_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "图解清晰度信息不足。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("analysis_dimensions", {}).get("information_efficiency") or 0.0), reverse=True)[:3], 3)
    return f"{refs} 这些段落最能看出信息有没有被讲清。好的信息图不是把东西摆出来，而是让人立刻知道先看哪里、再看哪里，最后明白关键关系是什么。"


def _infographic_hierarchy_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "层级引导信息不足。"
    return "画面层级有没有带路，看的不是元素多少，而是注意力有没有被顺着箭头、大小、颜色和位置一步步往前送。只要层级顺，复杂信息也不会糊成一团。"


def _infographic_failure_risk(data: Dict) -> str:
    return "这类内容最容易失效在“每个元素都重要”，结果观众一个重点都抓不住。图形越多，越需要有人替观众排先后。"


def _pure_visual_mix_rhythm_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "视觉节奏信息不足。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("scores", {}).get("impact") or 0.0), reverse=True)[:3], 3)
    return f"{refs} 这些段落最能看出纯靠画面时节奏还在不在。没有音乐扶着走时，剪辑、景别变化和画面碰撞本身就得继续往前推。"


def _pure_visual_mix_failure_risk(data: Dict) -> str:
    return "最容易塌的地方，是一开始有冲击，后面只剩连续漂亮镜头。纯视觉混剪要是没有内在节奏，很快就会从“有冲劲”掉成“有素材感”。"


def _pure_visual_mix_viewing_advice(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "先看最有冲击的几段，再判断后面是不是还在继续加压。"
    refs = _scene_refs(sorted(scenes, key=lambda s: float(s.get("weighted_score") or 0.0), reverse=True)[:3], 3)
    return f"观看建议：先看 {refs} 这些最强段落，确认它是不是能只靠画面自己带路；如果后面还在不断加压，这类内容就成立了。"


def _cinematic_life_atmosphere_analysis(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "氛围数据不足。"
    aesthetic_scores = [float(s.get("scores", {}).get("aesthetic_beauty") or 0.0) for s in scenes]
    lighting_keywords = ["逆光", "暖色", "冷色", "剪影", "光影", "质感", "氛围"]
    lighting_scenes = [s for s in scenes if any(kw in _scene_desc(s) for kw in lighting_keywords)]
    consistency = 1.0 - (max(aesthetic_scores) - min(aesthetic_scores)) / 10.0 if aesthetic_scores else 0.0
    avg_aesthetic = _avg(aesthetic_scores)
    text = f"美学一致性 {consistency*10:.1f}/10，平均美学分 {avg_aesthetic:.1f}/10。"
    if consistency >= 0.7 and avg_aesthetic >= 7.0:
        text += f"电影化手段统一且高质，{_scene_refs(lighting_scenes[:4], 4)} 等场景通过光影和色调营造稳定的情绪包裹感，氛围连贯性强。"
    elif consistency >= 0.5:
        text += f"电影化手段有一定统一性，但 {len(lighting_scenes)} 个光影场景分布不均，部分段落氛围断裂。"
    else:
        text += "电影化手段不统一，光影、色调、构图风格跳跃，氛围包裹感弱，更像技法展示而非情绪营造。"
    return text


def _cinematic_life_authenticity_check(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "真实感数据不足。"
    credibility_scores = [float(s.get("scores", {}).get("credibility") or 0.0) for s in scenes]
    aesthetic_scores = [float(s.get("scores", {}).get("aesthetic_beauty") or 0.0) for s in scenes]
    avg_credibility = _avg(credibility_scores)
    avg_aesthetic = _avg(aesthetic_scores)
    life_keywords = ["日常", "生活", "记录", "真实", "现场"]
    life_scenes = [s for s in scenes if any(kw in _scene_desc(s) for kw in life_keywords)]
    balance = abs(avg_aesthetic - avg_credibility)
    text = f"电影化手段 {avg_aesthetic:.1f}/10 vs 生活真实感 {avg_credibility:.1f}/10，差值 {balance:.1f}。"
    if balance <= 2.0 and avg_credibility >= 6.0:
        text += f"电影化处理与生活内容平衡良好，{_scene_refs(life_scenes[:4], 4)} 等场景既有质感又保留真实感，形式服务内容。"
    elif avg_aesthetic >= 7.5 and avg_credibility <= 5.0:
        text += f'电影化手段过重，生活真实感不足，存在“形式很满、内容很空”风险，{len(life_scenes)} 个生活场景占比偏低。'
    else:
        text += "电影化手段与生活内容未形成有效配合，需要更明确的内容支撑。"
    return text


def _commentary_mix_argument_structure(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "论点数据不足。"
    voiceover_scenes = [s for s in scenes if _voiceover(s)]
    argument_keywords = ["因为", "所以", "但是", "然而", "原因", "结果", "问题", "证明"]
    argument_scenes = [s for s in voiceover_scenes if any(kw in _voiceover(s) for kw in argument_keywords)]
    total_duration = sum(float(s.get("duration_seconds") or 0.0) for s in scenes)
    argument_duration = sum(float(s.get("duration_seconds") or 0.0) for s in argument_scenes)
    density = len(argument_scenes) / (total_duration / 60) if total_duration > 0 else 0.0
    text = f"论点密度 {density:.1f} 个/分钟，论点场景占比 {argument_duration/total_duration*100:.0f}%。"
    if density >= 2.0 and argument_duration / total_duration >= 0.4:
        text += f"{_scene_refs(argument_scenes[:5], 5)} 等场景持续输出论点，语言轨道逻辑链条清晰，论证结构完整。"
    elif density >= 1.0:
        text += f"论点密度适中，但 {_scene_refs(argument_scenes[:4], 4)} 等场景之间逻辑跳跃，论证链条不够紧密。"
    else:
        text += "论点密度偏低，语言轨道更像素材描述而非论证，评论向定位不明确。"
    return text


def _commentary_mix_information_division(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "信息分工数据不足。"
    voiceover_scenes = [s for s in scenes if _voiceover(s)]
    visual_info_keywords = ["画面", "镜头", "场景", "看到", "展示"]
    conflict_scenes = [s for s in voiceover_scenes if any(kw in _voiceover(s) for kw in visual_info_keywords)]
    info_density_scores = [float(s.get("analysis_dimensions", {}).get("information_efficiency") or 0.0) for s in scenes]
    avg_info = _avg(info_density_scores)
    text = f"信息效率均值 {avg_info:.1f}/10，检测到 {len(conflict_scenes)} 个视听信息冲突场景。"
    if len(conflict_scenes) <= len(voiceover_scenes) * 0.2 and avg_info >= 7.0:
        text += "语言负责论点，画面负责证据，信息分工清晰，两轨互补而非重复。"
    elif len(conflict_scenes) >= len(voiceover_scenes) * 0.4:
        text += f"{_scene_refs(conflict_scenes[:4], 4)} 等场景语言在描述画面内容，信息重复，分工不清，削弱信息效率。"
    else:
        text += "信息分工有一定区分，但部分场景语言和画面信息重叠，需要更明确的分工策略。"
    return text


def _concept_mv_imagery_consistency(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "意象数据不足。"
    descriptions = [_scene_desc(s) for s in scenes]
    all_text = " ".join(descriptions)
    imagery_keywords = ["光", "影", "水", "火", "镜", "窗", "路", "门", "手", "眼"]
    detected = {kw: all_text.count(kw) for kw in imagery_keywords if all_text.count(kw) > 0}
    dominant = max(detected, key=detected.get) if detected else None
    style_keywords = [_safe_text(s.get("storyboard", {}).get("visual_style")) for s in scenes]
    style_consistency = len(set(style_keywords)) / len(style_keywords) if style_keywords else 1.0
    text = f"视觉符号重复度：{len(detected)} 种意象，风格统一度 {(1-style_consistency)*10:.1f}/10。"
    if dominant and detected[dominant] >= 3 and style_consistency <= 0.3:
        text += f'核心意象“{dominant}”重复 {detected[dominant]} 次，视觉符号形成稳定主题，风格高度统一，意象一致性强。'
    elif detected and style_consistency <= 0.5:
        text += f"检测到 {', '.join(detected.keys())} 等意象，有一定重复但未形成主导符号，风格较统一但意象分散。"
    else:
        text += "视觉符号分散，风格跳跃，意象一致性弱，更像片段拼接而非概念统一的作品。"
    return text


def _concept_mv_emotion_curve(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "情绪曲线数据不足。"
    impact_scores = [float(s.get("scores", {}).get("impact") or 0.0) for s in scenes]
    memorability_scores = [float(s.get("scores", {}).get("memorability") or 0.0) for s in scenes]
    emotion_curve = [(impact + memo) / 2.0 for impact, memo in zip(impact_scores, memorability_scores)]
    peak_indices = [i for i, score in enumerate(emotion_curve) if score >= 7.5]
    curve_variance = max(emotion_curve) - min(emotion_curve) if emotion_curve else 0.0
    text = f"情绪曲线波动幅度 {curve_variance:.1f}，峰值时刻 {len(peak_indices)} 个。"
    if curve_variance >= 3.0 and len(peak_indices) >= 2:
        peak_scenes = [scenes[i] for i in peak_indices[:4] if i < len(scenes)]
        text += f"{_scene_refs(peak_scenes, 4)} 等场景形成情绪高潮，曲线起伏明显，与音乐结构同步性强，情绪渲染完整。"
    elif curve_variance >= 2.0:
        text += "情绪曲线有一定起伏，但峰值不够突出，情绪渲染偏向平稳氛围而非爆发式高潮。"
    else:
        text += "情绪曲线平缓，缺少明显起伏，更像背景音乐配画面，未形成情绪叙事结构。"
    return text


def _documentary_information_completeness(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "信息完整性数据不足。"
    voiceovers = [_voiceover(s) for s in scenes]
    all_text = " ".join(voiceovers)
    w5h1 = {
        "谁(Who)": ["人物", "角色", "他", "她", "我们", "团队"],
        "什么(What)": ["事件", "项目", "产品", "问题", "现象"],
        "何时(When)": ["时间", "日期", "年", "月", "天", "小时", "当时"],
        "何地(Where)": ["地点", "位置", "这里", "那里", "现场"],
        "为何(Why)": ["原因", "因为", "所以", "目的", "为了"],
        "如何(How)": ["方法", "步骤", "过程", "通过", "实现"],
    }
    coverage = {label: any(kw in all_text for kw in keywords) for label, keywords in w5h1.items()}
    covered_count = sum(coverage.values())
    info_density_scores = [float(s.get("analysis_dimensions", {}).get("information_efficiency") or 0.0) for s in scenes]
    avg_info = _avg(info_density_scores)
    text = f"5W1H覆盖度 {covered_count}/6，信息密度均值 {avg_info:.1f}/10。"
    if covered_count >= 5 and avg_info >= 7.0:
        covered = [label for label, val in coverage.items() if val]
        text += f"信息要素完整（{', '.join(covered)}），信息密度高，纪实内容结构完整，观众能获得清晰的事件全貌。"
    elif covered_count >= 3:
        missing = [label for label, val in coverage.items() if not val]
        text += f"部分信息要素缺失（{', '.join(missing)}），信息完整性不足，观众可能产生疑问。"
    else:
        text += "信息要素严重缺失，纪实内容不完整，更像片段记录而非完整讲述。"
    return text


def _documentary_credibility_assessment(data: Dict) -> str:
    scenes = _ordered_scenes(data)
    if not scenes:
        return "可信度数据不足。"
    credibility_scores = [float(s.get("scores", {}).get("credibility") or 0.0) for s in scenes]
    high_credibility = [s for s in scenes if float(s.get("scores", {}).get("credibility") or 0.0) >= 7.0]
    avg_credibility = _avg(credibility_scores)
    real_keywords = ["现场", "实拍", "记录", "真实", "采访", "拍摄"]
    real_scenes = [s for s in scenes if any(kw in _scene_desc(s) for kw in real_keywords)]
    text = f"可信度均值 {avg_credibility:.1f}/10，高可信场景 {len(high_credibility)} 个，现场感场景 {len(real_scenes)} 个。"
    if avg_credibility >= 7.0 and len(high_credibility) >= len(scenes) * 0.6:
        text += f"{_scene_refs(high_credibility[:5], 5)} 等场景可信度高，现场感强，纪实内容真实可靠，观众信任度高。"
    elif avg_credibility >= 5.0:
        text += f"可信度中等，{_scene_refs(real_scenes[:4], 4)} 等场景有现场感，但部分段落缺少实证支撑。"
    else:
        text += "可信度偏低，现场感不足，纪实定位与实际呈现不匹配，观众可能质疑真实性。"
    return text


def _narrative_groups(data: Dict) -> Dict[str, List[Dict]]:
    ordered = _ordered_scenes(data)
    total = len(ordered)
    setup = [scene for scene in ordered if _safe_text(scene.get("story_role")) == "开场建立"]
    conflict = [scene for scene in ordered if _safe_text(scene.get("story_role")) in {"世界展开", "中段推进"}]
    climax = [scene for scene in ordered if _safe_text(scene.get("story_role")) == "高潮收束" and not _looks_like_promo_card(scene)]
    resolution = [scene for scene in ordered if _safe_text(scene.get("story_role")) == "高潮收束"][-max(1, len(climax) // 2 or 1):]

    if not setup:
        setup = ordered[:max(1, int(total * 0.2))]
    if not conflict:
        conflict = ordered[max(1, int(total * 0.2)):max(2, int(total * 0.6))]
    if not climax:
        climax = ordered[max(2, int(total * 0.6)):max(3, int(total * 0.8))]
    if not resolution:
        resolution = ordered[max(3, int(total * 0.8)):]
    if ordered:
        # Short narrative samples still need representative scenes for each
        # report section, otherwise route-specific figure blocks crash.
        fallback_tail = ordered[-1:]
        conflict = conflict or fallback_tail
        climax = climax or conflict or fallback_tail
        resolution = resolution or climax or fallback_tail
    high_score_scenes = sorted(ordered, key=lambda s: float(s.get("weighted_score") or 0.0), reverse=True)[:8]
    return {
        "setup": setup,
        "conflict": conflict,
        "climax": climax,
        "resolution": resolution,
        "investigation": conflict,
        "stage": climax,
        "deduction": resolution,
        "key_moments": high_score_scenes,
    }


def _narrative_story_summary(data: Dict) -> str:
    groups = _narrative_groups(data)
    setup_refs = _scene_refs(groups["setup"], 4)
    conflict_refs = _scene_refs(groups["conflict"], 4)
    climax_refs = _scene_refs(groups["climax"], 4)
    resolution_refs = _scene_refs(groups["resolution"], 4)

    setup_desc = " / ".join(_scene_desc(s)[:20] for s in groups["setup"][:2] if _scene_desc(s))
    conflict_desc = " / ".join(_scene_desc(s)[:20] for s in groups["conflict"][:2] if _scene_desc(s))
    climax_desc = " / ".join(_scene_desc(s)[:20] for s in groups["climax"][:2] if _scene_desc(s))
    setup_funcs = _top_text([_safe_text(s.get("story_function")) for s in groups["setup"]], 2)
    conflict_funcs = _top_text([_safe_text(s.get("story_function")) for s in groups["conflict"]], 2)
    climax_funcs = _top_text([_safe_text(s.get("story_function")) for s in groups["climax"]], 2)

    parts = [
        f"这条片子的叙事不是靠一句总结撑起来，而是先用 {setup_refs} 把 {setup_funcs} 立住（{setup_desc}），让观众先进入这条片的世界、人物和情绪基调。",
        f"随后 {conflict_refs} 把 {conflict_funcs} 往前推（{conflict_desc}），叙事重心从“先看清楚”转向“开始发生变化”。",
        f"到 {climax_refs} 这几段，{climax_funcs} 被明显抬高（{climax_desc}），全片的情绪、动作或意象在这里形成高点。",
        f"最后再用 {resolution_refs} 把后段收住，让前面的铺垫和高点有一个明确落点，所以它整体呈现的是一条能被顺着跟下去的叙事线。",
    ]
    return "".join(parts)


def _narrative_node_lines(data: Dict) -> List[str]:
    groups = _narrative_groups(data)
    lines = [
        f"- 开场建立：{_scene_refs(groups['setup'], 4)} 先把 {_top_text([_safe_text(s.get('story_function')) for s in groups['setup']], 2)} 立起来。",
        f"- 中段推进：{_scene_refs(groups['conflict'], 4)} 继续把 {_top_text([_safe_text(s.get('story_function')) for s in groups['conflict']], 2)} 往前送。",
        f"- 高点抬升：{_scene_refs(groups['climax'], 4)} 把全片最集中的情绪、动作或意象推到前面来。",
        f"- 尾声收束：{_scene_refs(groups['resolution'], 4)} 给前面的铺垫和高点一个落点。",
    ]
    return lines


def _narrative_visual_paragraph(data: Dict) -> str:
    groups = _narrative_groups(data)
    setup_refs = _scene_refs(groups["setup"], 4)
    conflict_refs = _scene_refs(groups["conflict"], 4)
    climax_refs = _scene_refs(groups["climax"], 4)

    setup_visual = " / ".join(_scene_desc(s)[:25] for s in groups["setup"][:2] if _scene_desc(s))
    conflict_visual = " / ".join(_scene_desc(s)[:25] for s in groups["conflict"][:2] if _scene_desc(s))
    climax_visual = " / ".join(_scene_desc(s)[:25] for s in groups["climax"][:2] if _scene_desc(s))

    return (
        f"视觉轨道真正起作用的地方，不是单纯把场面拍漂亮，而是给每一段叙事安排了明确任务。{setup_refs} 这一批镜头先把人物、空间和基调立起来（{setup_visual}），"
        f"让情境不是一句话，而是一个能被直接看见的状态；{conflict_refs} 这批镜头继续把关系、动作或情绪往前推（{conflict_visual}），让叙事不至于停在开场；"
        f"{climax_refs} 则把镜头功能推向高点（{climax_visual}），全片最强的视觉能量和主题意象会在这里集中冒出来。"
    )


def _narrative_language_paragraph(data: Dict) -> str:
    groups = _narrative_groups(data)
    key_moments = groups["key_moments"]
    dialogue_scenes = [s for s in key_moments if _report_voiceover(s)]

    if dialogue_scenes:
        refs = _scene_refs(dialogue_scenes[:5], 5)
        sample_text = " / ".join(_report_voiceover(s)[:20] for s in dialogue_scenes[:2] if _report_voiceover(s))
        return (
            f"语言轨道在这条片子里主要负责推进叙事和交代关键信息。像 {refs} 这些段落里的语言内容（{sample_text}），"
            "承担着说明情节、揭示人物关系或推动故事发展的功能，让观众能够跟上叙事逻辑。"
        )
    return "语言轨道在这条片子里更多承担情绪和氛围表达，不靠它来完整讲清故事，而是让它给画面加上一层情感底色。"


def _narrative_pairing_paragraph(data: Dict, alignment: Dict[str, object]) -> str:
    groups = _narrative_groups(data)
    conflict_refs = _scene_refs(groups["conflict"], 4)

    text = (
        "这条片子的视听关系不是简单重复，而是有明确分工。通常是画面先给出人物关系和场景状态，语言再补充关键信息和情感表达；"
    )

    if alignment["level"] == "偏低":
        text += f" 它最明显的短板在于：视觉已经把故事推到高潮，但音频和语言并不总是同步接住这个情绪高点，所以观众会觉得故事看懂了，情绪却没有在同一瞬间被一起顶上去。"
    else:
        text += " 两条轨道在关键节点上能互相接住，所以观众既能看懂事件，也能在高点被同时推到。"
    return text


def _narrative_integrity_paragraph(data: Dict) -> str:
    avg_narrative = _avg([float(scene.get("analysis_dimensions", {}).get("narrative_function") or 0.0) for scene in data.get("scenes", [])])
    if avg_narrative >= 7.2:
        return "从完整性看，这条故事是成立的。故事目标、发展过程、关键转折和最终解决都能被跟上，所以它不只是“有剧情感”，而是真的把一条故事讲到了结尾。真正的不足不在故事缺骨架，而在部分视听节奏没有完全咬合。"
    return "从完整性看，这条内容已经有故事轮廓，但局部推进还更像连续氛围段落，某些节点要靠观众自己补连接，因此更接近“情绪线强于故事线”。"


def _trailer_groups(data: Dict) -> Dict[str, List[Dict]]:
    ordered = _ordered_scenes(data)
    total = len(ordered)
    opening = ordered[:max(1, int(total * 0.15))]
    setup = ordered[max(1, int(total * 0.15)):max(2, int(total * 0.35))]
    investigation = ordered[max(2, int(total * 0.35)):max(3, int(total * 0.55))]
    escalation = ordered[max(3, int(total * 0.55)):max(4, int(total * 0.8))]
    payoff = ordered[max(4, int(total * 0.8)):]
    cards = [scene for scene in ordered if _looks_like_promo_card(scene)]
    peaks = sorted(
        ordered,
        key=lambda scene: (
            float(scene.get("scores", {}).get("impact") or 0.0),
            float(scene.get("weighted_score") or 0.0),
        ),
        reverse=True,
    )[:6]
    return {
        "opening": opening or ordered[:1],
        "setup": setup or opening or ordered[:1],
        "investigation": investigation or setup or ordered[:1],
        "escalation": escalation or ordered[:1],
        "payoff": payoff or ordered[-1:],
        "cards": cards,
        "peaks": peaks,
    }


def _trailer_story_summary(data: Dict) -> str:
    groups = _trailer_groups(data)
    opening_refs = _best_scene_refs(groups["opening"], 2)
    setup_refs = _best_scene_refs(groups["setup"], 2)
    investigation_refs = _best_scene_refs(groups["investigation"], 2)
    escalation_refs = _best_scene_refs(groups["escalation"], 3, prefer_impact=True)
    payoff_refs = _best_scene_refs(groups["payoff"], 3, prefer_impact=True)
    opening_phrase = _best_scene_phrase(groups["opening"])
    setup_phrase = _best_scene_phrase(groups["setup"])
    investigation_phrase = _best_scene_phrase(groups["investigation"])
    escalation_phrase = _best_scene_phrase(groups["escalation"], prefer_impact=True)
    payoff_phrase = _best_scene_phrase(groups["payoff"], prefer_impact=True)
    return (
        f"开头先拿 {opening_refs} 勾人，把不安气氛先压下来（{opening_phrase}）。"
        f"紧接着用 {setup_refs} 把现实入口和故事前提摆清楚（{setup_phrase}），"
        f"中段再靠 {investigation_refs} 把人一步步往更深处拽（{investigation_phrase}）。"
        f"等观众刚把规则摸到一点边，{escalation_refs} 就把异常空间、人物失控和生存压力一起掀上来（{escalation_phrase}），"
        f"最后通过 {payoff_refs} 把最后一记高能和片名收口一起钉住（{payoff_phrase}）。"
        "整条片讲的很直接：有人闯进了一个不可能存在的空间，而且越往里走，代价越吓人。"
    )


def _best_card_scene(scenes: Sequence[Dict]) -> Dict | None:
    if not scenes:
        return None
    with_release = [scene for scene in scenes if _looks_like_release_text(_onscreen_text(scene))]
    candidates = with_release or list(scenes)
    return sorted(candidates, key=lambda scene: int(scene.get("scene_number", 0)), reverse=True)[0]


def _trailer_highlight_specs(data: Dict) -> List[Tuple[str, Dict, str]]:
    groups = _trailer_groups(data)
    return [
        (
            "开场勾人",
            _best_representative_scene(groups["opening"], prefer_impact=True),
            "这一张先把人拽住，观众还没搞清楚发生了什么，气氛已经先钻进来了。",
        ),
        (
            "现实入口",
            _best_representative_scene(groups["setup"]),
            "这一张把“这事是从哪儿开始不对劲的”交代清楚，预告的门就是从这里打开的。",
        ),
        (
            "继续深入",
            _best_representative_scene(groups["investigation"]),
            "这一张能看出人物已经不是随便看看，而是真的要往里面走，危险感开始从想法变成行动。",
        ),
        (
            "危险升级",
            _best_representative_scene(groups["escalation"], prefer_impact=True) or _best_representative_scene(groups["peaks"], prefer_impact=True),
            "这一张把异常空间和人物危机真正顶到台前，是整支预告最抓人的那一下。",
        ),
        (
            "最终一击",
            _best_representative_scene(groups["payoff"], prefer_impact=True) or _best_representative_scene(groups["cards"], prefer_impact=True) or _best_representative_scene(groups["peaks"], prefer_impact=True),
            "这一张负责把最后那口气卡在观众胸口，走出报告以后脑子里还会留着它。",
        ),
        (
            "收口提醒",
            _best_card_scene(groups["cards"]),
            "这一张把片名和档期钉牢，前面的不安感到这里才真正变成“我记住这部片了”。",
        ),
    ]


def _trailer_premise_paragraph(data: Dict) -> str:
    groups = _trailer_groups(data)
    return (
        f"{_best_scene_refs(groups['opening'], 2, prefer_impact=True)} 和 {_best_scene_refs(groups['setup'], 2)} 这一段最重要。"
        f"前者先把人心吊起来，后者把现实入口和异常前提摆出来：{_best_scene_phrase(groups['setup'])}。"
        "看到这里，观众心里大概已经有数了: 这不是普通探险，而是有人真的摸到了一个不该存在的地方。"
    )


def _trailer_escalation_paragraph(data: Dict) -> str:
    groups = _trailer_groups(data)
    return (
        f"{_best_scene_refs(groups['investigation'], 2)} 先把行动往前推，接着 {_best_scene_refs(groups['escalation'], 3, prefer_impact=True)} 直接把危险掀开。"
        f"这里最管用的画面是：{_best_scene_phrase(groups['escalation'], prefer_impact=True)}。"
        "前面还是“怪”，到这里就变成“会出事”，而且是会把人整个人吞进去的那种出事。"
    )


def _trailer_sell_paragraph(data: Dict) -> str:
    groups = _trailer_groups(data)
    card_refs = _best_scene_refs(groups["cards"], 4)
    if card_refs == "暂无明确场景":
        card_refs = _best_scene_refs(groups["payoff"], 4, prefer_impact=True)
    return (
        f"{_best_scene_refs(groups['payoff'], 2, prefer_impact=True)} 把最后一记恐惧顶住，{card_refs} 再把片名和档期钉牢。"
        "看到这儿，观众手里不只是剩下一股情绪，还会顺手记住作品名和上映信息，这才像一支真正完成任务的预告。"
    )


def _event_brand_groups(data: Dict) -> Dict[str, List[Dict]]:
    ordered = _ordered_scenes(data)
    total = len(ordered)
    opening = ordered[:max(1, int(total * 0.15))]
    spectacle = [scene for scene in ordered if any(word in _scene_desc(scene) + _safe_text(scene.get("storyboard", {}).get("visual_style")) for word in ("灯阵", "字阵", "夜空", "无人机", "烟花", "品牌图形"))]
    crowd = [scene for scene in ordered if any(word in _scene_desc(scene) for word in ("人群", "观众", "合唱", "一起", "欢呼", "大家"))]
    human = [scene for scene in ordered if any(word in _scene_desc(scene) for word in ("女孩", "男生", "女性", "长者", "孩子", "情侣", "家"))]
    product = [scene for scene in ordered if any(word in _scene_desc(scene) + _safe_text(scene.get("storyboard", {}).get("technique")) for word in ("饮料", "喝", "举起饮料", "举瓶", "瓶身", "产品体验"))]
    closing = ordered[max(1, int(total * 0.8)):]
    return {
        "opening": opening or ordered[:1],
        "spectacle": spectacle or ordered[:1],
        "crowd": crowd or ordered[:1],
        "human": human or ordered[:1],
        "product": product or ordered[:1],
        "closing": closing or ordered[-1:],
    }


def _journey_brand_groups(data: Dict) -> Dict[str, List[Dict]]:
    ordered = _ordered_scenes(data)
    total = len(ordered)
    opening = ordered[:max(1, int(total * 0.18))]
    clue = [scene for scene in ordered if any(word in _scene_desc(scene) for word in ("书页", "纸页", "照片", "纸片", "地图", "书"))]
    arrival = [scene for scene in ordered if any(word in _scene_desc(scene) for word in ("巷子", "台阶", "白墙", "海", "小镇", "门", "港口"))]
    portrait = [scene for scene in ordered if any(word in _scene_desc(scene) for word in ("脸", "眼神", "侧脸", "回头", "坐在", "站在"))]
    poetic = [scene for scene in ordered if any(word in _scene_desc(scene) + _safe_text(scene.get("storyboard", {}).get("visual_style")) for word in ("叠", "海", "风", "光", "影", "诗", "天空"))]
    closing = ordered[max(1, int(total * 0.8)):]
    brand_tail = [scene for scene in closing if _looks_like_promo_card(scene) or any(word in _onscreen_text(scene) for word in ("Monos", "品牌"))]
    return {
        "opening": opening or ordered[:1],
        "clue": clue or ordered[:1],
        "arrival": arrival or ordered[:1],
        "portrait": portrait or ordered[:1],
        "poetic": poetic or ordered[:1],
        "closing": closing or ordered[-1:],
        "brand_tail": brand_tail or closing or ordered[-1:],
    }


def _event_brand_story_summary(data: Dict) -> str:
    groups = _event_brand_groups(data)
    return (
        f"这条广告先用 {_best_scene_refs(groups['opening'], 2)} 把夏夜现场立起来，"
        f"再用 {_best_scene_refs(groups['spectacle'], 2, prefer_impact=True)} 把品牌符号直接挂到天空上。"
        f"接着 {_best_scene_refs(groups['crowd'], 2)} 和 {_best_scene_refs(groups['human'], 2)} 轮着把“大家一起唱”的热度推高，"
        f"最后用 {_best_scene_refs(groups['product'], 1)} 和 {_best_scene_refs(groups['closing'], 2, prefer_impact=True)} 把产品体验和周年记忆一起收住。"
        "它讲的不是危险，也不是悬念，而是一场会让不同年龄的人都想加入的品牌节庆。"
    )


def _journey_brand_story_summary(data: Dict) -> str:
    groups = _journey_brand_groups(data)
    return (
        f"这条短片一开始先用 {_best_scene_refs(groups['opening'], 2)} 把人安静带上路，"
        f"然后靠 {_best_scene_refs(groups['clue'], 2)} 把纸页、旧物和线索慢慢摊开。"
        f"等人物真正走进 {_best_scene_refs(groups['arrival'], 2)} 这些地点，旅程才从脑子里的问题变成脚下的风景。"
        f"中段的 {_best_scene_refs(groups['portrait'], 2)} 和 {_best_scene_refs(groups['poetic'], 2)} 把情绪和地点揉在一起，"
        f"最后再让 {_best_scene_refs(groups['brand_tail'], 2)} 把品牌名字轻轻落下来。"
        "它更像一封写给旅途和命运感的信，不是在吊人胃口。"
    )


def _framework_family(route: Dict[str, object]) -> str:
    framework = route["framework"]
    if framework in LANGUAGE_LED_FRAMEWORKS:
        return "language_led"
    if framework in ATMOSPHERIC_FRAMEWORKS:
        return "atmospheric"
    if framework in MEME_FRAMEWORKS:
        return "meme"
    if framework in GRAPHIC_FRAMEWORKS:
        return "graphic"
    return "generic"


def _technical_explainer_groups(data: Dict) -> Dict[str, List[Dict]]:
    ordered = _ordered_scenes(data)
    minimal = _group_scenes_by_count(ordered)
    if minimal.get("_mode") != "full":
        opening = minimal["opening"]
        middle = minimal["middle"]
        closing = minimal["closing"]
        return {
            "opening": opening,
            "question": opening,
            "overview": middle or opening,
            "detail": middle or opening,
            "step": middle or opening,
            "recap": closing or middle or opening,
            "_mode": minimal["_mode"],
        }

    opening = _scene_slice(ordered, 0.0, TECH_OPENING_RATIO)
    early = _scene_slice(ordered, 0.0, TECH_EARLY_RATIO, min_items=2)
    middle = _scene_slice(ordered, TECH_MIDDLE_START_RATIO, TECH_MIDDLE_END_RATIO, min_items=2)
    late = _scene_slice(ordered, TECH_LATE_START_RATIO, 1.0)
    question = [scene for scene in early if _matches_any(_voiceover(scene), QUESTION_PATTERNS)]
    overview = [scene for scene in middle if any(word in _scene_haystack(scene) for word in OVERVIEW_KEYWORDS)]
    detail = [scene for scene in middle if any(word in _scene_haystack(scene) for word in DETAIL_KEYWORDS)]
    step = [scene for scene in middle if _matches_any(_voiceover(scene), STEP_PATTERNS + QUESTION_PATTERNS)]
    recap = [scene for scene in late if _matches_any(_voiceover(scene) + " " + _onscreen_text(scene), RECAP_PATTERNS)]
    return {
        "opening": opening or ordered[:1],
        "question": question or opening or ordered[:1],
        "overview": overview or middle or ordered[:1],
        "detail": detail or middle or ordered[:1],
        "step": step or middle or ordered[:1],
        "recap": recap or ordered[-1:],
        "_mode": "full",
    }


def _technical_explainer_story_summary(data: Dict) -> str:
    groups = _technical_explainer_groups(data)
    mode = groups.get("_mode")
    if mode == "single":
        return (
            f"这条片主要靠 {_best_scene_refs(groups['question'], 1)} 这个核心场景，把问题抛出、关键动作和结论压在同一次讲解里。"
            "它不是分很多段慢慢展开，而是用一个足够清楚的镜头先把门打开，让观众先跟上这件事到底厉害在哪。"
        )
    if mode in {"paired", "minimal"}:
        return (
            f"它先用 {_best_scene_refs(groups['question'], 1)} 把问题立住，再用 {_best_scene_refs(groups['detail'], 2)} 把关键动作和解释往前推。"
            "这种短结构更看镜头本身够不够清楚，只要核心动作和讲解能在有限场景里扣上，观众一样能快速看懂。"
        )
    return (
        f"它先用 {_best_scene_refs(groups['question'], 2)} 把问题抛出来，让观众先知道这件事到底厉害在哪。"
        f"然后靠 {_best_scene_refs(groups['overview'], 2)} 把整套动作的站位和节奏摊开，"
        f"再用 {_best_scene_refs(groups['detail'], 2)} 和 {_best_scene_refs(groups['step'], 2)} 把关键动作一刀刀拆给你看。"
        f"最后 {_best_scene_refs(groups['recap'], 2)} 再把结论收回来，所以这条片真正想做的，是把“原来看不懂的速度”拆成“现在终于看懂了”。"
    )


def _technical_explainer_highlight_specs(data: Dict) -> List[Tuple[str, Dict, str]]:
    groups = _technical_explainer_groups(data)
    seen: set[int] = set()
    ordered = sorted(
        [scene for scene in _ordered_scenes(data) if _scene_screenshot(scene)],
        key=lambda scene: _scene_priority(scene, prefer_impact=True),
        reverse=True,
    )
    cleaned = []
    steps = [
        ("问题抛出", groups["question"], True, "先把最核心的问题摆到桌上，读者才知道后面为什么值得看。"),
        ("整体站位", groups["overview"], False, "这一张负责让人先看懂全局，不然细节拆再多也会乱。"),
        ("关键细节", groups["detail"], False, "真正让人长知识的，往往就是这些一闪而过但决定成败的小动作。"),
        ("步骤拆开", groups["step"], False, "这一张要告诉读者事情不是神秘完成的，而是一环扣一环做出来的。"),
        ("爽点总览", groups["overview"], True, "看懂以后最爽的，通常就是再回头看一遍整体配合为什么这么整齐。"),
        ("结论回看", groups["recap"], True, "最后这张负责把“所以它厉害在哪”稳稳收住。"),
    ]
    for title, scenes, prefer_impact, note in steps:
        scene = _best_unique_scene(scenes, seen, prefer_impact=prefer_impact)
        if scene is None:
            scene = _best_unique_scene(ordered, seen, prefer_impact=True)
        if scene is None:
            continue
        seen.add(int(scene.get("scene_number", 0)))
        cleaned.append((title, scene, note))
    return cleaned


def _event_brand_highlight_specs(data: Dict) -> List[Tuple[str, Dict, str]]:
    groups = _event_brand_groups(data)
    return [
        ("现场开场", _best_representative_scene(groups["opening"]), "先把夜色、海港和现场规模立住，读者一下就知道这是节庆不是剧情悬疑。"),
        ("品牌奇观", _best_representative_scene(groups["spectacle"], prefer_impact=True), "这一张把品牌符号直接做成天幕奇观，视觉记忆点会很强。"),
        ("群体同唱", _best_representative_scene(groups["crowd"]), "这一张要让人看明白核心不是某个人，而是一整群人一起被点亮。"),
        ("人的温度", _best_representative_scene(groups["human"]), "大场面之外还要有人脸和关系，不然广告只会剩热闹，没有感情。"),
        ("产品落地", _best_representative_scene(groups["product"]), "这一张负责把产品真正接回现场，不让品牌只停在天上。"),
        ("收口记忆", _best_representative_scene(groups["closing"], prefer_impact=True), "最后要把品牌名字或纪念点钉牢，让热闹有一个清楚的落点。"),
    ]


def _journey_brand_highlight_specs(data: Dict) -> List[Tuple[str, Dict, str]]:
    groups = _journey_brand_groups(data)
    return [
        ("上路的心情", _best_representative_scene(groups["opening"]), "先把人物心里那点不安和期待拍出来，整条片子的调子才会准。"),
        ("线索物件", _best_representative_scene(groups["clue"]), "纸页、旧物这些东西很小，但它们决定了这条片是不是有回味。"),
        ("真正抵达", _best_representative_scene(groups["arrival"]), "这张要让读者感到人真的到了一个地方，而不是一直在想象里飘。"),
        ("人物状态", _best_representative_scene(groups["portrait"]), "旅程片最终还是要落回一张脸，不然地点再美也只剩旅游片。"),
        ("诗意高点", _best_representative_scene(groups["poetic"], prefer_impact=True), "这张负责把地点、风和心事揉成一股气，让人记住这条片的味道。"),
        ("品牌尾声", _best_card_scene(groups["brand_tail"]) or _best_representative_scene(groups["brand_tail"]), "最后这张得让品牌出现得自然，不抢戏，但也不能让人看完还不知道是谁。"),
    ]


def _language_led_groups(data: Dict) -> Dict[str, List[Dict]]:
    ordered = _ordered_scenes(data)
    total = len(ordered)
    opening = ordered[:max(1, int(total * 0.15))]
    early = ordered[: max(2, int(total * 0.35))]
    late = ordered[max(1, int(total * 0.7)) :]
    issue = [scene for scene in early if _matches_any(_voiceover(scene), ("为什么", "怎么", "怎麼", "如何", r"\?", "？", "问题", "原因", "What", "How", "Why"))]
    overview = [scene for scene in ordered if any(word in _scene_desc(scene) + _safe_text(scene.get("storyboard", {}).get("shot_size")) + _onscreen_text(scene) for word in ("大全景", "全景", "图", "示意", "结构", "整体", "总览", "框架", "字卡", "图示"))]
    detail = [scene for scene in ordered if any(word in _scene_desc(scene) + _safe_text(scene.get("storyboard", {}).get("shot_size")) + _safe_text(scene.get("storyboard", {}).get("technique")) for word in ("特写", "近景", "细节", "局部", "手", "按钮", "图标", "画面文字"))]
    proof = [scene for scene in ordered if _matches_any(_voiceover(scene), ("首先", "然后", "接着", "所以", "因为", "需要", "负责", "结果", "原来", "说明", "就是", "第一", "第二", "第三", "例如"))]
    recap = [scene for scene in late if _matches_any(_voiceover(scene) + " " + _onscreen_text(scene), ("最后", "總", "总", "总结", "结论", "所以", "因此", "这就是"))]
    return {
        "opening": opening or ordered[:1],
        "issue": issue or opening or ordered[:1],
        "overview": overview or ordered[:1],
        "detail": detail or ordered[:1],
        "proof": proof or ordered[:1],
        "recap": recap or ordered[-1:],
    }


def _language_led_summary(data: Dict, route: Dict[str, object]) -> str:
    groups = _language_led_groups(data)
    verbs = {
        "documentary_generic": "把事情讲清楚",
        "commentary_mix": "讲观点",
        "lecture_performance": "带着观众听懂一件事",
        "hybrid_commentary": "用多种素材撑住同一条判断",
        "infographic_animation": "把信息变成更好吞的图形节奏",
        "narrative_motion_graphics": "让图形和语言一起把线索推出来",
    }
    lead = verbs.get(route["framework"], "把一件事讲明白")
    return (
        f"它主要在{lead}。开头先用 {_best_scene_refs(groups['issue'], 2)} 把问题或主线提出来，"
        f"接着 {_best_scene_refs(groups['overview'], 2)} 把整体框架摊开，"
        f"再靠 {_best_scene_refs(groups['detail'], 2)} 和 {_best_scene_refs(groups['proof'], 2)} 把关键点一层层拆给观众。"
        f"最后 {_best_scene_refs(groups['recap'], 2)} 再把话收回来，所以看完以后脑子里通常会留下一条清楚的线。"
    )


def _language_led_highlight_specs(data: Dict, route: Dict[str, object]) -> List[Tuple[str, Dict, str]]:
    groups = _language_led_groups(data)
    return [
        ("问题抛出", _best_representative_scene(groups["issue"]), "先把最核心的问题摆出来，读者才知道后面为什么要继续看。"),
        ("整体框架", _best_representative_scene(groups["overview"]), "这一张先把全局说明白，不然细节再多也会散。"),
        ("关键细节", _best_representative_scene(groups["detail"]), "真正让人一下开窍的，常常就是这些容易被忽略的小动作或小信息。"),
        ("论证推进", _best_representative_scene(groups["proof"]), "这一张要让人看见主讲思路是怎么一环扣一环往前推的。"),
        ("回到整体", _best_representative_scene(groups["overview"], prefer_impact=True), "看懂细节以后再回头看全局，观众更容易产生“原来是这样”的通透感。"),
        ("结论回看", _best_representative_scene(groups["recap"], prefer_impact=True), "最后这张要把结论稳稳收住，不让前面的理解散掉。"),
    ]


def _atmospheric_groups(data: Dict) -> Dict[str, List[Dict]]:
    ordered = _ordered_scenes(data)
    total = len(ordered)
    opening = ordered[:max(1, int(total * 0.15))]
    human = [scene for scene in ordered if any(word in _scene_desc(scene) for word in ("人", "她", "他", "女孩", "男生", "女人", "男人", "背影", "笑", "脸"))]
    motif = [scene for scene in ordered if any(word in _scene_desc(scene) + _safe_text(scene.get("storyboard", {}).get("visual_style")) for word in ("海", "光", "影", "风", "夜", "色", "意象", "氛围", "质感", "天空", "剪影", "灯"))]
    rhythm = [scene for scene in ordered if float(scene.get("scores", {}).get("impact") or 0.0) >= 8.0 or _safe_text(scene.get("storyboard", {}).get("camera_movement"))]
    crest = sorted(ordered, key=lambda scene: _scene_priority(scene, prefer_impact=True), reverse=True)[: max(1, min(6, len(ordered)))]
    closing = ordered[max(1, int(total * 0.75)) :]
    return {
        "opening": opening or ordered[:1],
        "human": human or ordered[:1],
        "motif": motif or ordered[:1],
        "rhythm": rhythm or ordered[:1],
        "crest": crest or ordered[:1],
        "closing": closing or ordered[-1:],
    }


def _atmospheric_summary(data: Dict, route: Dict[str, object]) -> str:
    groups = _atmospheric_groups(data)
    lead = {
        "mix_music": "把素材剪成越来越上头的节奏体验",
        "concept_mv": "用意象和情绪把人慢慢包进去",
        "cinematic_life": "把普通生活裹上一层电影感",
        "hybrid_music": "用几种风格一起堆一股情绪浪",
        "hybrid_ambient": "把氛围慢慢养出来",
        "pure_visual_mix": "靠画面之间的碰撞自己往前走",
        "silent_reality": "全靠画面把观察感撑起来",
        "silent_performance": "靠身体和表情接管情绪",
        "narrative_mix": "把零散片段重新拧成一股感觉",
    }.get(route["framework"], "制造一种能被记住的感觉")
    return (
        f"它主要在 {lead}。开头先用 {_best_scene_refs(groups['opening'], 2)} 把气氛种下去，"
        f"再靠 {_best_scene_refs(groups['human'], 2)} 和 {_best_scene_refs(groups['motif'], 2)} 把人和视觉符号慢慢拧到一起。"
        f"等 {_best_scene_refs(groups['rhythm'], 2)} 和 {_best_scene_refs(groups['crest'], 2)} 把节奏抬起来，观众就会被整股情绪带着走。"
        f"最后 {_best_scene_refs(groups['closing'], 2)} 再把余味留住。"
    )


def _atmospheric_highlight_specs(data: Dict, route: Dict[str, object]) -> List[Tuple[str, Dict, str]]:
    groups = _atmospheric_groups(data)
    return [
        ("气氛开场", _best_representative_scene(groups["opening"]), "先把这条片子的温度、颜色和呼吸感定下来。"),
        ("人物落点", _best_representative_scene(groups["human"]), "不管多抒情，最后还是要有人能让观众代进去。"),
        ("意象锚点", _best_representative_scene(groups["motif"]), "这一张负责把整条片最能代表味道的视觉符号钉出来。"),
        ("节奏抬升", _best_representative_scene(groups["rhythm"], prefer_impact=True), "这里会把原本慢慢养的情绪往上托一把。"),
        ("情绪高点", _best_representative_scene(groups["crest"], prefer_impact=True), "这一张应该是全片最能让人记住的一口气。"),
        ("收口余味", _best_representative_scene(groups["closing"]), "最后留的不是信息，而是余味。"),
    ]


def _meme_summary(data: Dict, route: Dict[str, object]) -> str:
    ordered = sorted(_ordered_scenes(data), key=lambda scene: _scene_priority(scene, prefer_impact=True), reverse=True)
    refs = _scene_refs(ordered, 4)
    return f"它主要在制造反差、梗点和即时反应。像 {refs} 这些地方，画面和声音一顶上来，观众会先笑出来，再去想它到底是怎么把这个点做成的。"


def _meme_highlight_specs(data: Dict, route: Dict[str, object]) -> List[Tuple[str, Dict, str]]:
    ordered = sorted(_ordered_scenes(data), key=lambda scene: _scene_priority(scene, prefer_impact=True), reverse=True)
    labels = ["梗源建立", "反差瞬间", "表情反应", "笑点叠加", "高潮包袱", "尾巴回钩"]
    notes = [
        "先让人知道这条片的笑点从哪冒出来。",
        "这一张要把最关键的反差顶出来。",
        "好笑很多时候要靠人的反应落地。",
        "不是只有一个点，要看它会不会连续往上拱。",
        "这一张负责把整条片最狠的那一下钉住。",
        "最后还要留个小尾巴，不然笑点会散。",
    ]
    return [(label, scene, note) for label, note, scene in zip(labels, notes, ordered[:6])]


def _graphic_summary(data: Dict, route: Dict[str, object]) -> str:
    ordered = _ordered_scenes(data)
    refs = _scene_refs(ordered, 4)
    return f"它主要靠图形、排版和动效把信息变得更好吞。{refs} 这些地方最能看出它不是单纯在动，而是在带着观众一层层往下理解。"


def _graphic_highlight_specs(data: Dict, route: Dict[str, object]) -> List[Tuple[str, Dict, str]]:
    ordered = sorted(_ordered_scenes(data), key=lambda scene: _scene_priority(scene, prefer_impact=True), reverse=True)
    labels = ["信息抛出", "结构示意", "关键变形", "节奏推进", "总结落点", "尾声回钩"]
    notes = [
        "先让读者知道这条信息图到底在说什么。",
        "这一张负责把复杂结构变得一眼能看懂。",
        "关键变化往往就藏在这里。",
        "动效不是乱动，而是在推理解节奏。",
        "最后要把结论稳稳落下来。",
        "收尾还得留个回钩，不然信息记不住。",
    ]
    return [(label, scene, note) for label, note, scene in zip(labels, notes, ordered[:6])]


def _music_layer_paragraph(data: Dict, alignment: Dict[str, object]) -> str:
    groups = _narrative_groups(data)
    key_moments = groups["key_moments"]

    voiceover_scenes = [s for s in key_moments if _report_voiceover(s)]
    if voiceover_scenes:
        refs = _scene_refs(voiceover_scenes[:4], 4)
        sample_text = " / ".join(_report_voiceover(s)[:15] for s in voiceover_scenes[:2] if _report_voiceover(s))
        text = (
            f"把它当 MV 看，音乐层做的不是补充叙事事实，而是把核心主题从情节道具变成整支视频的情感隐喻。{refs} 这些段落的语言内容（{sample_text}），"
            "反复强化核心主题，于是画面里的具体情节，不再只是一个单纯的故事，而变成更深层主题的载体。"
        )
    else:
        visual_fallback = _music_visual_fallback_details(key_moments or _ordered_scenes(data))
        text = "把它当 MV 看，音乐层做的不是补充叙事事实，而是通过旋律和节奏营造整体情绪氛围。"
        if visual_fallback:
            text += f" 即使拿不到可靠歌词，也能从画面本身看出它在往哪种情绪上推：{visual_fallback}。"
        text += " 这些视觉重复会把具体情节抬升到情感和主题层面。"

    if alignment["level"] == "偏低":
        text += " 但音乐层的弱点也很明确：它更擅长托住主题，不总是贴着叙事节奏走，所以到了关键叙事节点，音乐提供的更多是气氛和情绪，而不是同等强度的信息收束。"
    else:
        text += " 这一层和叙事层的节奏大体同拍，所以主题表达和情节推进能相互放大。"
    return text


def _first_scene_with_image(scenes: Sequence[Dict]) -> Dict | None:
    for scene in scenes:
        if _scene_screenshot(scene):
            return scene
    return scenes[0] if scenes else None


def _narrative_figure_specs(data: Dict) -> List[Tuple[str, Dict, str]]:
    groups = _narrative_groups(data)
    specs: List[Tuple[str, Dict, str]] = []
    candidates = [
        ("图 1 开场定调", _first_scene_with_image(groups["setup"]), "这张图负责把人物、空间和最初的情绪气压先立起来，让观众第一眼就知道这条片子从什么状态开始。"),
        ("图 2 中段推进", _first_scene_with_image(groups["investigation"]), "这张图代表中段真正开始往前走的方式：不管是动作、关系还是情绪，都会从这里明显发生变化。"),
        ("图 3 意象高点", _first_scene_with_image(groups["stage"]), "这张图不是普通过场，而是把歌曲主题、表演能量和视觉意象拧成一股力。"),
        ("图 4 转折收束", _first_scene_with_image(groups["deduction"]), "这张图对应叙事真正抬高或落下来的时刻，让前面的铺垫开始有明确落点。"),
        ("图 5 尾声定音", _first_scene_with_image(groups["resolution"]), "这张图负责把最后留下的情绪和主题钉住，让整条叙事线真正关上门。"),
    ]
    for title, scene, note in candidates:
        if scene:
            specs.append((title, scene, note))
    return specs[:4]


def _generic_figure_specs(data: Dict) -> List[Tuple[str, Dict, str]]:
    ordered = sorted(
        [scene for scene in _ordered_scenes(data) if _scene_screenshot(scene)],
        key=lambda scene: float(scene.get("weighted_score") or 0.0),
        reverse=True,
    )
    specs: List[Tuple[str, Dict, str]] = []
    for index, scene in enumerate(ordered[:3], start=1):
        specs.append(
            (
                f"图 {index} 代表镜头",
                scene,
                f"这张图对应 { _safe_text(scene.get('content_analysis', {}).get('visual_function')) or '关键视觉任务'}，它能代表这条内容最典型的一段视听表达。",
            )
        )
    return specs


def _build_visual_figure_section(data: Dict, route: Dict[str, object], report_dir: Path | None) -> List[str]:
    if route["framework"] == "narrative_performance":
        return []
    specs = _generic_figure_specs(data)
    if not specs or report_dir is None:
        return []

    lines = ["## 代表镜头图解", ""]
    for title, scene, note in specs:
        screenshot = _scene_screenshot(scene)
        rel_path = _markdown_media_path(screenshot, report_dir)
        if not rel_path:
            continue
        scene_num = int(scene.get("scene_number", 0))
        lines.extend(
            [
                f"### {title} · Scene {scene_num:03d}",
                "",
                f"![Scene {scene_num:03d}](<{rel_path}>)",
                "",
                f"- 图注：{_scene_desc(scene)}",
                f"- 为什么看这张：{note}",
                "",
            ]
        )
    return lines


def _build_inline_figure_blocks(
    specs: Sequence[Tuple[str, Dict | None, str]],
    report_dir: Path | None,
) -> List[str]:
    if report_dir is None:
        return []

    lines: List[str] = []
    seen_numbers = set()
    has_heading = False
    for title, scene, note in specs:
        if scene is None:
            continue
        scene_num = int(scene.get("scene_number", 0))
        if scene_num in seen_numbers:
            continue
        screenshot = _scene_screenshot(scene)
        rel_path = _markdown_media_path(screenshot, report_dir)
        if not rel_path:
            continue
        if not has_heading:
            lines.extend(["#### 对应镜头图解", ""])
            has_heading = True
        lines.extend(
            [
                f"##### Scene {scene_num:03d} · {title}",
                "",
                f"![Scene {scene_num:03d}](<{rel_path}>)",
                "",
                f"- 图注：{_scene_desc(scene)}",
                f"- 为什么放这里：{note}",
                "",
            ]
        )
        seen_numbers.add(scene_num)
    return lines


def _combined_expression_summary(data: Dict, route: Dict[str, object], identity: Dict[str, str]) -> str:
    if route["framework"] == "narrative_trailer":
        return "它最后让观众带走的，不是完整剧情答案，而是一个足够清楚的世界前提、一种越来越强的危险感，以及一个很难忘掉的片名记忆点。"
    if route["framework"] == "narrative_performance" and route["dual_layer"].get("secondary") == "音乐表达层":
        return "它最后让观众看到的，不只是几个分散的剧情点，而是歌曲主题如何被人物、舞台和意象一起推成一个更大的情绪命题。"
    if route["framework"] == "narrative_performance":
        return "它最后让观众接收到的，是一个由人物关系、空间压迫和关键证据共同撑起来的故事效果，而不是散开的情绪片段。"
    return f"两条轨道最终让观众接收到的是围绕“{identity['core_intent']}”展开的一体化感受。"


def _main_summary(data: Dict, route: Dict[str, object]) -> str:
    if route["framework"] == "narrative_trailer":
        return _trailer_story_summary(data)
    if route["framework"] == "technical_explainer":
        return _technical_explainer_story_summary(data)
    if route["framework"] == "event_brand_ad":
        return _event_brand_story_summary(data)
    if route["framework"] == "journey_brand_film":
        return _journey_brand_story_summary(data)
    if route["framework"] == "narrative_performance":
        return _narrative_story_summary(data)
    if route["framework"] == "commentary_mix":
        return "它主要在讲观点。不是单纯复述素材，而是先把误区或论点摆出来，再用画面和细节一条条去对照、去举证，最后把判断收回到一个更清楚的结论上。"
    if route["framework"] == "mix_music":
        return "它主要在把素材剪成越来越上头的节奏体验。不是先讲故事，而是先用鼓点和切换把人卷进去，再让高光和情绪一波波往上顶。"
    if route["framework"] == "concept_mv":
        return "它主要在用意象和情绪把人慢慢包进去。你记住的不会是某个剧情点，而是颜色、节奏、人物和氛围一起留下来的那股感觉。"
    family = _framework_family(route)
    if family == "language_led":
        return _language_led_summary(data, route)
    if family == "atmospheric":
        return _atmospheric_summary(data, route)
    if family == "meme":
        return _meme_summary(data, route)
    if family == "graphic":
        return _graphic_summary(data, route)
    if route.get("content_profile", {}).get("key") == "technical_explainer":
        return "这条视频主要在把一件复杂的事情讲清楚：它用语言负责说明概念、流程和因果，再让画面去做例子、证据或演示。"
    return "这条视频更看整体表达有没有成立：它要么在讲清一件事，要么在制造一种感受，要么在把一个内容卖出去。"


def _highlight_specs_for_route(data: Dict, route: Dict[str, object]) -> List[Tuple[str, Dict, str]]:
    if route["framework"] == "narrative_trailer":
        specs = _trailer_highlight_specs(data)
    elif route["framework"] == "technical_explainer":
        specs = _technical_explainer_highlight_specs(data)
    elif route["framework"] == "event_brand_ad":
        specs = _event_brand_highlight_specs(data)
    elif route["framework"] == "journey_brand_film":
        specs = _journey_brand_highlight_specs(data)
    elif route["framework"] == "narrative_performance":
        specs = _narrative_figure_specs(data)[:3]
    else:
        family = _framework_family(route)
        if family == "language_led":
            specs = _language_led_highlight_specs(data, route)
        elif family == "atmospheric":
            specs = _atmospheric_highlight_specs(data, route)
        elif family == "meme":
            specs = _meme_highlight_specs(data, route)
        elif family == "graphic":
            specs = _graphic_highlight_specs(data, route)
        else:
            specs = _generic_figure_specs(data)

    ordered = sorted(
        [scene for scene in _ordered_scenes(data) if _scene_screenshot(scene)],
        key=lambda scene: _scene_priority(scene, prefer_impact=True),
        reverse=True,
    )
    seen = set()
    deduped: List[Tuple[str, Dict, str]] = []
    for title, scene, note in specs:
        candidate = scene
        if candidate is not None and int(candidate.get("scene_number", 0)) in seen:
            candidate = None
        if candidate is None:
            for fallback in ordered:
                scene_number = int(fallback.get("scene_number", 0))
                if scene_number not in seen:
                    candidate = fallback
                    break
        if candidate is None:
            continue
        seen.add(int(candidate.get("scene_number", 0)))
        deduped.append((title, candidate, note))
    return deduped


def _judgement_heading(route: Dict[str, object]) -> str:
    if route["framework"] == "narrative_trailer":
        return "作为预告片，它到底好不好"
    if route["framework"] == "technical_explainer":
        return "作为技术讲解，它到底好不好"
    if route["framework"] == "event_brand_ad":
        return "作为活动广告，它到底好不好"
    if route["framework"] == "journey_brand_film":
        return "作为旅程型品牌短片，它到底好不好"
    if route.get("content_profile", {}).get("key") == "technical_explainer":
        return "作为讲解内容，它到底好不好"
    return "作为这一类内容，它到底好不好"


def _route_uses_inline_figures(route: Dict[str, object]) -> bool:
    return route["framework"] in {"narrative_trailer", "narrative_performance"}


def _highlight_summary_lines(specs: Sequence[Tuple[str, Dict, str]]) -> List[str]:
    lines: List[str] = []
    for title, scene, note in specs:
        if scene is None:
            continue
        scene_num = int(scene.get("scene_number", 0))
        lines.append(f"- Scene {scene_num:03d} · {title}：{note}")
    return lines or ["- 这一类内容最值得看的，通常是最能代表整体表达的几段镜头。"]


def _route_visual_summary(data: Dict) -> str:
    scenes = data.get("scenes", [])
    return (
        f"画面这一路，最常干的事是 {_top_text([_safe_text(scene.get('content_analysis', {}).get('visual_function')) for scene in scenes])}。"
        f"镜头大多落在 {_top_text([_safe_text(scene.get('storyboard', {}).get('shot_size')) for scene in scenes])}，"
        f"光线常见的是 {_top_text([_safe_text(scene.get('storyboard', {}).get('lighting')) for scene in scenes])}，"
        f"机位动作多是 {_top_text([_safe_text(scene.get('storyboard', {}).get('camera_movement')) for scene in scenes])}。"
    )


def _route_language_summary(data: Dict) -> str:
    scenes = data.get("scenes", [])
    functions = _top_text([_safe_text(scene.get("content_analysis", {}).get("language_function")) for scene in scenes])
    if not any(_report_voiceover(scene) for scene in scenes):
        return "这条片子没怎么靠对白硬撑，信息和情绪主要还是让画面自己往前走。"
    return f"台词和字幕这一路，主要在干 {functions} 这件事。比较能代表味道的几句是：{_scene_list_text(_pick_scenes(data, require_voiceover=True), use_voiceover=True)}。"


def _alignment_summary(data: Dict) -> Dict[str, object]:
    scenes = data.get("scenes", [])
    visual_sorted = sorted(scenes, key=lambda scene: (float(scene.get("scores", {}).get("impact") or 0.0), float(scene.get("weighted_score") or 0.0)), reverse=True)
    language_sorted = sorted(scenes, key=lambda scene: len(_voiceover(scene).replace(" ", "")), reverse=True)
    visual_peaks = {int(scene.get("scene_number", 0)) for scene in visual_sorted[: max(1, len(scenes) // 8 or 1)]}
    language_peaks = {int(scene.get("scene_number", 0)) for scene in language_sorted[: max(1, len(scenes) // 8 or 1)] if _voiceover(scene)}
    overlap_ratio = len(visual_peaks & language_peaks) / max(len(language_peaks), 1)
    if overlap_ratio >= 0.55:
        level, summary = "高", "画面最猛的时候，声音和台词大多也能跟上，所以高点基本能一起砸下来。"
    elif overlap_ratio >= 0.25:
        level, summary = "中", "两条线大体是顺的，关键时刻能接上一些，但最狠的那几下还没有完全拧成一股。"
    else:
        level, summary = "偏低", "画面已经冲上去了，声音和台词有时还在后面追，所以会让人觉得劲没有一起落下来。"
    return {"level": level, "summary": summary, "visual_peaks": sorted(visual_peaks), "language_peaks": sorted(language_peaks)}


def _top_scene_refs_by_metric(scenes: Sequence[Dict], metric_key: str, limit: int = 3) -> str:
    ranked = sorted(
        scenes,
        key=lambda scene: float(scene.get("analysis_dimensions", {}).get(metric_key) or 0.0),
        reverse=True,
    )
    return _scene_refs(ranked, limit)


def _top_scenes_by_metric(scenes: Sequence[Dict], metric_key: str, limit: int = 3) -> List[Dict]:
    return sorted(
        scenes,
        key=lambda scene: float(scene.get("analysis_dimensions", {}).get(metric_key) or 0.0),
        reverse=True,
    )[:limit]


def _voiceover_text_is_unreliable(text: str) -> bool:
    cleaned = _safe_text(text)
    if not cleaned:
        return True

    normalized = re.sub(r"\s+", " ", cleaned).strip()
    if re.search(r"(.)\1{10,}", normalized):
        return True
    if re.search(r"\b(\w+)(?:\s+\1){2,}\b", normalized, re.IGNORECASE):
        return True

    tokens = re.findall(r"[A-Za-z0-9\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af']+", normalized.lower())
    if len(tokens) >= 6 and len(set(tokens)) <= max(3, len(tokens) // 3):
        return True

    meaningful_chars = sum(
        1
        for ch in normalized
        if ch.isalnum()
        or "\u4e00" <= ch <= "\u9fff"
        or "\u3040" <= ch <= "\u30ff"
        or "\uac00" <= ch <= "\ud7af"
    )
    return meaningful_chars / max(len(normalized), 1) < 0.35


def _report_voiceover(scene: Dict) -> str:
    text = _voiceover(scene)
    return "" if _voiceover_text_is_unreliable(text) else text


def _music_visual_fallback_details(scenes: Sequence[Dict]) -> str:
    ranked = sorted(
        [scene for scene in scenes if _scene_desc(scene)],
        key=lambda scene: _scene_priority(scene, prefer_impact=True),
        reverse=True,
    )
    if not ranked:
        return ""

    refs = _scene_refs(ranked[:3], 3)
    phrase = _best_scene_phrase(ranked, limit=2, max_length=22, prefer_impact=True)
    styles = _top_text([_safe_text(scene.get("storyboard", {}).get("visual_style")) for scene in ranked], limit=2)
    lighting = _top_text([_safe_text(scene.get("storyboard", {}).get("lighting")) for scene in ranked], limit=2)
    movement = _top_text([_safe_text(scene.get("storyboard", {}).get("camera_movement")) for scene in ranked], limit=2)

    details: List[str] = []
    if phrase:
        details.append(f"{refs} 这些段落里最抓人的画面是 {phrase}")
    if styles != "未形成稳定偏好":
        details.append(f"视觉上反复落在 {styles}")
    if lighting != "未形成稳定偏好":
        details.append(f"光线多用 {lighting}")
    if movement != "未形成稳定偏好":
        details.append(f"运镜常见 {movement}")
    return "；".join(details)


def _top_terms(scenes: Sequence[Dict], field_getter, limit: int = 2) -> str:
    counter = Counter()
    for scene in scenes:
        value = _safe_text(field_getter(scene))
        if value:
            counter[value] += 1
    items = [item for item, _ in counter.most_common(limit)]
    return "、".join(items) if items else "这一挂"


__all__ = [name for name in globals() if name.startswith("_")]
