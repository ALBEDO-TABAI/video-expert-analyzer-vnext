import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import audiovisual.reporting.builder as report_builder
import audiovisual.reporting.handoff as handoff_module
import audiovisual.reporting.raw_prompt_adapter as raw_prompt_adapter
import audiovisual.reporting.template_engine as template_engine
from audiovisual.rendering.pdf import build_audiovisual_report_pdf_blocks
from classification_summary import build_classification_summary_payload
from video_type_router_runtime import build_classification_result_payload


def _stub_handoff_outputs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    body: str | None = None,
    diagram: str | None = None,
    overview: str | None = None,
    illustrate: str | None = None,
) -> None:
    """Short-circuit AudiovisualHandoffCoordinator so that body/diagram/overview/illustrate
    subtasks resolve synchronously from pre-supplied stub content.

    Without this, generate_audiovisual_report_outputs() writes a task packet
    and raises AudiovisualHandoffPending on the first call.
    """
    outputs = {
        "body": body,
        "diagram": diagram,
        "overview": overview,
        "illustrate": illustrate,
    }

    def fake_read_output(self, name: str, filename: str) -> str | None:
        value = outputs.get(name)
        if value is None:
            return None
        text = str(value)
        return text if text.strip() else None

    monkeypatch.setattr(
        handoff_module.AudiovisualHandoffCoordinator,
        "_read_output",
        fake_read_output,
    )


# These are report-generation frameworks supported by the template engine.
# They are not the 19 child-router result types from video_type_router_runtime.py.
ALL_REPORT_FRAMEWORKS = [
    "abstract_sfx",
    "cinematic_life",
    "commentary_mix",
    "concept_mv",
    "documentary_generic",
    "event_brand_ad",
    "hybrid_ambient",
    "hybrid_commentary",
    "hybrid_meme",
    "hybrid_music",
    "hybrid_narrative",
    "infographic_animation",
    "journey_brand_film",
    "lecture_performance",
    "meme",
    "mix_music",
    "narrative_mix",
    "narrative_motion_graphics",
    "narrative_performance",
    "narrative_trailer",
    "pure_motion_graphics",
    "pure_visual_mix",
    "reality_sfx",
    "silent_performance",
    "silent_reality",
    "technical_explainer",
]

ALL_CHILD_ROUTER_TYPES = [
    "concept_mv",
    "performance_mv",
    "live_session",
    "narrative_short",
    "narrative_trailer",
    "talking_head",
    "documentary_essay",
    "commentary_remix",
    "brand_film",
    "event_promo",
    "explainer",
    "infographic_motion",
    "rhythm_remix",
    "mood_montage",
    "cinematic_vlog",
    "reality_record",
    "meme_viral",
    "motion_graphics",
    "experimental",
]

RAW_PROMPT_CHILD_TYPES = [
    "concept_mv",
    "performance_mv",
    "live_session",
    "narrative_short",
    "talking_head",
    "commentary_remix",
    "documentary_essay",
    "brand_film",
    "event_promo",
    "explainer",
    "infographic_motion",
    "narrative_trailer",
    "rhythm_remix",
    "mood_montage",
    "cinematic_vlog",
    "reality_record",
    "meme_viral",
    "motion_graphics",
    "experimental",
]


def _mix_music_route() -> dict:
    return {
        "framework": "mix_music",
        "route_label": "音乐节奏向二创",
        "route_subtype": "",
        "reference": "游戏 / 影视混剪（音乐节奏向）",
        "visual_axis": "S",
        "visual_label": "二创素材",
        "audio_axis": "M",
        "audio_label": "音乐主导",
        "visual_rationale": "素材来自已有视频片段，剪辑重组明显。",
        "audio_rationale": "配乐主导情绪和节奏，不依赖解说。",
        "voiceover_ratio": 0.0,
        "dual_layer": {"enabled": False},
        "content_profile": {"key": "mix_music"},
    }


def _mix_music_payload() -> dict:
    return {
        "video_id": "mix-music-test",
        "title": "High energy anime edit",
        "video_title": "High energy anime edit",
        "audiovisual_route": _mix_music_route(),
        "scenes": [
            {
                "scene_number": 1,
                "duration_seconds": 0.8,
                "description": "角色近景切入，鼓点落下时镜头闪切。",
                "selection": "[MUST KEEP]",
                "weighted_score": 8.6,
                "scores": {
                    "aesthetic_beauty": 8.2,
                    "credibility": 5.1,
                    "impact": 8.9,
                    "memorability": 8.4,
                    "fun_interest": 7.3,
                },
                "analysis_dimensions": {
                    "emotional_effect": 8.1,
                    "information_efficiency": 4.1,
                },
                "storyboard": {
                    "visual_style": "霓虹动作",
                    "camera_movement": "快速推进",
                    "shot_size": "近景",
                    "voiceover": "",
                    "onscreen_text": "",
                },
            },
            {
                "scene_number": 2,
                "duration_seconds": 1.0,
                "description": "人物群像横移，情绪开始抬升。",
                "selection": "[USABLE]",
                "weighted_score": 7.4,
                "scores": {
                    "aesthetic_beauty": 7.8,
                    "credibility": 5.4,
                    "impact": 7.5,
                    "memorability": 7.2,
                    "fun_interest": 6.9,
                },
                "analysis_dimensions": {
                    "emotional_effect": 7.6,
                    "information_efficiency": 3.8,
                },
                "storyboard": {
                    "visual_style": "霓虹动作",
                    "camera_movement": "横移",
                    "shot_size": "中景",
                    "voiceover": "",
                    "onscreen_text": "",
                },
            },
            {
                "scene_number": 3,
                "duration_seconds": 2.6,
                "description": "长镜头停在角色回头的一瞬，情绪短暂停顿。",
                "selection": "[USABLE]",
                "weighted_score": 6.8,
                "scores": {
                    "aesthetic_beauty": 7.1,
                    "credibility": 5.2,
                    "impact": 5.8,
                    "memorability": 6.4,
                    "fun_interest": 5.9,
                },
                "analysis_dimensions": {
                    "emotional_effect": 5.2,
                    "information_efficiency": 3.2,
                },
                "storyboard": {
                    "visual_style": "暗色抒情",
                    "camera_movement": "固定",
                    "shot_size": "中近景",
                    "voiceover": "",
                    "onscreen_text": "",
                },
            },
            {
                "scene_number": 4,
                "duration_seconds": 0.7,
                "description": "光效爆开，动作和鼓点同时冲顶。",
                "selection": "[MUST KEEP]",
                "weighted_score": 8.9,
                "scores": {
                    "aesthetic_beauty": 8.4,
                    "credibility": 5.0,
                    "impact": 9.3,
                    "memorability": 8.8,
                    "fun_interest": 7.5,
                },
                "analysis_dimensions": {
                    "emotional_effect": 8.4,
                    "information_efficiency": 4.2,
                },
                "storyboard": {
                    "visual_style": "霓虹动作",
                    "camera_movement": "旋转推进",
                    "shot_size": "特写",
                    "voiceover": "",
                    "onscreen_text": "",
                },
            },
        ],
    }


def _with_classification(payload: dict, type_key: str, type_cn: str) -> dict:
    enriched = dict(payload)
    route = dict(enriched["audiovisual_route"])
    route["route_subtype"] = type_cn
    route["child_type"] = type_key
    route["child_type_cn"] = type_cn
    enriched["audiovisual_route"] = route
    enriched["classification_result"] = {
        "classification": {
            "type": type_key,
            "type_cn": type_cn,
            "confidence": "high",
        },
        "applied_route": route,
    }
    return enriched


def _with_child_route(payload: dict, type_key: str, type_cn: str) -> dict:
    enriched = dict(payload)
    route = dict(enriched["audiovisual_route"])
    route["route_subtype"] = type_cn
    route["child_type"] = type_key
    route["child_type_cn"] = type_cn
    enriched["audiovisual_route"] = route
    enriched.pop("classification_result", None)
    return enriched


def _with_route_subtype_only(payload: dict, type_cn: str) -> dict:
    enriched = dict(payload)
    route = dict(enriched["audiovisual_route"])
    route["route_subtype"] = type_cn
    route.pop("child_type", None)
    route.pop("child_type_cn", None)
    enriched["audiovisual_route"] = route
    enriched.pop("classification_result", None)
    return enriched


def _concept_mv_payload() -> dict:
    return {
        "video_id": "concept-mv-test",
        "title": "Dreamy concept video",
        "video_title": "Dreamy concept video",
        "audiovisual_route": {
            "framework": "concept_mv",
            "route_label": "概念 MV / 情绪渲染型",
            "route_subtype": "",
            "reference": "动态设计视频 / 概念 MV",
            "visual_axis": "D",
            "visual_label": "设计 / 动态图形",
            "audio_axis": "M",
            "audio_label": "音乐主导",
            "visual_rationale": "意象化视觉和风格统一度明显高于叙事推进。",
            "audio_rationale": "音乐承担主要情绪结构。",
            "voiceover_ratio": 0.0,
            "dual_layer": {"enabled": False},
            "content_profile": {"key": "concept_mv"},
        },
        "scenes": [
            {
                "scene_number": 1,
                "duration_seconds": 1.4,
                "description": "光从窗边切进来，人物站在镜子前抬手。",
                "selection": "[USABLE]",
                "weighted_score": 7.6,
                "scores": {
                    "aesthetic_beauty": 8.4,
                    "credibility": 5.0,
                    "impact": 7.1,
                    "memorability": 7.8,
                    "fun_interest": 6.1,
                },
                "analysis_dimensions": {
                    "emotional_effect": 7.2,
                    "information_efficiency": 3.0,
                },
                "storyboard": {
                    "visual_style": "蓝金梦境",
                    "camera_movement": "慢速平移",
                    "shot_size": "中景",
                    "voiceover": "",
                    "onscreen_text": "",
                },
            },
            {
                "scene_number": 2,
                "duration_seconds": 1.0,
                "description": "水面反光压过画面，眼神特写在鼓点前停住。",
                "selection": "[MUST KEEP]",
                "weighted_score": 8.2,
                "scores": {
                    "aesthetic_beauty": 8.8,
                    "credibility": 4.8,
                    "impact": 8.2,
                    "memorability": 8.3,
                    "fun_interest": 6.4,
                },
                "analysis_dimensions": {
                    "emotional_effect": 8.1,
                    "information_efficiency": 3.1,
                },
                "storyboard": {
                    "visual_style": "蓝金梦境",
                    "camera_movement": "推近",
                    "shot_size": "特写",
                    "voiceover": "",
                    "onscreen_text": "",
                },
            },
            {
                "scene_number": 3,
                "duration_seconds": 1.2,
                "description": "门被推开，光和影一起扫过长廊。",
                "selection": "[USABLE]",
                "weighted_score": 7.9,
                "scores": {
                    "aesthetic_beauty": 8.1,
                    "credibility": 5.1,
                    "impact": 7.7,
                    "memorability": 7.9,
                    "fun_interest": 6.0,
                },
                "analysis_dimensions": {
                    "emotional_effect": 7.8,
                    "information_efficiency": 3.2,
                },
                "storyboard": {
                    "visual_style": "蓝金梦境",
                    "camera_movement": "滑轨",
                    "shot_size": "全景",
                    "voiceover": "",
                    "onscreen_text": "",
                },
            },
            {
                "scene_number": 4,
                "duration_seconds": 1.8,
                "description": "火光在水面上颤动，人物回头停在副歌高点。",
                "selection": "[MUST KEEP]",
                "weighted_score": 8.7,
                "scores": {
                    "aesthetic_beauty": 8.9,
                    "credibility": 4.7,
                    "impact": 8.7,
                    "memorability": 8.8,
                    "fun_interest": 6.8,
                },
                "analysis_dimensions": {
                    "emotional_effect": 8.5,
                    "information_efficiency": 3.3,
                },
                "storyboard": {
                    "visual_style": "蓝金梦境",
                    "camera_movement": "慢速环绕",
                    "shot_size": "中近景",
                    "voiceover": "",
                    "onscreen_text": "",
                },
            },
        ],
    }


