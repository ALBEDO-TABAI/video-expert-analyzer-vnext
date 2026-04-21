"""Tests for the runtime video-type router integration."""

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from classification_summary import build_classification_summary_payload
from video_type_router_runtime import TYPE_LABELS, build_classification_result_payload
import audiovisual.routing.enrich as routing_enrich


def _music_video_payload() -> dict:
    scenes = []
    descriptions = [
        "黑白复古舞台表演近景，成员直视镜头，整体像无声电影画面。",
        "红色剧院群舞中景，镜头快速推进，属于剧情化 MV 的开场表演。",
        "展示柜中的成员全身远景，周围观众围看，是主题片段里的核心意象。",
        "舞台后场化妆间特写，歌词继续推进角色状态和情绪。",
    ]
    voiceovers = [
        "Why you think that 'bout nude",
        "Think outside the box",
        "Hello my name is 예삐 예삐요",
        "Self-made woman",
    ]
    for index, (description, voiceover) in enumerate(zip(descriptions, voiceovers), start=1):
        scenes.append(
            {
                "scene_number": index,
                "description": description,
                "type_classification": "TYPE-B Narrative",
                "weighted_score": 7.8,
                "scores": {
                    "aesthetic_beauty": 8,
                    "credibility": 6,
                    "impact": 8,
                    "memorability": 7,
                    "fun_interest": 6,
                },
                "storyboard": {
                    "voiceover": voiceover,
                    "onscreen_text": "",
                    "shot_size": "中近景",
                    "visual_style": "复古舞台 / 黑白高对比",
                    "technique": "表演拍摄",
                    "camera_movement": "稳定前推",
                },
            }
        )
    return {
        "video_id": "nxde-test",
        "title": "(여자)아이들((G)I-DLE) - 'Nxde' Official Music Video",
        "video_title": "(여자)아이들((G)I-DLE) - 'Nxde' Official Music Video",
        "scenes": scenes,
    }


def test_build_classification_result_payload_maps_child_route_to_report_route() -> None:
    summary_payload = build_classification_summary_payload(_music_video_payload(), target_groups=4)
    llm_result = {
        "classification": {
            "type": "performance_mv",
            "type_cn": "表演 MV",
            "confidence": "high",
        },
        "facets": {
            "visual_source": "P",
            "audio_dominance": "M",
        },
        "reasoning_summary": "标题和画面都指向 MV，且主体是舞台化表演。",
        "evidence": {
            "title_signals": ["Official Music Video"],
            "audio_signals": ["旁白基本都是歌词"],
            "visual_signals": ["主体是编排表演和群舞"],
        },
    }

    result = build_classification_result_payload(summary_payload, llm_result)

    assert result["classification"]["type"] == "performance_mv"
    assert result["applied_route"]["framework"] == "narrative_performance"
    assert result["applied_route"]["route_subtype"] == "表演 MV"
    assert result["applied_route"]["child_type"] == "performance_mv"
    assert result["applied_route"]["child_type_cn"] == "表演 MV"
    assert result["applied_route"]["content_profile"]["key"] == "music_video"
    assert result["summary_source"]["summary_hash"]


def test_enrich_audiovisual_layers_prefers_classification_result(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _music_video_payload()
    summary_payload = build_classification_summary_payload(payload, target_groups=4)
    payload["classification_result"] = build_classification_result_payload(
        summary_payload,
        {
            "classification": {
                "type": "concept_mv",
                "type_cn": "概念 MV",
                "confidence": "high",
            },
            "facets": {
                "visual_source": "P",
                "audio_dominance": "M",
            },
            "reasoning_summary": "概念场景明显多于单一表演空间。",
            "evidence": {
                "title_signals": ["Official Music Video"],
                "audio_signals": ["歌词贯穿全片"],
                "visual_signals": ["多个概念化布景反复切换"],
            },
        },
    )

    monkeypatch.setattr(
        routing_enrich,
        "infer_content_profile",
        lambda *_args, **_kwargs: pytest.fail("external classification should bypass legacy content profile inference"),
    )
    monkeypatch.setattr(
        routing_enrich,
        "infer_audiovisual_route",
        lambda *_args, **_kwargs: pytest.fail("external classification should bypass legacy route inference"),
    )

    enriched = routing_enrich.enrich_audiovisual_layers(payload)

    assert enriched["audiovisual_route"]["framework"] == "concept_mv"
    assert enriched["audiovisual_route"]["child_type"] == "concept_mv"
    assert enriched["audiovisual_route"]["child_type_cn"] == "概念 MV"
    assert enriched["content_profile"]["key"] == "music_video"


def test_classification_result_summary_hash_is_stable_for_same_summary() -> None:
    summary_payload = build_classification_summary_payload(_music_video_payload(), target_groups=4)
    llm_result = {
        "classification": {
            "type": "performance_mv",
            "type_cn": "表演 MV",
            "confidence": "high",
        },
        "facets": {
            "visual_source": "P",
            "audio_dominance": "M",
        },
        "reasoning_summary": "标题和画面都指向 MV，且主体是舞台化表演。",
        "evidence": {
            "title_signals": ["Official Music Video"],
            "audio_signals": ["旁白基本都是歌词"],
            "visual_signals": ["主体是编排表演和群舞"],
        },
    }

    first = build_classification_result_payload(summary_payload, llm_result)
    second = build_classification_result_payload(summary_payload, llm_result)

    assert first["summary_source"]["summary_hash"] == second["summary_source"]["summary_hash"]


def test_child_router_type_catalog_stays_at_19_results() -> None:
    assert TYPE_LABELS == {
        "concept_mv": "概念 MV",
        "performance_mv": "表演 MV",
        "live_session": "现场演出",
        "narrative_short": "叙事短片",
        "narrative_trailer": "预告 / 先导片",
        "talking_head": "口播 / 讲述",
        "documentary_essay": "纪实 / 影像论文",
        "commentary_remix": "评论向二创",
        "brand_film": "品牌影片",
        "event_promo": "活动 / 促销广告",
        "explainer": "讲解 / 教学",
        "infographic_motion": "信息动画",
        "rhythm_remix": "节奏混剪",
        "mood_montage": "情绪蒙太奇",
        "cinematic_vlog": "生活影像 / Vlog",
        "reality_record": "现实纪录",
        "meme_viral": "梗 / 病毒内容",
        "motion_graphics": "纯动态图形",
        "experimental": "形式实验",
    }