def _narrative_performance_payload() -> dict:
    return {
        "video_id": "narrative-performance-test",
        "title": "Narrative performance video",
        "video_title": "Narrative performance video",
        "audiovisual_route": {
            "framework": "narrative_performance",
            "route_label": "叙事型表演内容",
            "route_subtype": "剧情化 MV",
            "reference": "叙事短片 / 剧情广告 / 剧情化 MV",
            "visual_axis": "P",
            "visual_label": "原创演绎拍摄",
            "audio_axis": "LM",
            "audio_label": "语言 + 音乐并重",
            "visual_rationale": "人物调度和叙事段落清楚，表演承担推进。",
            "audio_rationale": "音乐和歌词共同托住叙事情绪。",
            "voiceover_ratio": 0.4,
            "dual_layer": {
                "enabled": True,
                "primary": "叙事层",
                "secondary": "音乐表达层",
                "reason": "它既在讲故事，也明显依托音乐和歌词完成情绪表达。",
            },
            "content_profile": {"key": "music_video"},
        },
        "scenes": [
            {
                "scene_number": 1,
                "duration_seconds": 2.2,
                "description": "角色推门走进空舞台，灯光刚刚亮起。",
                "weighted_score": 7.8,
                "story_role": "开场建立",
                "story_function": "人物关系建立",
                "scores": {
                    "aesthetic_beauty": 8.0,
                    "credibility": 6.0,
                    "impact": 7.2,
                    "memorability": 7.1,
                    "fun_interest": 6.5,
                },
                "analysis_dimensions": {
                    "emotional_effect": 7.2,
                    "information_efficiency": 5.2,
                    "narrative_function": 7.6,
                },
                "storyboard": {
                    "voiceover": "we begin in silence",
                    "onscreen_text": "",
                    "shot_size": "全景",
                    "visual_style": "舞台戏剧",
                    "camera_movement": "稳定推进",
                },
            },
            {
                "scene_number": 2,
                "duration_seconds": 1.7,
                "description": "两人错位对望，舞台中央开始旋转。",
                "weighted_score": 8.1,
                "story_role": "中段推进",
                "story_function": "关系拉扯",
                "scores": {
                    "aesthetic_beauty": 8.2,
                    "credibility": 6.1,
                    "impact": 7.9,
                    "memorability": 7.8,
                    "fun_interest": 6.7,
                },
                "analysis_dimensions": {
                    "emotional_effect": 7.9,
                    "information_efficiency": 5.4,
                    "narrative_function": 7.8,
                },
                "storyboard": {
                    "voiceover": "can you hear me now",
                    "onscreen_text": "",
                    "shot_size": "中景",
                    "visual_style": "舞台戏剧",
                    "camera_movement": "环绕",
                },
            },
            {
                "scene_number": 3,
                "duration_seconds": 1.3,
                "description": "红幕突然落下，群舞和副歌一起冲顶。",
                "weighted_score": 8.9,
                "story_role": "高潮收束",
                "story_function": "主题爆发",
                "scores": {
                    "aesthetic_beauty": 8.7,
                    "credibility": 5.9,
                    "impact": 9.0,
                    "memorability": 8.6,
                    "fun_interest": 7.2,
                },
                "analysis_dimensions": {
                    "emotional_effect": 8.6,
                    "information_efficiency": 5.7,
                    "narrative_function": 8.5,
                },
                "storyboard": {
                    "voiceover": "all the lights are calling",
                    "onscreen_text": "",
                    "shot_size": "中近景",
                    "visual_style": "舞台戏剧",
                    "camera_movement": "快速推近",
                },
            },
            {
                "scene_number": 4,
                "duration_seconds": 1.9,
                "description": "角色回头停住，余音和眼神一起收束。",
                "weighted_score": 8.4,
                "story_role": "高潮收束",
                "story_function": "情绪落点",
                "scores": {
                    "aesthetic_beauty": 8.4,
                    "credibility": 6.2,
                    "impact": 8.1,
                    "memorability": 8.0,
                    "fun_interest": 6.9,
                },
                "analysis_dimensions": {
                    "emotional_effect": 8.0,
                    "information_efficiency": 5.3,
                    "narrative_function": 8.1,
                },
                "storyboard": {
                    "voiceover": "stay with me tonight",
                    "onscreen_text": "",
                    "shot_size": "特写",
                    "visual_style": "舞台戏剧",
                    "camera_movement": "静止",
                },
            },
        ],
    }


def _cinematic_life_payload() -> dict:
    return {
        "video_id": "cinematic-life-test",
        "title": "Cinematic daily vlog",
        "video_title": "Cinematic daily vlog",
        "audiovisual_route": {
            "framework": "cinematic_life",
            "route_label": "生活电影化剪辑",
            "route_subtype": "",
            "reference": "生活电影化剪辑 / 氛围 Vlog",
            "visual_axis": "R",
            "visual_label": "原创现实拍摄",
            "audio_axis": "M",
            "audio_label": "音乐主导",
            "visual_rationale": "画面以日常动作和氛围镜头为主。",
            "audio_rationale": "音乐负责包裹情绪，不承担讲解。",
            "voiceover_ratio": 0.0,
            "dual_layer": {"enabled": False},
            "content_profile": {"key": "cinematic_life"},
        },
        "scenes": [
            {
                "scene_number": 1,
                "duration_seconds": 1.6,
                "description": "逆光下骑车穿过街口，像生活记录的开场。",
                "selection": "[USABLE]",
                "weighted_score": 7.8,
                "scores": {
                    "aesthetic_beauty": 8.3,
                    "credibility": 6.9,
                    "impact": 7.0,
                    "memorability": 7.4,
                    "fun_interest": 6.1,
                },
                "analysis_dimensions": {
                    "emotional_effect": 7.3,
                    "information_efficiency": 3.2,
                },
                "storyboard": {
                    "visual_style": "暖色生活电影感",
                    "camera_movement": "跟拍",
                    "shot_size": "中景",
                    "voiceover": "",
                    "onscreen_text": "",
                },
            },
            {
                "scene_number": 2,
                "duration_seconds": 1.4,
                "description": "暖色厨房特写，蒸汽和笑声一起升起来。",
                "selection": "[MUST KEEP]",
                "weighted_score": 8.2,
                "scores": {
                    "aesthetic_beauty": 8.6,
                    "credibility": 6.8,
                    "impact": 7.6,
                    "memorability": 7.9,
                    "fun_interest": 6.5,
                },
                "analysis_dimensions": {
                    "emotional_effect": 7.8,
                    "information_efficiency": 3.1,
                },
                "storyboard": {
                    "visual_style": "暖色生活电影感",
                    "camera_movement": "微移",
                    "shot_size": "特写",
                    "voiceover": "",
                    "onscreen_text": "",
                },
            },
            {
                "scene_number": 3,
                "duration_seconds": 1.8,
                "description": "日常生活的桌边交谈被慢慢拉远，保留了真实停顿。",
                "selection": "[USABLE]",
                "weighted_score": 7.6,
                "scores": {
                    "aesthetic_beauty": 8.1,
                    "credibility": 7.2,
                    "impact": 6.8,
                    "memorability": 7.1,
                    "fun_interest": 6.0,
                },
                "analysis_dimensions": {
                    "emotional_effect": 7.0,
                    "information_efficiency": 3.0,
                },
                "storyboard": {
                    "visual_style": "暖色生活电影感",
                    "camera_movement": "缓慢拉远",
                    "shot_size": "中近景",
                    "voiceover": "",
                    "onscreen_text": "",
                },
            },
            {
                "scene_number": 4,
                "duration_seconds": 1.5,
                "description": "夜色剪影里抬头看灯，光影和现场感一起收住。",
                "selection": "[USABLE]",
                "weighted_score": 8.0,
                "scores": {
                    "aesthetic_beauty": 8.5,
                    "credibility": 6.7,
                    "impact": 7.8,
                    "memorability": 8.0,
                    "fun_interest": 6.2,
                },
                "analysis_dimensions": {
                    "emotional_effect": 7.9,
                    "information_efficiency": 3.1,
                },
                "storyboard": {
                    "visual_style": "暖色生活电影感",
                    "camera_movement": "轻微上摇",
                    "shot_size": "中景",
                    "voiceover": "",
                    "onscreen_text": "",
                },
            },
        ],
    }


def _commentary_mix_payload() -> dict:
    return {
        "video_id": "commentary-mix-test",
        "title": "Commentary remix",
        "video_title": "Commentary remix",
        "audiovisual_route": {
            "framework": "commentary_mix",
            "route_label": "评论向素材二创",
            "route_subtype": "",
            "reference": "影视 / 游戏解说、评论向混剪",
            "visual_axis": "S",
            "visual_label": "二创素材",
            "audio_axis": "L",
            "audio_label": "语言主导",
            "visual_rationale": "画面主要承担举证和例子功能。",
            "audio_rationale": "语言负责主论点推进。",
            "voiceover_ratio": 0.55,
            "dual_layer": {"enabled": False},
            "content_profile": {"key": "commentary_mix"},
        },
        "scenes": [
            {
                "scene_number": 1,
                "duration_seconds": 1.2,
                "description": "素材切到关键动作，评论开始抛出问题。",
                "selection": "[USABLE]",
                "weighted_score": 7.5,
                "scores": {
                    "aesthetic_beauty": 7.2,
                    "credibility": 6.2,
                    "impact": 7.1,
                    "memorability": 6.8,
                    "fun_interest": 6.0,
                },
                "analysis_dimensions": {
                    "emotional_effect": 6.8,
                    "information_efficiency": 7.1,
                },
                "storyboard": {
                    "visual_style": "影视素材拼接",
                    "camera_movement": "原片镜头",
                    "shot_size": "中景",
                    "voiceover": "问题不是动作本身，而是因为信息被故意藏起来了",
                    "onscreen_text": "",
                },
            },
            {
                "scene_number": 2,
                "duration_seconds": 1.1,
                "description": "镜头回到证据段落，人物反应被放大。",
                "selection": "[MUST KEEP]",
                "weighted_score": 7.9,
                "scores": {
                    "aesthetic_beauty": 7.4,
                    "credibility": 6.4,
                    "impact": 7.6,
                    "memorability": 7.2,
                    "fun_interest": 6.1,
                },
                "analysis_dimensions": {
                    "emotional_effect": 7.0,
                    "information_efficiency": 7.4,
                },
                "storyboard": {
                    "visual_style": "影视素材拼接",
                    "camera_movement": "原片镜头",
                    "shot_size": "近景",
                    "voiceover": "所以这一段画面才是真正的证据，不是装饰性插入",
                    "onscreen_text": "",
                },
            },
            {
                "scene_number": 3,
                "duration_seconds": 1.4,
                "description": "素材切回对照镜头，结论开始收束。",
                "selection": "[USABLE]",
                "weighted_score": 7.7,
                "scores": {
                    "aesthetic_beauty": 7.3,
                    "credibility": 6.5,
                    "impact": 7.0,
                    "memorability": 6.9,
                    "fun_interest": 6.0,
                },
                "analysis_dimensions": {
                    "emotional_effect": 6.9,
                    "information_efficiency": 7.0,
                },
                "storyboard": {
                    "visual_style": "影视素材拼接",
                    "camera_movement": "原片镜头",
                    "shot_size": "中近景",
                    "voiceover": "但是如果只看表面镜头，就会错过作者真正想证明的问题",
                    "onscreen_text": "",
                },
            },
        ],
    }


def _stub_agent_output() -> str:
    return """## 内容速览

这条混剪围绕清晰的鼓点推进，核心不是讲故事，而是通过短切、重击和高冲击素材把观众持续焊在同一股节奏体验里。

---
## 节拍骨架与卡点组织

这条片子靠连续短切和强冲击画面把人直接拉进节奏里，关键卡点主要集中在 Scene 001 和 Scene 004 这种短时长高冲击段落。

<!-- FIGURE:opening -->

---
## 素材采样策略

高分镜头基本都围着霓虹动作风格在打，说明它不是随便拼，而是在挑最适合当前节拍骨架的能量片段。

<!-- FIGURE:rhythm_peak -->

---
## 视觉参数如何为节奏服务

景别、运动和光效都在给节奏抬压强，所以观众记住的不只是动作本身，而是动作被音乐重新焊起来后的冲击。

<!-- FIGURE:source_quality -->

---
## 声画对位与高潮工程学

它不是把高光顺着摆开，而是先压一下再往上顶，情绪有明确起伏。

---
## 批评性评注

最成立的地方，是卡点和素材冲击大体站在同一股劲上；真正要小心的，是如果中段呼吸位再弱一点，后面的高点就会更像单纯堆素材。

---
## 综合述评

- 类型定性：高压节奏型动作混剪
- 目标受众：会为强节奏画面和连续高光停下来的观众
- 核心意图：把熟悉素材重新剪成更上头的一轮冲击

<!-- PYTHON_DIRECT:alignment -->
    <!-- PYTHON_DIRECT:scoring_table -->
"""


def _meme_stub_agent_output() -> str:
    return """## 内容速览

这条梗视频最有效的地方，不是单个笑点多夸张，而是它把固定反应模板、反差时机和圈层信号拧成了一个容易被模仿的表达骨架。

---
## 模板结构解剖

真正固定下来的不是某一句台词，而是“先铺一个正常预期，再突然翻过去”的反应结构，所以 Scene 001 到 Scene 003 才是这条片最像模板的骨架。

<!-- FIGURE:opening -->

---
## 传播驱动力分析

它的驱动力更偏立场和形式一起发力：观众会转，不只是因为好笑，还因为这种反应姿态很适合拿去继续套自己的情境。

<!-- FIGURE:evidence_peak -->

---
## 不协调结构与笑点机制

笑点最成立的地方，在于画面和音效同时把预期打断，所以反差不是单点，而是时机、表情和声响一起顶出来的。

---
## 互文门槛与圈层扩展

这条片门槛不算高，圈层信号更像加味料而不是硬门槛，所以既能让圈内人觉得熟，也不至于把路人完全挡在外面。

---
## 批评性评注

它最强的是模板够清楚、可复用性也够高；最需要小心的是如果后续变体只学表面声效和夸张表情，模板很快就会疲劳。

---
## 综合述评

- 类型定性：反应翻转型视频梗
- 目标受众：会为即时反差、熟悉模板和可套用表达停下来的观众
- 核心意图：让观众立刻 get 到反应姿态，并愿意顺手拿去再创作

<!-- PYTHON_DIRECT:alignment -->
<!-- PYTHON_DIRECT:scoring_table -->
"""


def _narrative_stub_agent_output() -> str:
    return """## 内容速览

这条 MV 主要由舞台、后台和表演空间组成，歌词持续围绕人物关系和情绪姿态推进，整条片的重点不是讲一个复杂事件，而是把表演和叙事拧成一条线。

---
## 视觉语法统计

大量中近景和稳定推进镜头让人物一直处在被观看的位置，灯光和色调则持续把空间压在“表演中的叙事世界”里，而不是现实日常里。

<!-- FIGURE:opening -->

---
## 空间系统拆解

前半段空间负责建立人物关系，中段空间开始把张力拧紧，后段则把舞台真正抬成情绪爆点，所以空间不是换景，而是在推主题。

---
## 叙事弧线识别

主体状态从被压住、被观看，慢慢走到能把情绪主动抬出来，这条弧线在 Scene 001 到 Scene 004 之间是完整的。

<!-- FIGURE:narrative_peak -->

---
## 双线交织分析

歌词不是在补剧情说明，而是在和舞台表演互相抬高，画面越往后越像把语言里的情绪命题演成了可见的动作。

---
## 符号系统梳理

最有效的符号不是零散道具，而是舞台、视线和光线反复形成的观看关系，这些东西一起把人物放进了同一个叙事姿态里。

---
## 标题与收尾分析

标题和收尾都没有把观众往外推出去，而是继续把人物关系压在最后几镜里，所以结尾不是补说明，而是在给整条弧线落最后一个姿态。

---
## 批评性评注

这条 MV 的长处，是表演和叙事没有各走各的；它真正要小心的，是如果中段空间变化再弱一点，整条线就会更像舞台片段堆叠而不是完整推进。

---
## 综合述评

- 类型定性：舞台叙事型剧情 MV
- 目标受众：会同时盯人物关系和副歌爆发点的音乐视频观众
- 核心意图：把一段舞台关系推成更大的情绪命题

<!-- PYTHON_DIRECT:alignment -->
<!-- PYTHON_DIRECT:scoring_table -->
"""


def _concept_stub_agent_output() -> str:
    return """## 先看结论

这条片子不是在交代事件，而是在反复用光、水、门这些意象把人往梦境里带。

<!-- FIGURE:opening -->

---
## 内容速览

它先用低信息量的意象建立气氛，再在副歌附近把重复符号推成更强的情绪包围。

---
## 意象一致性

主意象稳定，风格没有乱跳，视觉符号一直在往同一个情绪方向压。

<!-- FIGURE:motif_peak -->

---
## 情绪曲线与音乐结构

副歌前后的 Scene 002 和 Scene 004 是最明显的情绪抬升点。

---
## 观看建议与失效风险

先看 Scene 002 和 Scene 004，如果这两段没有把你带进去，整条片子的概念就立不住。

---
## 综合述评

- 类型定性：梦境意象型概念 MV
- 目标受众：会为重复意象和情绪流动停下来的观众
- 核心意图：把音乐的情绪层慢慢转成可记住的画面记忆

<!-- PYTHON_DIRECT:alignment -->
<!-- PYTHON_DIRECT:scoring_table -->
"""


def _cinematic_stub_agent_output() -> str:
    return """## 先看结论

这条片子最成立的地方，是它把生活片段都压在同一种暖色和呼吸感里，没有为了好看把日常掏空。

<!-- FIGURE:opening -->

---
## 内容速览

前面先让人进入日常节奏，中段用光影和停顿抬高质感，后面再把生活感轻轻收住。

---
## 氛围一致性

光影、色调和运动方式都在同一个方向上，没有忽冷忽热。

<!-- FIGURE:atmosphere_peak -->

---
## 生活真实感

它没有把生活磨得太假，现场停顿和人物状态还在。

---
## 观看建议与失效风险

先看 Scene 002 和 Scene 003，如果这两段还能同时保住质感和日常感，这条片就成立了。

---
## 综合述评

- 类型定性：暖色日常电影化短片
- 目标受众：会为生活细节和电影感停下来的观众
- 核心意图：把普通日常包成一段可以停留的情绪体验

<!-- PYTHON_DIRECT:alignment -->
<!-- PYTHON_DIRECT:scoring_table -->
"""


def _commentary_stub_agent_output() -> str:
    return """## 内容速览

这条视频围绕一条明确判断展开，画面主要由原片片段、对照镜头和字幕信息组成，旁白一直在解释这些素材为什么能证明创作者的结论。

---
## 论证架构拆解

这条片子不是把观点散着丢，而是在 Scene 001 抛出问题、Scene 002 补强证据、Scene 003 收束判断，论证链条是连续的。

<!-- FIGURE:opening -->

---
## 旁白—画面权力关系

多数时候仍是旁白在决定论证方向，但画面不是被动插图，像 Scene 002 这样的对照镜头已经在独立承担证据任务。

---
## 解说者主体性

创作者不是假装中立地念说明书，而是在持续用自己的判断框架带观众看素材，这种主体介入本身就是这条 Video Essay 的说服来源之一。

<!-- FIGURE:evidence_peak -->

---
## 修辞诉求与节奏

前半段主要靠 logos 把判断立住，中段再用更高冲击的素材把 pathos 接上，所以节奏上不是平均输出，而是越往后越像在给结论加压。

---
## 引用与证据系统

引用素材最有效的时候，是它们不仅重复旁白关键词，而是真的把“为什么这段能算证据”展示出来；如果后半段继续增加对照强度，这个证据系统会更完整。

---
## 开场与收束策略

开场没有先交代背景，而是直接把争议点推出去，收尾再把零散片段回收到同一个判断，这让观众经历的是“先被挑起疑问，再被一步步说服”的过程。

---
## 批评性评注

这条 Video Essay 最成立的地方，是论点、证据和收束至少还在同一条线上；它真正的风险，是少数段落已经接近“旁白说了算”，画面还可以再多承担一点独立论证任务。

---
## 综合述评

- 类型定性：论证递进型 Video Essay
- 目标受众：需要观点链条和素材支撑一起成立的观众
- 核心意图：把零散素材重新排成一条更有说服力的判断

<!-- PYTHON_DIRECT:alignment -->
<!-- PYTHON_DIRECT:scoring_table -->
"""


def _documentary_stub_agent_output() -> str:
    return """## 内容速览

这条片子围绕真实人物和现场信息展开，画面重点落在跟拍、访谈和环境细节上，语言层负责把观众带进这件事的理解框架。

---
## 再现模式与可信度入口

它更接近观察驱动和访谈支撑并用的纪实表达，可信度不是靠一句权威结论压出来，而是靠现场和受访者的连续出现慢慢积出来。

<!-- FIGURE:opening -->

---
## 声音层级系统

旁白没有完全压住所有信息，受访者声音和现场声都还在起作用，所以观众相信的不是单一口径，而是多层声音共同搭出来的现实感。

---
## 论证结构

它先把问题抛出来，再补现场和人物信息，最后收成一个更明确的理解方向，整体论证不是最锋利，但基本站得住。

<!-- FIGURE:evidence_peak -->

---
## 访谈框架

访谈不是单纯填空，而是在帮导演规定“谁有资格发言、谁代表现场经验”，这让受访者本身也成了可信度装置的一部分。

---
## 证据系统与现场感

真正让人信的，是高可信场景和现场素材彼此接住了；如果只剩下说明，没有继续保住环境和人物的在场感，整条片就会马上变薄。

---
## 开场与收尾

开场负责把观众放进问题现场，收尾则把前面的零散观察压成一个较明确的判断，所以首尾之间的认知位移是清楚的。

---
## 批评性评注

它的优势是没有只靠情绪推人走，而是尽量把现场和讲述绑在一起；短板是某些论证环节还不够紧，观众会懂大意，但未必能马上复述完整逻辑。

---
## 综合述评

- 类型定性：观察驱动型纪实访谈
- 目标受众：愿意通过人物和现场去理解一个现实问题的观众
- 核心意图：让观众相信这件事不只是被讲出来，而是真的被看见、被经历过

<!-- PYTHON_DIRECT:alignment -->
<!-- PYTHON_DIRECT:scoring_table -->
"""


def _trailer_stub_agent_output() -> str:
    return """## 内容速览

这支预告围绕一个逐步失控的世界前提展开，画面不断切到角色危机、空间异化和高能瞬间，声音层则负责把悬念和记忆点一起钉住。

---
## 剪辑节奏与视觉语法

它不是平均给信息，而是越往后越加速，镜头、音乐和冲击场面一起把“事情正在失控”的感觉推高。

<!-- FIGURE:opening -->

---
## 信息经济学：揭示与遮蔽

这支预告把世界前提和危险轮廓给得够多，但把真正的答案留住了，所以观众会知道“出事了”，却还不知道事情到底会坏到哪一步。

<!-- FIGURE:setup -->

---
## 世界切片与类型信号

它挑出来的空间和角色关系已经足够把类型锚住，观众很快能判断这是一条靠悬念、危机和升级体验卖人的剧情预告。

---
## 多轨交织分析

真正成立的地方，是画面、台词和音乐经常在同一个点上同时施压，不是在各说各话。

<!-- FIGURE:escalation -->

---
## 结构弧线与记忆点

从前提到升级再到最后一击，这条线基本是顺的，尤其尾段会把观众的注意力压到最该被记住的那几个镜头和片名信息上。

<!-- FIGURE:payoff -->

---
## 开钩与收钩

开头先丢一个足够抓人的不安点，结尾再用片名和高能镜头补最后一钉，这种首尾设计就是它最核心的预告修辞。

---
## 批评性评注

它的说服效率不错，因为给了前提但没有把谜底说死；真正需要注意的，是类型承诺不能只靠高能镜头，后续还得让观众相信正片真的能接住这份期待。

---
## 综合述评

- 类型定性：悬念递增型剧情预告
- 目标受众：会被危险升级、谜面设计和高能记忆点勾住的观众
- 核心意图：让观众在看完后立刻想知道正片到底会把这场危机推到哪里

<!-- PYTHON_DIRECT:alignment -->
<!-- PYTHON_DIRECT:scoring_table -->
"""


def _event_brand_stub_agent_output() -> str:
    return """## 内容速览

这条广告主要在搭一个活动现场的热闹入口，画面不断在大场面、人群参与和品牌露出之间切换，想让观众先产生“我也想加入”的即时感受。

---
## 先看结论

它最成立的地方，是热闹和品牌露出没有完全分家；最需要小心的，是如果后段品牌再更重一点，现场感就会马上被广告感顶掉。

<!-- FIGURE:opening -->

---
## 气氛是怎样越抬越高的

它先用空间和灯光把场子铺开，再让奇观和人群反应轮流抬高情绪，所以观众感受到的不是单一热闹，而是一步步被推上去的参与冲动。

<!-- FIGURE:spectacle -->

---
## 品牌是怎么接进去的

品牌最好用的时候，不是只挂在天上，而是能回到人群动作和现场反应里，所以被记住的不是一个 logo，而是“这场热闹是谁点亮的”。

<!-- FIGURE:product -->

---
## 这条广告好在哪

它的优势在于，奇观、人群和品牌信号大多还在一股劲上，没有完全拆成三件互不相干的事。

---
## 还有哪里能更好

如果还要再往前走一步，最该补的是人物温度，不然观众会记住热闹，却未必真的把品牌和某种具体感受绑死。

<!-- FIGURE:closing -->

---
## 综合述评

- 类型定性：现场热度型活动广告
- 目标受众：会被群体气氛、场面感和即时参与欲望勾住的观众
- 核心意图：把一次热闹活动直接转成品牌记忆

<!-- PYTHON_DIRECT:alignment -->
<!-- PYTHON_DIRECT:scoring_table -->
"""


def _journey_brand_stub_agent_output() -> str:
    return """## 内容速览

这条广告围绕一场被品牌组织起来的集体时刻展开，画面反复在奇观场面、人群参与和品牌露出之间切换，试图把热闹直接转成品牌记忆。

---
## 视觉修辞语法

它不是单纯堆大场面，而是在用灯光、空间、群体动作和高冲击镜头，先把“这是一场值得加入的事件”这层感觉抬起来。

<!-- FIGURE:opening -->

---
## 意义转移系统

整条广告最重要的动作，是把节庆、参与感和群体共鸣这些原本属于现场的意义，慢慢转移到品牌身上，让品牌看起来像是这股情绪的发起者。

<!-- FIGURE:spectacle -->

---
## 说服弧线与品牌角色

它先让观众想加入，再让品牌在高潮段出现，所以品牌不是旁观者，更像这场集体体验的组织者和命名者。

---
## 多轨交织分析

画面、音乐和人群反应大多在同一个方向上发力，这让“热闹”不只是视觉描述，而是完整的情绪压强。

---
## 品牌战略解码

这条片不是在解释产品功能，而是在争夺一种文化位置：品牌想被记住的，不只是名字，而是“这场开心时刻就是由它点亮的”。

<!-- FIGURE:product -->

---
## 首尾注意力设计

开头先铺场，结尾再把品牌落下来，首尾之间的注意力调度基本合理，所以品牌不是硬插进来，而是像给整场活动盖章。

---
## 批评性评注

它最成功的地方，是把奇观和人群温度接到了同一股情绪上；真正的风险，是如果品牌露出再更硬一点，观众就会开始感觉自己在被强行提醒“这是广告”。

---
## 综合述评

- 类型定性：节庆奇观型品牌主片
- 目标受众：会被集体情绪、高参与感和品牌场面表达打动的观众
- 核心意图：把一次热闹而有归属感的群体体验稳稳焊到品牌记忆上

<!-- PYTHON_DIRECT:alignment -->
<!-- PYTHON_DIRECT:scoring_table -->
"""


def _mv_overview_stub_response() -> str:
    return """```json
{
  "overview_title": "视频内容架构总览",
  "overview_summary": "整条片先压住人物关系，再把舞台高点和副歌情绪一起推开。",
  "acts": [
    {
      "visual_title": "空舞台",
      "visual_subtitle": "冷光开场建立",
      "theme_title": "关系压住",
      "theme_subtitle": "00:00 - 00:18",
      "language_title": "we begin in silence",
      "language_subtitle": "先把状态压低",
      "color": "coral"
    },
    {
      "visual_title": "对望旋转",
      "visual_subtitle": "环绕调度升温",
      "theme_title": "张力上拧",
      "theme_subtitle": "00:18 - 00:34",
      "language_title": "can you hear me now",
      "language_subtitle": "把关系拧紧",
      "color": "purple"
    },
    {
      "visual_title": "副歌舞台",
      "visual_subtitle": "灯光和动作爆开",
      "theme_title": "情绪爆发",
      "theme_subtitle": "00:34 - 00:52",
      "language_title": "sing it back to me",
      "language_subtitle": "副歌抬成主题",
      "color": "teal"
    },
    {
      "visual_title": "尾声回看",
      "visual_subtitle": "舞台收束停留",
      "theme_title": "姿态落定",
      "theme_subtitle": "00:52 - 01:06",
      "language_title": "we stay in the light",
      "language_subtitle": "把关系收住",
      "color": "green"
    }
  ]
}
```"""


def _generic_svg_structure_stub_response(title: str = "测试结构图") -> str:
    return f"""```svg
<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 680 180" role="img">
  <title>{title}</title>
  <desc>用于测试报告插图接线的结构图。</desc>
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>
  <text x="124" y="28" text-anchor="middle">左列</text>
  <text x="340" y="28" text-anchor="middle">中列</text>
  <text x="556" y="28" text-anchor="middle">右列</text>
  <line x1="40" y1="35" x2="640" y2="35" stroke="#D1D7E0" stroke-width="0.5"/>
  <rect x="40" y="50" width="168" height="56" rx="8" fill="#FFF1EB" stroke="#E39C82" stroke-width="1"/>
  <rect x="256" y="50" width="168" height="56" rx="8" fill="#FFF1EB" stroke="#E39C82" stroke-width="1"/>
  <rect x="472" y="50" width="168" height="56" rx="8" fill="#FFF1EB" stroke="#E39C82" stroke-width="1"/>
  <text x="124" y="72" text-anchor="middle">入口</text>
  <text x="340" y="72" text-anchor="middle">推进</text>
  <text x="556" y="72" text-anchor="middle">落点</text>
  <line x1="208" y1="78" x2="254" y2="78" stroke="#A6AFBC" stroke-width="1.3" marker-end="url(#arrow)"/>
  <line x1="424" y1="78" x2="470" y2="78" stroke="#A6AFBC" stroke-width="1.3" marker-end="url(#arrow)"/>
</svg>
```"""


def _svg_structure_stub_response(
    title: str = "测试结构图",
    headers: tuple[str, str, str] = ("日常锚点（分离触发）", "动员弧线（仪式功能）", "节庆承诺（体验着陆）"),
) -> str:
    left, middle, right = headers
    return f"""```svg
<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 680 180" role="img">
  <title>{title}</title>
  <desc>用于测试报告插图接线的结构图。</desc>
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>
  <text class="ts" x="124" y="28" text-anchor="middle" style="font-weight:500">{left}</text>
  <text class="ts" x="340" y="28" text-anchor="middle" style="font-weight:500">{middle}</text>
  <text class="ts" x="556" y="28" text-anchor="middle" style="font-weight:500">{right}</text>
  <line x1="40" y1="35" x2="640" y2="35" stroke="#D1D7E0" stroke-width="0.5"/>
  <rect x="40" y="50" width="168" height="56" rx="8" fill="#FFF1EB" stroke="#E39C82" stroke-width="1"/>
  <rect x="256" y="50" width="168" height="56" rx="8" fill="#FFF1EB" stroke="#E39C82" stroke-width="1"/>
  <rect x="472" y="50" width="168" height="56" rx="8" fill="#FFF1EB" stroke="#E39C82" stroke-width="1"/>
  <text x="124" y="72" text-anchor="middle">入口</text>
  <text x="340" y="72" text-anchor="middle">推进</text>
  <text x="556" y="72" text-anchor="middle">落点</text>
  <line x1="208" y1="78" x2="254" y2="78" stroke="#A6AFBC" stroke-width="1.3" marker-end="url(#arrow)"/>
  <line x1="424" y1="78" x2="470" y2="78" stroke="#A6AFBC" stroke-width="1.3" marker-end="url(#arrow)"/>
</svg>
```"""


def _class_based_svg_structure_stub_response(title: str = "测试结构图") -> str:
    return f"""```svg
<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 680 180" role="img">
  <title>{title}</title>
  <desc>用于测试 class 样式补全的结构图。</desc>
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>
  <text class="ts" x="124" y="28" text-anchor="middle" style="font-weight:500">视觉场域（感官素材）</text>
  <text class="ts" x="340" y="28" text-anchor="middle" style="font-weight:500">体验建构（感知状态）</text>
  <text class="ts" x="556" y="28" text-anchor="middle" style="font-weight:500">声画博弈（多媒体关系）</text>
  <line x1="40" y1="35" x2="640" y2="35" stroke="var(--color-border-tertiary)" stroke-width="0.5"/>
  <g class="node c-coral">
    <rect x="40" y="50" width="168" height="56" rx="8" stroke-width="0.5"/>
    <text class="th" x="124" y="69" text-anchor="middle" dominant-baseline="central">入口</text>
    <text class="ts" x="124" y="89" text-anchor="middle" dominant-baseline="central">暖色启动</text>
  </g>
  <g class="node c-teal">
    <rect x="256" y="50" width="168" height="56" rx="8" stroke-width="0.5"/>
    <text class="th" x="340" y="69" text-anchor="middle" dominant-baseline="central">推进</text>
    <text class="ts" x="340" y="89" text-anchor="middle" dominant-baseline="central">冷静过渡</text>
  </g>
  <g class="node c-purple">
    <rect x="472" y="50" width="168" height="56" rx="8" stroke-width="0.5"/>
    <text class="th" x="556" y="69" text-anchor="middle" dominant-baseline="central">对位</text>
    <text class="ts" x="556" y="89" text-anchor="middle" dominant-baseline="central">多媒体博弈</text>
  </g>
  <line x1="208" y1="78" x2="254" y2="78" class="arr" marker-end="url(#arrow)" stroke="var(--color-border-secondary)"/>
  <line x1="254" y1="84" x2="208" y2="84" class="arr" marker-end="url(#arrow)" stroke="var(--color-border-secondary)"/>
  <line x1="424" y1="78" x2="470" y2="78" class="arr" marker-end="url(#arrow)" stroke="var(--color-border-secondary)"/>
  <line x1="470" y1="84" x2="424" y2="84" class="arr" marker-end="url(#arrow)" stroke="var(--color-border-secondary)"/>
</svg>
```"""


def _auto_agent_output_for_payload(payload: dict) -> str:
    spec = template_engine.build_audiovisual_body_prompt(payload, payload["audiovisual_route"])
    required_sections = spec["required_sections"]
    headings = [heading.removeprefix("## ").strip() for heading in required_sections]
    body_text = _raw_heading_stub_output(headings, payload=payload)
    closer = [
        "",
        "## 综合述评",
        "",
        "- 类型定性：测试类型",
        "- 目标受众：测试受众",
        "- 核心意图：测试意图",
        "",
        "<!-- PYTHON_DIRECT:alignment -->",
        "<!-- PYTHON_DIRECT:scoring_table -->",
    ]
    return body_text + "\n".join(closer)


def _raw_heading_stub_output(headings: list[str], payload: dict | None = None) -> str:
    """Produce a stub report that satisfies the post-restructure depth validator.

    Each required ## heading gets all its ### subsections (if the raw prompt
    defines any) and enough padding + scene citations to clear the min-chars
    and min-scene-evidence thresholds. Used by tests that stub out the agent;
    real-world outputs come from the agent itself.
    """
    required_subsections: dict[str, list[str]] = {}
    if payload is not None:
        route = payload.get("audiovisual_route") or {}
        if raw_prompt_adapter.raw_prompt_available_for_data(payload, route):
            prompt_text = raw_prompt_adapter.load_sanitized_raw_prompt_for_data(payload, route)
            required_subsections = raw_prompt_adapter.extract_required_subsections_from_raw_prompt(prompt_text)

    filler_scene_line = (
        "Scene 001 与 Scene 002、Scene 003 三段镜头的组合足以支撑这一节的判断，"
        "并辅以 Scene 004 补强证据；后续 Scene 005 呼应作为对照，完成这一子条目的分析闭环。"
        "Scene 006 给出反向对照例证，Scene 007 则引入转折样本，进一步稳固本节结论。"
    )
    filler_paragraph = (
        "这段文字是测试填充，用来把子条目字数撑到机器校验阈值以上；"
        "真实产出会有具体修辞推导、理论操作化与分镜引用，这里不展开。"
        "为了保证机器校验能通过最低字数门槛，这段文字会在此处以同义换述的方式重复一轮，"
        "说明测试层面只关心结构合规，不追究语义原创性；真正的分析文本由 agent 在运行时补齐。"
        "额外补充若干半中半英的陈述：stub filler ensures coverage thresholds are exceeded。"
    )

    module_closer = (
        "小结：本模块在 Scene 001、Scene 002、Scene 003、Scene 004 之间建立起可追溯的证据链，"
        "并通过 Scene 005、Scene 006 给出对照，测试层面仅确认结构完整与字数阈值，"
        "并不追求语义密度；真实运行时 agent 会把这些段落替换成具体的修辞、节奏与符号推导。"
        "This closing paragraph pads the module so each `##` clears the min-char threshold required by the validator."
    )

    blocks: list[str] = []
    for heading in headings:
        subsections = required_subsections.get(heading) or []
        lines = [f"## {heading}", ""]
        if subsections:
            for sub in subsections:
                lines.extend(
                    [
                        f"### {sub}",
                        "",
                        filler_scene_line,
                        filler_paragraph,
                        "",
                    ]
                )
        else:
            lines.extend(
                [
                    filler_scene_line,
                    filler_paragraph,
                    filler_paragraph,
                    "",
                ]
            )
        lines.extend([module_closer, ""])
        blocks.append("\n".join(lines).rstrip())
    return "\n\n".join(blocks)


def _expected_required_sections_for_payload(payload: dict) -> list[str]:
    route = payload["audiovisual_route"]
    if raw_prompt_adapter.raw_prompt_available_for_data(payload, route):
        prompt_text = raw_prompt_adapter.load_sanitized_raw_prompt_for_data(payload, route)
        headings = raw_prompt_adapter.extract_required_sections_from_raw_prompt(prompt_text)
        return [f"## {heading}" for heading in headings]

    template_text = template_engine.load_route_template_for_data(payload, route)
    tasks = template_engine._split_template_sections(template_text)["tasks"]
    return template_engine._extract_required_sections(tasks)


def test_load_route_template_resolves_includes() -> None:
    template_text = template_engine.load_route_template("mix_music")
    sections = template_engine._split_template_sections(template_text)

    assert "<!-- INCLUDE:" not in template_text
    assert "你是一位专业的视听内容分析师" in sections["system"]
    assert "总场景数" in sections["data"]
    assert "## 节拍骨架与卡点组织" in sections["tasks"]
    assert [block["name"] for block in sections["python_direct"]] == ["alignment", "scoring_table"]


@pytest.mark.parametrize(
    ("framework", "system_phrase"),
    [
        ("commentary_mix", "视听论证机器"),
        ("documentary_generic", "建构可信度的修辞文本"),
        ("mix_music", "节奏混剪视听分析师"),
        ("meme", "开放的参与式修辞模板"),
        ("narrative_trailer", "选择性释放"),
        ("narrative_performance", "音乐视频叙事分析师"),
        ("journey_brand_film", "意义转移"),
    ],
)
def test_updated_route_templates_embed_new_prompt_frameworks(framework: str, system_phrase: str) -> None:
    template_text = template_engine.load_route_template(framework)
    sections = template_engine._split_template_sections(template_text)

    assert system_phrase in sections["system"]


@pytest.mark.parametrize(
    ("framework", "type_key", "type_cn", "system_phrase"),
    [
        ("concept_mv", "concept_mv", "概念 MV", "自律的感官-概念装置"),
        ("cinematic_life", "cinematic_vlog", "生活影像 / Vlog", "自我展演文本"),
        ("event_brand_ad", "event_promo", "活动 / 促销广告", "仪式动员机器"),
        ("infographic_animation", "infographic_motion", "信息动画", "时间化的认知引导装置"),
        ("technical_explainer", "explainer", "讲解 / 教学", "认知脚手架机器"),
        ("narrative_performance", "live_session", "现场演出", "临场性的中介文本"),
        ("documentary_generic", "reality_record", "现实纪录", "索引性文本"),
        ("lecture_performance", "talking_head", "口播 / 讲述", "拟社会互动文本"),
        ("pure_motion_graphics", "motion_graphics", "纯动态图形", "形式的运动"),
        ("experimental", "experimental", "形式实验", "将形式本身升格为内容"),
    ],
)
def test_type_specific_templates_override_shared_framework_templates(
    framework: str,
    type_key: str,
    type_cn: str,
    system_phrase: str,
) -> None:
    payload = _with_classification(_minimal_payload_for_framework(framework), type_key, type_cn)
    template_text = template_engine.load_route_template_for_data(payload, payload["audiovisual_route"])
    sections = template_engine._split_template_sections(template_text)

    assert system_phrase in sections["system"]


@pytest.mark.parametrize(
    ("framework", "type_key", "type_cn"),
    [
        ("concept_mv", "concept_mv", "概念 MV"),
        ("cinematic_life", "cinematic_vlog", "生活影像 / Vlog"),
        ("event_brand_ad", "event_promo", "活动 / 促销广告"),
        ("infographic_animation", "infographic_motion", "信息动画"),
        ("technical_explainer", "explainer", "讲解 / 教学"),
        ("narrative_performance", "narrative_short", "叙事短片"),
        ("narrative_mix", "narrative_short", "叙事短片"),
        ("lecture_performance", "talking_head", "口播 / 讲述"),
        ("documentary_generic", "talking_head", "口播 / 讲述"),
        ("cinematic_life", "mood_montage", "情绪蒙太奇"),
        ("mix_music", "mood_montage", "情绪蒙太奇"),
        ("pure_motion_graphics", "mood_montage", "情绪蒙太奇"),
        ("narrative_performance", "live_session", "现场演出"),
        ("silent_performance", "live_session", "现场演出"),
        ("documentary_generic", "reality_record", "现实纪录"),
        ("silent_reality", "reality_record", "现实纪录"),
        ("pure_motion_graphics", "motion_graphics", "纯动态图形"),
        ("abstract_sfx", "motion_graphics", "纯动态图形"),
        ("experimental", "experimental", "形式实验"),
    ],
)
def test_type_specific_templates_resolve_placeholders(
    framework: str,
    type_key: str,
    type_cn: str,
) -> None:
    payload = _with_classification(_minimal_payload_for_framework(framework), type_key, type_cn)
    template_text = template_engine.load_route_template_for_data(payload, payload["audiovisual_route"])
    sections = template_engine._split_template_sections(template_text)
    context = template_engine.build_template_context(payload, payload["audiovisual_route"])
    unresolved = template_engine._UNRESOLVED_PLACEHOLDER_RE.findall(
        template_engine.fill_template(sections["data"], context) + template_engine.fill_template(sections["tasks"], context)
    )

    assert unresolved == []


def test_experimental_framework_is_supported_by_template_engine() -> None:
    assert template_engine.route_supports_template({"framework": "experimental"})


def test_type_specific_templates_can_resolve_from_route_child_type_without_classification_result() -> None:
    payload = _with_child_route(_minimal_payload_for_framework("event_brand_ad"), "event_promo", "活动 / 促销广告")

    template_text = template_engine.load_route_template_for_data(payload, payload["audiovisual_route"])
    sections = template_engine._split_template_sections(template_text)

    assert "仪式动员机器" in sections["system"]


def test_type_specific_templates_can_resolve_from_route_subtype_without_child_type() -> None:
    payload = _with_route_subtype_only(_minimal_payload_for_framework("infographic_animation"), "信息动画")

    template_text = template_engine.load_route_template_for_data(payload, payload["audiovisual_route"])
    sections = template_engine._split_template_sections(template_text)

    assert "时间化的认知引导装置" in sections["system"]


@pytest.mark.parametrize(
    ("type_key", "system_phrase", "required_headings"),
    [
        (
            "commentary_remix",
            'Video Essay 不是一段"带画面的文章朗读"',
            [
                "论证架构拆解",
                "旁白—画面权力关系",
                "解说者主体性分析",
                "修辞诉求配比与节奏",
                "引用生态系统",
                "视听论证节奏",
                "开场与收束策略",
            ],
        ),
        (
            "documentary_essay",
            '纪录片不是"现实的透明窗口"',
            [
                "再现模式判定与视觉语法",
                "声音层级系统",
                "论证结构分析",
                "访谈框架分析",
                "多轨交织分析",
                "证据系统与可信度装置",
                "符号系统与文化坐标",
                "开场建构与收尾定性",
            ],
        ),
        (
            "brand_film",
            "品牌本身是一个空洞的能指",
            [
                "视觉修辞语法",
                "意义转移系统：参照世界拆解",
                "说服弧线与品牌叙事结构",
                "多轨交织分析",
                "品牌符号学与意识形态分析",
                "品牌战略解码",
                "开钩与收钩：注意力经济的首尾博弈",
                "媒介语境与 Campaign 生态位分析",
            ],
        ),
        (
            "narrative_trailer",
            "信息的选择性释放",
            [
                "剪辑节奏与视觉语法",
                "信息经济学：揭示与遮蔽的博弈",
                "世界切片：空间展示策略",
                "多轨交织分析",
                "修辞诉求与类型信号系统",
                "预告片结构弧线",
                "开钩与收钩",
            ],
        ),
        (
            "rhythm_remix",
            "混剪师签名与技术指纹",
            [
                "节拍骨架解剖：剪切率与音乐结构的映射",
                "素材考古学：来源谱系与采样策略",
                "视觉语法统计：为节奏服务的视觉参数",
                "声画对位精析：多轨交织的微观解剖",
                '能量弧线与"高潮工程学"',
                "混剪师签名与技术指纹",
                "开钩与收尾",
            ],
        ),
        (
            "meme_viral",
            "三维度传播驱动力分析",
            [
                "模板结构解剖",
                "三维度传播驱动力分析",
                "不协调结构与幽默机制",
                "多模态构图分析",
                "互文网络与文化门槛",
                "传播动力学与平台适配",
                "生命周期与收尾姿态",
            ],
        ),
    ],
)
def test_batch1_types_use_original_prompts_for_body_generation(
    type_key: str,
    system_phrase: str,
    required_headings: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _child_type_payload(type_key)
    captured: dict[str, str] = {}

    def _stub_request(system_prompt, user_message, client=None, runtime_config=None):
        captured["system_prompt"] = system_prompt
        captured["user_message"] = user_message
        return _raw_heading_stub_output(required_headings, payload=payload)

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", _stub_request)

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert system_phrase in captured["system_prompt"]
    for heading in required_headings:
        assert f"## {heading}" in markdown


@pytest.mark.parametrize("type_key", RAW_PROMPT_CHILD_TYPES)
def test_stable_raw_prompt_types_use_original_prompt_text(
    type_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _child_type_payload(type_key)
    route = payload["audiovisual_route"]
    expected_prompt = raw_prompt_adapter.load_sanitized_raw_prompt_for_data(payload, route).strip()
    required_headings = raw_prompt_adapter.extract_required_sections_from_raw_prompt(expected_prompt)
    captured: dict[str, str] = {}

    def _stub_request(system_prompt, user_message, client=None, runtime_config=None):
        captured["system_prompt"] = system_prompt
        return _raw_heading_stub_output(required_headings, payload=payload)

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", _stub_request)

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert captured["system_prompt"] == expected_prompt
    for heading in required_headings:
        assert f"## {heading}" in markdown


def test_raw_prompt_path_keeps_alignment_and_scoring_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _child_type_payload("commentary_remix")
    headings = raw_prompt_adapter.extract_required_sections_from_raw_prompt(
        raw_prompt_adapter.load_sanitized_raw_prompt_for_data(payload, payload["audiovisual_route"])
    )

    def _stub_request(system_prompt, user_message, client=None, runtime_config=None):
        return (
            _raw_heading_stub_output(headings, payload=payload)
            + "\n\n## 综合述评\n\n测试内容。\n\n<!-- PYTHON_DIRECT:alignment -->\n<!-- PYTHON_DIRECT:scoring_table -->"
        )

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", _stub_request)

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert "**视听对齐度**" in markdown
    assert "| 维度 | 平均分 | 这一维在看什么 |" in markdown
    assert "<!-- PYTHON_DIRECT:" not in markdown


def test_load_route_template_falls_back_to_family_template(tmp_path: Path) -> None:
    (tmp_path / "_family_atmospheric.md").write_text("family template body", encoding="utf-8")

    template_text = template_engine.load_route_template("mix_music", templates_dir=tmp_path)

    assert template_text == "family template body"


def test_load_route_template_reports_missing_include_clearly(tmp_path: Path) -> None:
    (tmp_path / "template_demo.md").write_text("<!-- INCLUDE:missing.md -->", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match=r"Included template 'missing\.md' not found"):
        template_engine.load_route_template("demo", templates_dir=tmp_path)


def test_load_route_template_rejects_cyclic_includes(tmp_path: Path) -> None:
    (tmp_path / "template_demo.md").write_text("<!-- INCLUDE:a.md -->", encoding="utf-8")
    (tmp_path / "a.md").write_text("A<!-- INCLUDE:b.md -->", encoding="utf-8")
    (tmp_path / "b.md").write_text("B<!-- INCLUDE:a.md -->", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Cyclic template include detected"):
        template_engine.load_route_template("demo", templates_dir=tmp_path)


def test_load_route_template_resolves_nested_includes_relative_to_parent(tmp_path: Path) -> None:
    nested_dir = tmp_path / "partials"
    nested_dir.mkdir()
    (tmp_path / "template_demo.md").write_text("<!-- INCLUDE:partials/a.md -->", encoding="utf-8")
    (nested_dir / "a.md").write_text("A<!-- INCLUDE:b.md -->", encoding="utf-8")
    (nested_dir / "b.md").write_text("nested body", encoding="utf-8")

    template_text = template_engine.load_route_template("demo", templates_dir=tmp_path)

    assert template_text == "Anested body"


@pytest.mark.parametrize("framework", ALL_REPORT_FRAMEWORKS)
def test_all_route_templates_exist_and_parse(framework: str) -> None:
    template_text = template_engine.load_route_template(framework)
    sections = template_engine._split_template_sections(template_text)

    assert sections["system"]
    assert sections["data"]
    assert sections["tasks"]
    assert sections["python_direct"]


def test_all_route_frameworks_are_supported_by_template_engine() -> None:
    unsupported = [framework for framework in ALL_REPORT_FRAMEWORKS if not template_engine.route_supports_template({"framework": framework})]
    assert unsupported == []


def test_build_template_context_extracts_mix_music_metrics() -> None:
    payload = _mix_music_payload()
    context = template_engine.build_template_context(payload, payload["audiovisual_route"])

    assert context["avg_duration"] == "1.3"
    assert context["short_cut_ratio"] == "25"
    assert context["beat_hit_scenes"] == "Scene 004"
    assert context["high_score_ratio"] == "75"
    assert context["emotion_peak_count"] == "3"
    assert "节奏相关" in context["scenes_by_dimension"]


def test_build_template_context_extracts_concept_mv_metrics() -> None:
    payload = _concept_mv_payload()
    context = template_engine.build_template_context(payload, payload["audiovisual_route"])

    assert context["dominant_imagery"] == "光"
    assert context["dominant_imagery_count"] == "4"
    assert context["emotion_peak_count"] == "3"
    assert "意象相关" in context["scenes_by_dimension"]


def test_build_template_context_extracts_narrative_performance_groups() -> None:
    payload = _narrative_performance_payload()
    context = template_engine.build_template_context(payload, payload["audiovisual_route"])

    assert context["setup_scene_refs"] == "Scene 001"
    assert context["conflict_scene_refs"] == "Scene 002"
    assert context["climax_scene_refs"] == "Scene 003、Scene 004"
    assert context["secondary_layer_name"] == "音乐表达层"
    assert "开场建立" in context["scenes_by_dimension"]


def test_build_template_context_extracts_cinematic_life_metrics() -> None:
    payload = _cinematic_life_payload()
    context = template_engine.build_template_context(payload, payload["audiovisual_route"])

    assert context["lighting_scene_count"] == "3"
    assert context["life_scene_count"] == "3"
    assert context["aesthetic_credibility_gap"] == "1.5"
    assert "氛围相关" in context["scenes_by_dimension"]


def test_build_template_context_extracts_commentary_mix_metrics() -> None:
    payload = _commentary_mix_payload()
    context = template_engine.build_template_context(payload, payload["audiovisual_route"])

    assert context["argument_scene_count"] == "3"
    assert context["conflict_scene_count"] == "2"
    assert context["argument_scene_refs"] == "Scene 001、Scene 002、Scene 003"
    assert "论点相关" in context["scenes_by_dimension"]


def test_build_markdown_uses_template_engine_for_mix_music(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _mix_music_payload()

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_stub_agent_output())

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert markdown.startswith("# 视听剖析报告")
    assert "## 路由判断" in markdown
    assert "## 节拍骨架与卡点组织" in markdown
    assert "## 声画对位与高潮工程学" in markdown
    assert "高压节奏型动作混剪" in markdown
    assert "视听对齐度" in markdown
    assert "| 冲击力 |" in markdown
    assert "<!-- FIGURE:" not in markdown
    assert "<!-- PYTHON_DIRECT:" not in markdown


def test_build_markdown_uses_template_engine_for_meme(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _minimal_payload_for_framework("meme")

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_meme_stub_agent_output())

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert "## 模板结构解剖" in markdown
    assert "## 不协调结构与笑点机制" in markdown
    assert "反应翻转型视频梗" in markdown


def test_build_markdown_uses_template_engine_for_concept_mv(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _concept_mv_payload()

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_concept_stub_agent_output())

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert "## 意象一致性" in markdown
    assert "梦境意象型概念 MV" in markdown
    assert "视听对齐度" in markdown


def test_build_markdown_uses_template_engine_for_narrative_performance(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _narrative_performance_payload()

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_narrative_stub_agent_output())

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert "## 视觉语法统计" in markdown
    assert "## 双线交织分析" in markdown
    assert "舞台叙事型剧情 MV" in markdown


def test_build_markdown_uses_template_engine_for_cinematic_life(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _cinematic_life_payload()

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_cinematic_stub_agent_output())

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert "## 氛围一致性" in markdown
    assert "暖色日常电影化短片" in markdown


def test_build_markdown_uses_template_engine_for_commentary_mix(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _commentary_mix_payload()

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_commentary_stub_agent_output())

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert "## 论证架构拆解" in markdown
    assert "## 旁白—画面权力关系" in markdown
    assert "论证递进型 Video Essay" in markdown


def test_build_markdown_uses_template_engine_for_documentary_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _minimal_payload_for_framework("documentary_generic")

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_documentary_stub_agent_output())

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert "## 声音层级系统" in markdown
    assert "## 访谈框架" in markdown
    assert "观察驱动型纪实访谈" in markdown


def test_build_markdown_uses_template_engine_for_narrative_trailer(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _minimal_payload_for_framework("narrative_trailer")

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_trailer_stub_agent_output())

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert "## 信息经济学：揭示与遮蔽" in markdown
    assert "## 开钩与收钩" in markdown
    assert "悬念递增型剧情预告" in markdown


def test_build_markdown_uses_template_engine_for_event_brand_ad(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _minimal_payload_for_framework("event_brand_ad")

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_event_brand_stub_agent_output())

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert "## 气氛是怎样越抬越高的" in markdown
    assert "## 品牌是怎么接进去的" in markdown
    assert "现场热度型活动广告" in markdown


def test_build_markdown_uses_template_engine_for_journey_brand_film(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _minimal_payload_for_framework("journey_brand_film")

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_journey_brand_stub_agent_output())

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert "## 意义转移系统" in markdown
    assert "## 品牌战略解码" in markdown
    assert "节庆奇观型品牌主片" in markdown


def test_mv_overview_prompt_absorbs_svg_template_constraints() -> None:
    prompt_text = (ROOT / "scripts" / "templates" / "prompt_mv_overview_chart.md").read_text(encoding="utf-8")

    assert "叙事弧线（主题）" in prompt_text
    assert "颜色要反映阶段情绪变化" in prompt_text


def test_inject_figure_blocks_preserves_marker_order_when_names_repeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        template_engine,
        "_highlight_specs_for_route",
        lambda data, route: [{"title": "one"}, {"title": "two"}],
        raising=False,
    )
    monkeypatch.setattr(template_engine, "_render_figure_block", lambda spec, report_dir: f"BLOCK-{spec['title']}")

    body = "before\n<!-- FIGURE:unknown -->\nmiddle\n<!-- FIGURE:unknown -->\nafter"

    rendered = template_engine._inject_figure_blocks(body, {}, {}, None)

    assert rendered == "before\nBLOCK-one\nmiddle\nBLOCK-two\nafter"


def test_inject_figure_blocks_prefers_marker_rationale_over_static_route_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    screenshot_path = tmp_path / "scene-001.png"
    screenshot_path.write_bytes(b"png")
    scene = {
        "scene_number": 1,
        "description": "角色推门走进空间，作为开场镜头。",
        "frame_path": str(screenshot_path),
    }

    monkeypatch.setattr(
        template_engine,
        "_highlight_specs_for_route",
        lambda data, route: [("开场镜头", scene, "这是旧的静态说明，不该直接落进报告")],
    )

    rendered = template_engine._inject_figure_blocks("before\n<!-- FIGURE:opening -->\nafter", {}, {}, tmp_path)

    assert "这是旧的静态说明，不该直接落进报告" not in rendered
    assert "开场" in rendered


def test_template_engine_defaults_to_template_path_without_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "video_id": "default-template-route",
        "title": "Trailer sample",
        "video_title": "Trailer sample",
        "audiovisual_route": {
            "framework": "narrative_trailer",
            "route_label": "剧情预告 / 叙事预告",
            "route_subtype": "",
            "reference": "预告片 / teaser / trailer",
            "visual_axis": "P",
            "visual_label": "原创演绎拍摄",
            "audio_axis": "LM",
            "audio_label": "语言 + 音乐并重",
            "visual_rationale": "画面以预告式高能片段为主。",
            "audio_rationale": "台词和音乐一起制造悬念。",
            "voiceover_ratio": 0.35,
            "dual_layer": {"enabled": False},
            "content_profile": {"key": "trailer"},
        },
        "scenes": [
            {
                "scene_number": 1,
                "duration_seconds": 1.4,
                "description": "主角推开门，预告片的危险前提被点亮。",
                "weighted_score": 7.8,
                "scores": {
                    "aesthetic_beauty": 8,
                    "credibility": 6,
                    "impact": 8,
                    "memorability": 7,
                    "fun_interest": 6,
                },
                "analysis_dimensions": {
                    "technical_quality": 7.5,
                    "narrative_function": 7.8,
                    "emotional_effect": 7.2,
                    "information_efficiency": 6.4,
                    "clip_usability": 7.0,
                },
                "storyboard": {
                    "voiceover": "This is where it begins",
                    "onscreen_text": "",
                    "shot_size": "中景",
                    "visual_style": "预告片段",
                    "technique": "表演拍摄",
                    "camera_movement": "稳定推进",
                    "lighting": "高反差舞台灯",
                },
            }
        ],
    }

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_trailer_stub_agent_output())

    markdown = report_builder.build_audiovisual_report_markdown(payload)

    assert markdown.startswith("# 视听剖析报告")
    assert "## 信息经济学：揭示与遮蔽" in markdown
    assert "悬念递增型剧情预告" in markdown


def test_template_engine_raises_when_agent_path_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "video_id": "fallback-route",
        "title": "Trailer sample",
        "video_title": "Trailer sample",
        "audiovisual_route": {
            "framework": "narrative_trailer",
            "route_label": "剧情预告 / 叙事预告",
            "route_subtype": "",
            "reference": "预告片 / teaser / trailer",
            "visual_axis": "P",
            "visual_label": "原创演绎拍摄",
            "audio_axis": "LM",
            "audio_label": "语言 + 音乐并重",
            "visual_rationale": "画面以预告式高能片段为主。",
            "audio_rationale": "台词和音乐一起制造悬念。",
            "voiceover_ratio": 0.35,
            "dual_layer": {"enabled": False},
            "content_profile": {"key": "trailer"},
        },
        "scenes": [
            {
                "scene_number": 1,
                "duration_seconds": 1.4,
                "description": "主角推开门，预告片的危险前提被点亮。",
                "weighted_score": 7.8,
                "scores": {
                    "aesthetic_beauty": 8,
                    "credibility": 6,
                    "impact": 8,
                    "memorability": 7,
                    "fun_interest": 6,
                },
                "analysis_dimensions": {
                    "technical_quality": 7.5,
                    "narrative_function": 7.8,
                    "emotional_effect": 7.2,
                    "information_efficiency": 6.4,
                    "clip_usability": 7.0,
                },
                "storyboard": {
                    "voiceover": "This is where it begins",
                    "onscreen_text": "",
                    "shot_size": "中景",
                    "visual_style": "预告片段",
                    "technique": "表演拍摄",
                    "camera_movement": "稳定推进",
                    "lighting": "高反差舞台灯",
                },
            }
        ],
    }

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "route_supports_template", lambda route: True)
    monkeypatch.setattr(
        template_engine,
        "synthesize_audiovisual_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("anthropic unavailable")),
    )

    with pytest.raises(RuntimeError, match="anthropic unavailable"):
        report_builder.build_audiovisual_report_markdown(payload)


def test_route_supports_mv_overview_for_music_video_routes() -> None:
    assert template_engine.route_supports_mv_overview(_mix_music_route())
    assert template_engine.route_supports_mv_overview(_concept_mv_payload()["audiovisual_route"])
    assert template_engine.route_supports_mv_overview(_narrative_performance_payload()["audiovisual_route"])
    assert not template_engine.route_supports_mv_overview(_commentary_mix_payload()["audiovisual_route"])


def test_generate_mv_overview_assets_writes_png_and_svg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _narrative_performance_payload()
    route = payload["audiovisual_route"]

    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_mv_overview_stub_response())

    assets = template_engine.generate_mv_overview_assets(_narrative_stub_agent_output(), payload, route, tmp_path)

    assert assets["summary"] == "整条片先压住人物关系，再把舞台高点和副歌情绪一起推开。"
    assert assets["png"].exists()
    assert assets["svg"].exists()
    svg_text = assets["svg"].read_text(encoding="utf-8")
    assert 'role="img"' in svg_text
    assert "叙事弧线（主题）" in svg_text


def test_generate_audiovisual_outputs_prepend_mv_overview_chart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _child_type_payload("performance_mv")

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    _stub_handoff_outputs(
        monkeypatch,
        body=_auto_agent_output_for_payload(payload),
        overview=_mv_overview_stub_response(),
    )

    outputs = report_builder.generate_audiovisual_report_outputs(payload, tmp_path, formats=("md",))
    markdown = outputs["md"].read_text(encoding="utf-8")

    assert markdown.index("## 视频内容架构总览") < markdown.index("## 路由判断")
    assert "narrative-performance-test_audiovisual_overview.png" in markdown

    blocks = build_audiovisual_report_pdf_blocks(payload, report_dir=tmp_path, markdown_text=markdown)
    image_index = next(index for index, block in enumerate(blocks) if block.get("type") == "image")
    route_index = next(index for index, block in enumerate(blocks) if block.get("text") == "路由判断")
    assert image_index < route_index


@pytest.mark.parametrize(
    ("type_key", "expected_prompt_name"),
    [
        ("event_promo", "event-promo-svg-diagram-prompt.md"),
        ("brand_film", "ad-svg-diagram-prompt.md"),
        ("documentary_essay", "documentary-svg-diagram-prompt.md"),
        ("commentary_remix", "explainer-svg-diagram-prompt.md"),
        ("narrative_trailer", "trailer-svg-diagram-prompt.md"),
        ("performance_mv", None),
    ],
)
def test_child_type_svg_prompt_resolution(type_key: str, expected_prompt_name: str | None) -> None:
    payload = _child_type_payload(type_key)

    prompt_path = template_engine.resolve_child_type_svg_prompt_path(payload, payload["audiovisual_route"])

    if expected_prompt_name is None:
        assert prompt_path is None
    else:
        assert prompt_path is not None
        assert prompt_path.name == expected_prompt_name


def test_generate_child_type_svg_diagram_assets_writes_png_and_svg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _child_type_payload("event_promo")
    route = payload["audiovisual_route"]

    monkeypatch.setattr(
        template_engine,
        "_request_agent_report",
        lambda system_prompt, user_message, client=None, **kwargs: _svg_structure_stub_response("节庆宣传广告动员结构图"),
    )

    assets = template_engine.generate_child_type_svg_diagram_assets(_event_brand_stub_agent_output(), payload, route, tmp_path)

    assert assets["title"] == "节庆宣传广告动员结构图"
    assert assets["png"].exists()
    assert assets["svg"].exists()
    svg_text = assets["svg"].read_text(encoding="utf-8")
    assert 'role="img"' in svg_text
    assert "<title>节庆宣传广告动员结构图</title>" in svg_text


def test_generate_child_type_svg_diagram_assets_rejects_missing_prompt_dimensions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _child_type_payload("event_promo")
    route = payload["audiovisual_route"]

    monkeypatch.setattr(
        template_engine,
        "_request_agent_report",
        lambda system_prompt, user_message, client=None, **kwargs: _generic_svg_structure_stub_response("节庆宣传广告动员结构图"),
    )

    with pytest.raises(ValueError, match="SVG prompt fidelity"):
        template_engine.generate_child_type_svg_diagram_assets(_event_brand_stub_agent_output(), payload, route, tmp_path)


def test_generate_child_type_svg_diagram_assets_inlines_styles_for_class_based_svg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _child_type_payload("concept_mv")
    route = payload["audiovisual_route"]

    monkeypatch.setattr(
        template_engine,
        "_request_agent_report",
        lambda system_prompt, user_message, client=None, **kwargs: _class_based_svg_structure_stub_response("概念 MV 感知建筑图"),
    )

    assets = template_engine.generate_child_type_svg_diagram_assets(_event_brand_stub_agent_output(), payload, route, tmp_path)
    svg_text = assets["svg"].read_text(encoding="utf-8")

    assert "<style>" in svg_text
    assert ".node.c-coral rect" in svg_text
    assert "--color-border-secondary: #A6AFBC;" in svg_text
    assert "--color-border-tertiary: #D1D7E0;" in svg_text


def test_generate_audiovisual_outputs_prepend_child_type_svg_diagram(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _child_type_payload("event_promo")

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    _stub_handoff_outputs(
        monkeypatch,
        body=_auto_agent_output_for_payload(payload),
        diagram=_svg_structure_stub_response("节庆宣传广告动员结构图"),
    )

    outputs = report_builder.generate_audiovisual_report_outputs(payload, tmp_path, formats=("md",))
    markdown = outputs["md"].read_text(encoding="utf-8")

    assert markdown.index("## 节庆宣传广告动员结构图") < markdown.index("## 路由判断")
    assert "](<test-event_brand_ad_audiovisual_structure.png>)" in markdown
    assert outputs["png"].exists()
    assert outputs["svg"].exists()

    blocks = build_audiovisual_report_pdf_blocks(payload, report_dir=tmp_path, markdown_text=markdown)
    image_index = next(index for index, block in enumerate(blocks) if block.get("type") == "image")
    route_index = next(index for index, block in enumerate(blocks) if block.get("text") == "路由判断")
    assert image_index < route_index


def test_generate_outputs_normalize_local_absolute_image_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _child_type_payload("event_promo")
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    scene_path = frames_dir / "scene 001.png"
    scene_path.write_bytes(b"fake-image")

    structure_path = tmp_path / "chart image.png"
    structure_path.write_bytes(b"fake-image")

    absolute_markdown = "\n".join(
        [
            "# 视听剖析报告",
            "",
            f"![结构图](<{structure_path}>)",
            "",
            f"![Scene 001]({scene_path})",
            "",
        ]
    )

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(report_builder, "assemble_audiovisual_report_markdown", lambda *args, **kwargs: (absolute_markdown, {}))

    outputs = report_builder.generate_audiovisual_report_outputs(payload, tmp_path, formats=("md",))
    markdown = outputs["md"].read_text(encoding="utf-8")

    assert "](<chart image.png>)" in markdown
    assert "](<frames/scene 001.png>)" in markdown
    assert str(tmp_path) not in markdown


def test_generate_audiovisual_outputs_keep_mv_overview_for_performance_mv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _child_type_payload("performance_mv")

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    _stub_handoff_outputs(
        monkeypatch,
        body=_auto_agent_output_for_payload(payload),
        overview=_mv_overview_stub_response(),
    )

    outputs = report_builder.generate_audiovisual_report_outputs(payload, tmp_path, formats=("md",))
    markdown = outputs["md"].read_text(encoding="utf-8")

    assert "## 视频内容架构总览" in markdown
    assert "narrative-performance-test_audiovisual_overview.png" in markdown
    assert "audiovisual_structure.png" not in markdown


@pytest.mark.parametrize("type_key", ALL_CHILD_ROUTER_TYPES)
def test_child_router_types_generate_markdown_via_real_report_entry(
    type_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _child_type_payload(type_key)

    monkeypatch.setattr(report_builder, "enrich_audiovisual_layers", lambda data: data)
    monkeypatch.setattr(template_engine, "_request_agent_report", lambda system_prompt, user_message, client=None, **kwargs:_auto_agent_output_for_payload(payload))

    markdown = report_builder.build_audiovisual_report_markdown(payload)
    required_sections = _expected_required_sections_for_payload(payload)

    assert markdown.startswith("# 视听剖析报告")
    for heading in required_sections:
        assert heading in markdown


def _stub_classification_cache_handoff(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    _stub_handoff_outputs(
        monkeypatch,
        body=_auto_agent_output_for_payload(payload),
        diagram=_svg_structure_stub_response("节庆宣传广告动员结构图"),
    )


def test_generate_outputs_marks_fresh_classification_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _minimal_payload_for_framework("event_brand_ad")
    summary_payload = build_classification_summary_payload(payload)
    classification_result = build_classification_result_payload(
        summary_payload,
        {
            "classification": {
                "type": "event_promo",
                "type_cn": "活动 / 促销广告",
                "confidence": "high",
            },
            "facets": {
                "visual_source": "P",
                "audio_dominance": "M",
            },
            "reasoning_summary": "活动热度和品牌露出共同构成促销导向。",
            "evidence": {
                "title_signals": ["春季促销"],
                "audio_signals": ["音乐持续抬高热度"],
                "visual_signals": ["人群参与和品牌露出反复出现"],
            },
        },
    )
    (tmp_path / "classification_result.json").write_text(json.dumps(classification_result, ensure_ascii=False, indent=2), encoding="utf-8")

    _stub_classification_cache_handoff(
        monkeypatch,
        _with_classification(payload, "event_promo", "活动 / 促销广告"),
    )

    outputs = report_builder.generate_audiovisual_report_outputs(payload, tmp_path, formats=("md",))

    assert outputs["data"]["_classification_result_cache_status"] == "fresh"


def test_generate_outputs_ignores_stale_classification_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _with_child_route(_minimal_payload_for_framework("event_brand_ad"), "event_promo", "活动 / 促销广告")
    stale_payload = _minimal_payload_for_framework("concept_mv")
    stale_summary = build_classification_summary_payload(stale_payload)
    stale_result = build_classification_result_payload(
        stale_summary,
        {
            "classification": {
                "type": "concept_mv",
                "type_cn": "概念 MV",
                "confidence": "high",
            },
            "facets": {
                "visual_source": "D",
                "audio_dominance": "M",
            },
            "reasoning_summary": "概念意象更强。",
            "evidence": {
                "title_signals": ["Concept Video"],
                "audio_signals": ["音乐主导"],
                "visual_signals": ["抽象意象反复出现"],
            },
        },
    )
    (tmp_path / "classification_result.json").write_text(json.dumps(stale_result, ensure_ascii=False, indent=2), encoding="utf-8")

    _stub_classification_cache_handoff(monkeypatch, payload)

    outputs = report_builder.generate_audiovisual_report_outputs(payload, tmp_path, formats=("md",))

    assert outputs["data"]["_classification_result_cache_status"] == "stale"
    assert outputs["data"]["audiovisual_route"]["framework"] == "event_brand_ad"
    assert outputs["data"]["audiovisual_route"]["child_type"] == "event_promo"


def test_generate_outputs_ignores_unverifiable_classification_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _with_child_route(_minimal_payload_for_framework("event_brand_ad"), "event_promo", "活动 / 促销广告")
    unverifiable_result = {
        "classification": {
            "type": "concept_mv",
            "type_cn": "概念 MV",
            "confidence": "high",
        },
        "summary_source": {
            "source_kind": "scene_scores_json",
            "group_count": 6,
        },
        "applied_route": {
            "framework": "concept_mv",
            "route_subtype": "概念 MV",
        },
    }
    (tmp_path / "classification_result.json").write_text(json.dumps(unverifiable_result, ensure_ascii=False, indent=2), encoding="utf-8")

    _stub_classification_cache_handoff(monkeypatch, payload)

    outputs = report_builder.generate_audiovisual_report_outputs(payload, tmp_path, formats=("md",))

    assert outputs["data"]["_classification_result_cache_status"] == "unverifiable"
    assert outputs["data"]["audiovisual_route"]["framework"] == "event_brand_ad"
    assert outputs["data"]["audiovisual_route"]["child_type"] == "event_promo"


def test_generate_outputs_rejects_legacy_framework_only_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _minimal_payload_for_framework("event_brand_ad")
    monkeypatch.setattr(
        template_engine,
        "_request_agent_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should fail before remote request")),
    )

    with pytest.raises(RuntimeError, match="子类型路由"):
        report_builder.generate_audiovisual_report_outputs(payload, tmp_path, formats=("md",))


def test_generate_outputs_refuse_old_framework_fallback_when_raw_prompt_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _with_child_route(_minimal_payload_for_framework("event_brand_ad"), "event_promo", "活动 / 促销广告")

    monkeypatch.setattr(raw_prompt_adapter, "raw_prompt_available_for_data", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        template_engine,
        "_request_agent_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should fail before remote request")),
    )

    with pytest.raises(FileNotFoundError, match="raw prompt"):
        report_builder.generate_audiovisual_report_outputs(payload, tmp_path, formats=("md",))


def _minimal_scene(scene_number: int = 1) -> dict:
    return {
        "scene_number": scene_number,
        "duration_seconds": 1.0,
        "description": f"场景 {scene_number} 的描述，包含人物、城市和光影。",
        "selection": "[USABLE]",
        "weighted_score": 7.0,
        "scores": {
            "aesthetic_beauty": 7.0,
            "credibility": 6.5,
            "impact": 7.0,
            "memorability": 6.5,
            "fun_interest": 6.0,
        },
        "analysis_dimensions": {
            "emotional_effect": 7.0,
            "information_efficiency": 6.5,
            "narrative_function": 7.0,
        },
        "storyboard": {
            "visual_style": "通用风格",
            "camera_movement": "平移",
            "shot_size": "中景",
            "voiceover": "这是一段包含原因和结果的解说词。",
            "onscreen_text": "标题文字",
            "technique": "实拍",
        },
        "story_role": "中段推进",
        "story_function": "信息建立",
    }


def _minimal_payload_for_framework(framework: str) -> dict:
    route_configs = {
        "narrative_trailer": {"visual_axis": "P", "audio_axis": "LM", "reference": "预告片"},
        "event_brand_ad": {"visual_axis": "P", "audio_axis": "M", "reference": "广告"},
        "journey_brand_film": {"visual_axis": "P", "audio_axis": "M", "reference": "品牌短片"},
        "concept_mv": {"visual_axis": "D", "audio_axis": "M", "reference": "概念 MV"},
        "narrative_mix": {"visual_axis": "S", "audio_axis": "LM", "reference": "叙事混剪"},
        "hybrid_music": {"visual_axis": "D", "audio_axis": "M", "reference": "混合音乐"},
        "hybrid_ambient": {"visual_axis": "D", "audio_axis": "E", "reference": "混合氛围"},
        "pure_visual_mix": {"visual_axis": "S", "audio_axis": "N", "reference": "纯视觉"},
        "silent_reality": {"visual_axis": "R", "audio_axis": "N", "reference": "弱听觉记录"},
        "silent_performance": {"visual_axis": "P", "audio_axis": "N", "reference": "默片表演"},
        "technical_explainer": {"visual_axis": "D", "audio_axis": "L", "reference": "技术讲解"},
        "documentary_generic": {"visual_axis": "R", "audio_axis": "L", "reference": "纪实"},
        "hybrid_commentary": {"visual_axis": "S", "audio_axis": "L", "reference": "混合评论"},
        "lecture_performance": {"visual_axis": "P", "audio_axis": "L", "reference": "讲述表演"},
        "infographic_animation": {"visual_axis": "D", "audio_axis": "E", "reference": "信息图动画"},
        "narrative_motion_graphics": {"visual_axis": "D", "audio_axis": "E", "reference": "叙事动效"},
        "pure_motion_graphics": {"visual_axis": "D", "audio_axis": "E", "reference": "纯动效"},
        "meme": {"visual_axis": "S", "audio_axis": "E", "reference": "梗片"},
        "hybrid_meme": {"visual_axis": "S", "audio_axis": "E", "reference": "混合梗"},
        "reality_sfx": {"visual_axis": "R", "audio_axis": "E", "reference": "现实音效"},
        "abstract_sfx": {"visual_axis": "D", "audio_axis": "E", "reference": "抽象音效"},
        "hybrid_narrative": {"visual_axis": "P", "audio_axis": "LM", "reference": "混合叙事"},
        "experimental": {"visual_axis": "H", "audio_axis": "N", "reference": "形式实验"},
    }
    rc = route_configs.get(framework, {"visual_axis": "R", "audio_axis": "L", "reference": "通用"})
    scenes = [_minimal_scene(i) for i in range(1, 7)]
    return {
        "video_id": f"test-{framework}",
        "title": f"Test {framework}",
        "video_title": f"Test {framework}",
        "audiovisual_route": {
            "framework": framework,
            "route_label": framework,
            "route_subtype": "",
            "reference": rc["reference"],
            "visual_axis": rc["visual_axis"],
            "visual_label": "测试",
            "audio_axis": rc["audio_axis"],
            "audio_label": "测试",
            "visual_rationale": "测试",
            "audio_rationale": "测试",
            "voiceover_ratio": 0.3,
            "dual_layer": {"enabled": False},
            "content_profile": {"key": framework},
        },
        "scenes": scenes,
    }


def _child_type_payload(type_key: str) -> dict:
    payload_factories = {
        "concept_mv": lambda: _with_classification(_concept_mv_payload(), "concept_mv", "概念 MV"),
        "performance_mv": lambda: _with_classification(_narrative_performance_payload(), "performance_mv", "表演 MV"),
        "live_session": lambda: _with_classification(_minimal_payload_for_framework("narrative_performance"), "live_session", "现场演出"),
        "narrative_short": lambda: _with_classification(_minimal_payload_for_framework("narrative_performance"), "narrative_short", "叙事短片"),
        "narrative_trailer": lambda: _with_classification(_minimal_payload_for_framework("narrative_trailer"), "narrative_trailer", "预告 / 先导片"),
        "talking_head": lambda: _with_classification(_minimal_payload_for_framework("lecture_performance"), "talking_head", "口播 / 讲述"),
        "documentary_essay": lambda: _with_classification(_minimal_payload_for_framework("documentary_generic"), "documentary_essay", "纪实 / 影像论文"),
        "commentary_remix": lambda: _with_classification(_commentary_mix_payload(), "commentary_remix", "评论向二创"),
        "brand_film": lambda: _with_classification(_minimal_payload_for_framework("journey_brand_film"), "brand_film", "品牌影片"),
        "event_promo": lambda: _with_classification(_minimal_payload_for_framework("event_brand_ad"), "event_promo", "活动 / 促销广告"),
        "explainer": lambda: _with_classification(_minimal_payload_for_framework("technical_explainer"), "explainer", "讲解 / 教学"),
        "infographic_motion": lambda: _with_classification(_minimal_payload_for_framework("infographic_animation"), "infographic_motion", "信息动画"),
        "rhythm_remix": lambda: _with_classification(_mix_music_payload(), "rhythm_remix", "节奏混剪"),
        "mood_montage": lambda: _with_classification(_minimal_payload_for_framework("cinematic_life"), "mood_montage", "情绪蒙太奇"),
        "cinematic_vlog": lambda: _with_classification(_cinematic_life_payload(), "cinematic_vlog", "生活影像 / Vlog"),
        "reality_record": lambda: _with_classification(_minimal_payload_for_framework("documentary_generic"), "reality_record", "现实纪录"),
        "meme_viral": lambda: _with_classification(_minimal_payload_for_framework("meme"), "meme_viral", "梗 / 病毒内容"),
        "motion_graphics": lambda: _with_classification(_minimal_payload_for_framework("pure_motion_graphics"), "motion_graphics", "纯动态图形"),
        "experimental": lambda: _with_classification(_minimal_payload_for_framework("experimental"), "experimental", "形式实验"),
    }
    return payload_factories[type_key]()


@pytest.mark.parametrize("framework", ALL_REPORT_FRAMEWORKS)
def test_template_placeholders_are_resolved(framework: str) -> None:
    payload = _minimal_payload_for_framework(framework)
    template_text = template_engine.load_route_template(framework)
    sections = template_engine._split_template_sections(template_text)
    context = template_engine.build_template_context(payload, payload["audiovisual_route"])
    filled_data = template_engine.fill_template(sections["data"], context)
    filled_tasks = template_engine.fill_template(sections["tasks"], context)
    unresolved = template_engine._UNRESOLVED_PLACEHOLDER_RE.findall(filled_data + filled_tasks)
    assert unresolved == [], f"Unresolved placeholders for {framework}: {unresolved}"


def test_synthesize_audiovisual_report_rejects_missing_required_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _mix_music_payload()

    monkeypatch.setattr(
        template_engine,
        "_request_agent_report",
        lambda system_prompt, user_message, client=None, **kwargs: "## 先看结论\n\n只有一节",
    )

    with pytest.raises(ValueError, match="Missing required sections"):
        template_engine.synthesize_audiovisual_report(payload, payload["audiovisual_route"])


def test_synthesize_audiovisual_report_rejects_raw_prompt_sections_without_scene_evidence() -> None:
    payload = _child_type_payload("brand_film")
    route = payload["audiovisual_route"]
    spec = template_engine.build_audiovisual_body_prompt(payload, route)

    assert spec["source"] == "raw_prompt"

    weak_body = "\n\n".join(
        f"{heading}\n\n这一节只有泛泛总结，没有落到具体镜头，也没有时间依据。"
        for heading in spec["required_sections"]
    )

    with pytest.raises(ValueError, match="Prompt fidelity"):
        template_engine.synthesize_audiovisual_report(payload, route, request_fn=lambda *_: weak_body)


def test_synthesize_audiovisual_report_accepts_raw_prompt_sections_with_scene_evidence_and_anchors() -> None:
    payload = _child_type_payload("brand_film")
    route = payload["audiovisual_route"]
    spec = template_engine.build_audiovisual_body_prompt(payload, route)
    headings = [heading.removeprefix("## ").strip() for heading in spec["required_sections"]]
    stub_body = _raw_heading_stub_output(headings, payload=payload)

    markdown = template_engine.synthesize_audiovisual_report(
        payload,
        route,
        request_fn=lambda *_: stub_body,
    )

    assert "# 视听剖析报告" in markdown
    assert "## 视觉修辞语法" in markdown
