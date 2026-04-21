#!/usr/bin/env python3
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List

try:
    from storyboard_generator import ANALYSIS_FIELD_LABELS, scene_missing_analysis_fields
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from storyboard_generator import ANALYSIS_FIELD_LABELS, scene_missing_analysis_fields


def _safe_text(value: object, fallback: str = "未填写") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text or text.upper().startswith("TODO"):
        return fallback
    return text


def _safe_score(value: object) -> str:
    if isinstance(value, (int, float)) and value > 0:
        return f"{float(value):.2f}" if isinstance(value, float) else str(value)
    return "未填写"


def _scene_report_name(scene_number: int) -> str:
    return f"Scene-{scene_number:03d}.md"


def _format_missing_fields(missing_fields: List[str]) -> str:
    if not missing_fields:
        return "无"
    labels = [ANALYSIS_FIELD_LABELS.get(name, name) for name in missing_fields]
    return "、".join(labels)


def map_score_to_rating(score: float) -> str:
    """将分数映射为定性评价"""
    if score >= 8.5:
        return "顶尖"
    if score >= 7.5:
        return "优秀"
    if score >= 6.5:
        return "良好"
    if score >= 5.0:
        return "一般"
    return "较差"


def calculate_overall_dimensions(scenes: List[Dict]) -> Dict[str, float]:
    """计算 5 个核心维度的全片平均分"""
    dims = ["aesthetic_beauty", "credibility", "impact", "memorability", "fun_interest"]
    totals = {d: 0.0 for d in dims}
    counts = {d: 0 for d in dims}

    for scene in scenes:
        scores = scene.get("scores", {})
        for d in dims:
            val = scores.get(d)
            if isinstance(val, (int, float)) and val > 0:
                totals[d] += float(val)
                counts[d] += 1

    return {d: (totals[d] / counts[d] if counts[d] > 0 else 0.0) for d in dims}




def _dominant_type(scenes: List[Dict]) -> str:
    type_names = [s.get("type_classification", "").split()[0] for s in scenes if s.get("type_classification")]
    return Counter(type_names).most_common(1)[0][0] if type_names else "Unknown"


def infer_video_type(scenes: List[Dict]) -> str:
    return {
        "TYPE-A": "高能短视频",
        "TYPE-B": "剧情/叙事",
        "TYPE-C": "氛围/审美向短片",
        "TYPE-D": "广告/展示",
    }.get(_dominant_type(scenes), "其他")


def infer_core_theme(scenes: List[Dict], dim_avgs: Dict[str, float]) -> str:
    top_type = _dominant_type(scenes)
    best_dim = max(dim_avgs.items(), key=lambda x: x[1])[0] if dim_avgs else ""
    theme_map = {
        "TYPE-A": "通过高冲击力画面快速抓住注意力，突出内容记忆点",
        "TYPE-B": "围绕人物情绪与叙事推进建立观众共鸣",
        "TYPE-C": "以画面氛围与视觉质感传递情绪和审美",
        "TYPE-D": "围绕卖点展示与价值传达服务转化目标",
    }
    dim_suffix = {
        "aesthetic_beauty": "，并强化整体视觉美感",
        "credibility": "，重点突出情感真实度",
        "impact": "，强调瞬时冲击和注意力抓取",
        "memorability": "，突出可复用的核心记忆点",
        "fun_interest": "，增强观看趣味与传播意愿",
    }
    return theme_map.get(top_type, "围绕核心内容建立清晰表达") + dim_suffix.get(best_dim, "")


def infer_target_audience(scenes: List[Dict]) -> str:
    return {
        "TYPE-A": "短视频平台用户，以及偏好强节奏开场和高能内容的观众",
        "TYPE-B": "关注剧情表达、人物关系和情感共鸣的观众",
        "TYPE-C": "偏好审美氛围、影像质感和情绪表达的观众",
        "TYPE-D": "潜在消费者，以及关注产品价值和功能表达的人群",
    }.get(_dominant_type(scenes), "泛内容消费人群")


def infer_emotional_tone(scenes: List[Dict], dim_avgs: Dict[str, float]) -> str:
    top_type = _dominant_type(scenes)
    best_dim = max(dim_avgs.items(), key=lambda x: x[1])[0] if dim_avgs else ""
    if top_type == "TYPE-B" and best_dim == "credibility":
        return "温馨/走心"
    if top_type == "TYPE-A" or best_dim == "impact":
        return "高能/励志"
    if top_type == "TYPE-C" or best_dim == "aesthetic_beauty":
        return "氛围/抒情"
    if best_dim == "fun_interest":
        return "轻松/有趣"
    return "理性/克制"


def infer_commercial_intent(scenes: List[Dict]) -> str:
    top_type = _dominant_type(scenes)
    if top_type == "TYPE-D":
        return "存在明确商业转化诉求，适合承接产品卖点、品牌表达或功能说明。"
    return "当前素材以内容表达为主，无明显硬广意图，更适合作为传播或叙事素材。"


def find_best_hook(scenes: List[Dict]) -> str:
    """推荐最适合作为开场 Hook 的场景 (Impact + Memorability)"""
    best_scene = None
    max_val = -1.0

    for scene in scenes:
        scores = scene.get("scores", {})
        imp = float(scores.get("impact", 0))
        mem = float(scores.get("memorability", 0))
        val = imp + mem
        if val > max_val:
            max_val = val
            best_scene = scene

    if not best_scene:
        return "未找到合适场景"

    desc = _safe_text(best_scene.get("description"))[:50] + "..."
    scores = best_scene.get("scores", {})
    return f"Scene {best_scene.get('scene_number'):03d} (Impact: {scores.get('impact')}, Memorability: {scores.get('memorability')}, 总分: {max_val:.1f}) - {desc}"


def find_best_emotion(scenes: List[Dict]) -> str:
    """推荐最能建立共情的场景 (Credibility)"""
    best_scene = None
    max_val = -1.0

    for scene in scenes:
        scores = scene.get("scores", {})
        val = float(scores.get("credibility", 0))
        if val > max_val:
            max_val = val
            best_scene = scene

    if not best_scene:
        return "未找到合适场景"

    desc = _safe_text(best_scene.get("description"))[:50] + "..."
    return f"Scene {best_scene.get('scene_number'):03d} (Credibility: {best_scene.get('scores', {}).get('credibility')}) - {desc}"


def find_best_visual(scenes: List[Dict]) -> str:
    """推荐视觉最精美的场景 (Aesthetics)"""
    best_scene = None
    max_val = -1.0

    for scene in scenes:
        scores = scene.get("scores", {})
        val = float(scores.get("aesthetic_beauty", 0))
        if val > max_val:
            max_val = val
            best_scene = scene

    if not best_scene:
        return "未找到合适场景"

    desc = _safe_text(best_scene.get("description"))[:50] + "..."
    return f"Scene {best_scene.get('scene_number'):03d} (Aesthetic: {best_scene.get('scores', {}).get('aesthetic_beauty')}) - {desc}"


def generate_murch_suggestions(dim_avgs: Dict[str, float]) -> str:
    """基于 Walter Murch 六法则给出改进建议"""
    # 建议池
    suggestions_map = {
        "credibility": "加强情感真实性，避免表演痕迹过重 (Walter Murch: Emotion 第一原则)",
        "impact": "增强视觉冲击力，考虑更有张力的构图或显著性对比",
        "memorability": "添加独特视觉符号或核心金句，提升观众记忆留存 (Von Restorff 效应)",
        "aesthetic_beauty": "优化光影质感与色彩平衡，提升画面整体电影感",
        "fun_interest": "增加剪辑节奏变化或反转点，提升观看趣味性与参与感"
    }

    # 按分数排序，找出最低的 2 个
    sorted_dims = sorted(dim_avgs.items(), key=lambda x: x[1])
    low_dims = [d for d, s in sorted_dims[:2] if s > 0]

    if not low_dims:
        return "整体表现均衡，建议继续保持当前风格。"

    lines = ["基于 Walter Murch 六法则分析，当前作品在以下方面有提升空间："]
    for i, d in enumerate(low_dims, 1):
        label = {"aesthetic_beauty": "美感", "credibility": "可信度", "impact": "冲击力", "memorability": "记忆度", "fun_interest": "趣味性"}.get(d, d)
        lines.append(f"{i}. **{label}层面** ({dim_avgs[d]:.2f}): {suggestions_map.get(d)}")

    return "\n".join(lines)


def generate_verdict(dim_avgs: Dict[str, float], scenes: List[Dict]) -> Dict[str, str]:
    """生成最终鉴定结论"""
    avg_score = sum(dim_avgs.values()) / len(dim_avgs) if dim_avgs else 0.0

    # 统计筛选建议
    selections = [s.get("selection", "") for s in scenes]
    must_keep_count = sum(1 for s in selections if "MUST KEEP" in s.upper())
    must_keep_ratio = must_keep_count / len(scenes) if scenes else 0

    # 统计类型分布
    types = [s.get("type_classification", "") for s in scenes]
    type_counts = {}
    for t in types:
        base_type = t.split()[0] if t else "Unknown"
        type_counts[base_type] = type_counts.get(base_type, 0) + 1

    # 1. 是否值得保留
    if avg_score >= 7.5 or must_keep_ratio >= 0.3:
        keep = f"✅ **极力推荐** (综合得分 {avg_score:.2f}, MUST KEEP 占比 {must_keep_ratio*100:.1f}%)"
    elif avg_score >= 6.5:
        keep = f"✅ **建议保留** (综合得分 {avg_score:.2f})"
    else:
        keep = f"⚠️ **谨慎保留** (综合得分 {avg_score:.2f}, 核心长板不足)"

    # 2. 推荐使用场景
    top_type = max(type_counts.items(), key=lambda x: x[1])[0] if type_counts else "N/A"
    usage_map = {
        "TYPE-A": "适合作为社交媒体短视频、投放广告或开场 Hook 片段",
        "TYPE-B": "适合作为长视频叙事主体、情感铺垫或剧情片段",
        "TYPE-C": "适合作为转场、空镜或氛围渲染素材",
        "TYPE-D": "适合作为产品展示、功能说明或商业演示"
    }
    usage = usage_map.get(top_type, "根据素材实际质量灵活调整")

    # 3. 二次创作建议
    best_dim = max(dim_avgs.items(), key=lambda x: x[1])[0] if dim_avgs else ""
    creation_map = {
        "aesthetic_beauty": "建议提取高画质帧作为封面或静态海报素材",
        "credibility": "建议保留完整长镜头，以维持情感连贯性",
        "impact": "建议提取 5-15s 高能片段，配合节奏感强的音乐进行混剪",
        "memorability": "建议围绕该场景的核心金句或符号进行二次解说",
        "fun_interest": "建议保留趣味互动部分，增加字幕特效强化笑点"
    }
    creation = creation_map.get(best_dim, "建议结合高分片段进行针对性剪辑")

    return {
        "keep": keep,
        "usage": usage,
        "creation": creation,
        "avg_score": f"{avg_score:.2f}"
    }


def build_scene_report_markdown(scene: Dict) -> str:
    scene_number = scene.get("scene_number", 0)
    storyboard = scene.get("storyboard", {})
    scores = scene.get("scores", {})
    motion_analysis = scene.get("motion_analysis", {})
    missing_fields = scene_missing_analysis_fields(scene)
    status_text = "已完成" if not missing_fields else "待补全"

    return f"""# Scene {scene_number:03d}

- 状态：{status_text}
- 缺失项：{_format_missing_fields(missing_fields)}
- 时间戳：{_safe_text(storyboard.get("timestamp") or scene.get("timestamp_range"))}
- 片段文件：`{_safe_text(scene.get("file_path"), scene.get("filename", ""))}`
- 截图文件：`{_safe_text(storyboard.get("screenshot_path") or scene.get("frame_path"))}`

## 画面内容

{_safe_text(scene.get("description"))}

## 类型与筛选

- 类型分类：{_safe_text(scene.get("type_classification"))}
- 加权总分：{_safe_score(scene.get("weighted_score"))}
- 筛选建议：{_safe_text(scene.get("selection"))}

## 五维评分

| 维度 | 分数 |
|------|------|
| 美感 | {_safe_score(scores.get("aesthetic_beauty"))} |
| 可信度 | {_safe_score(scores.get("credibility"))} |
| 冲击力 | {_safe_score(scores.get("impact"))} |
| 记忆度 | {_safe_score(scores.get("memorability"))} |
| 趣味度 | {_safe_score(scores.get("fun_interest"))} |

## 分镜信息

- 景别：{_safe_text(storyboard.get("shot_size"))}
- 灯光：{_safe_text(storyboard.get("lighting"))}
- 运镜：{_safe_text(storyboard.get("camera_movement"))}
- 画风：{_safe_text(storyboard.get("visual_style"))}
- 手法：{_safe_text(storyboard.get("technique"))}
- 旁白：{_safe_text(storyboard.get("voiceover"), "无可对齐文本")}
- 运镜依据：{_safe_text(storyboard.get("camera_movement_rationale") or motion_analysis.get("rationale"), "未提供")}

## 筛选理由

{_safe_text(scene.get("selection_reasoning"))}

## 剪辑建议

{_safe_text(scene.get("edit_suggestion"))}
"""




def _replace_metadata_todos(content: str, scenes: List[Dict], dim_avgs: Dict[str, float]) -> str:
    replacements = {
        "- **视频类型**: TODO (广告/剧情/Vlog/教程/其他)": f"- **视频类型**: {infer_video_type(scenes)}",
        "- **核心主题**: TODO ": f"- **核心主题**: {infer_core_theme(scenes, dim_avgs)}",
        "- **目标受众**: TODO": f"- **目标受众**: {infer_target_audience(scenes)}",
        "- **情感基调**: TODO (励志/搞笑/温馨/悬疑/其他)": f"- **情感基调**: {infer_emotional_tone(scenes, dim_avgs)}",
        "- **商业意图**: TODO (如有)": f"- **商业意图**: {infer_commercial_intent(scenes)}",
    }
    for old, new in replacements.items():
        content = content.replace(old, new)
    return content


def write_scene_reports(data: Dict, video_dir: Path) -> Dict:
    scene_reports_dir = video_dir / "scene_reports"
    scene_reports_dir.mkdir(exist_ok=True)

    scene_entries: List[Dict] = []
    incomplete: List[Dict] = []
    for scene in data.get("scenes", []):
        scene_number = int(scene.get("scene_number", 0))
        report_path = scene_reports_dir / _scene_report_name(scene_number)
        report_path.write_text(build_scene_report_markdown(scene), encoding="utf-8")
        missing_fields = scene_missing_analysis_fields(scene)
        scene_entry = {
            "scene_number": scene_number,
            "path": report_path,
            "missing_fields": missing_fields,
            "complete": not missing_fields,
        }
        scene_entries.append(scene_entry)
        if missing_fields:
            incomplete.append(scene_entry)

    return {
        "scene_reports_dir": scene_reports_dir,
        "scene_entries": scene_entries,
        "complete_count": sum(1 for item in scene_entries if item["complete"]),
        "incomplete_entries": incomplete,
    }


def write_detailed_report(data: Dict, video_dir: Path, scene_report_info: Dict, *, strict: bool) -> Path:
    video_id = data.get("video_id", "unknown")
    detail_path = video_dir / f"{video_id}_detailed_analysis.md"
    scene_entries = scene_report_info["scene_entries"]
    scenes = data.get("scenes", [])

    # 加载模板
    template_path = Path(__file__).parent.parent / "templates" / "detailed_report_template.md"
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
    else:
        # 回退逻辑：如果模板不存在，使用简单的拼接内容
        return _write_simple_fallback_report(data, video_dir, scene_report_info, strict)

    # 1. 基础占位符替换
    content = template.format(
        video_id=video_id,
        url=data.get("url", "N/A"),
        analysis_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        video_size_mb=data.get("video_size_mb", 0),
        scene_count=len(scenes),
        transcription_language=data.get("transcription", {}).get("language", "N/A"),
        transcription_segments=len(data.get("transcription", {}).get("segments", [])),
        transcript_text=data.get("transcript_text", "无转录文本"),
        scene_list_table=_build_scene_summary_table(data),
        detailed_scene_evaluations="{detailed_scene_evaluations}",  # 占位符供后续替换
        best_threshold=data.get("best_threshold", 7.5),
        best_shots_table=_build_best_shots_table(data),
        video_output_dir_name=video_dir.name
    )

    # 2. 自动化 TODO 填充 (v2.2.1 增强逻辑)
    if scenes:
        dim_avgs = calculate_overall_dimensions(scenes)
        verdict = generate_verdict(dim_avgs, scenes)
        content = _replace_metadata_todos(content, scenes, dim_avgs)

        replacements = {
            "TODO: 基于 IMPACT 和 MEMORABILITY 得分，推荐最适合作为开场 Hook 的场景": find_best_hook(scenes),
            "TODO: 基于 CREDIBILITY 得分，推荐最能建立共情的场景": find_best_emotion(scenes),
            "TODO: 基于 AESTHETICS 得分，推荐视觉最精美的场景": find_best_visual(scenes),
            "TODO: 基于 Walter Murch 法则提出具体的改进建议": generate_murch_suggestions(dim_avgs),
            "| 整体美感 | TODO | TODO |": f"| 整体美感 | {dim_avgs['aesthetic_beauty']:.2f} | {map_score_to_rating(dim_avgs['aesthetic_beauty'])} |",
            "| 叙事连贯性 | TODO | TODO |": f"| 叙事连贯性 | {(dim_avgs['credibility'] + dim_avgs['memorability']) / 2:.2f} | {map_score_to_rating((dim_avgs['credibility'] + dim_avgs['memorability']) / 2)} |",
            "| 情感共鸣度 | TODO | TODO |": f"| 情感共鸣度 | {dim_avgs['credibility']:.2f} | {map_score_to_rating(dim_avgs['credibility'])} |",
            "| 商业转化力 | TODO | TODO (如适用) |": f"| 商业转化力 | {(dim_avgs['memorability'] + dim_avgs['impact']) / 2:.2f} | {map_score_to_rating((dim_avgs['memorability'] + dim_avgs['impact']) / 2)} |",
            "| 病毒传播潜力 | TODO | TODO |": f"| 病毒传播潜力 | {(dim_avgs['impact'] + dim_avgs['fun_interest']) / 2:.2f} | {map_score_to_rating((dim_avgs['impact'] + dim_avgs['fun_interest']) / 2)} |",
            "| **综合得分** | **TODO** | - |": f"| **综合得分** | **{verdict['avg_score']}** | - |",
            "> TODO: 总结视频的核心优势和亮点": "> 基于数据分析，视频最强维度是 **" + {"aesthetic_beauty": "视觉美感", "credibility": "情感真实度", "impact": "视觉冲击力", "memorability": "记忆留存度", "fun_interest": "娱乐趣味性"}.get(max(dim_avgs.items(), key=lambda x: x[1])[0], "综合表现") + "**。",
            "| **是否值得保留** | TODO |": f"| **是否值得保留** | {verdict['keep']} |",
            "| **推荐使用场景** | TODO |": f"| **推荐使用场景** | {verdict['usage']} |",
            "| **二次创作建议** | TODO |": f"| **二次创作建议** | {verdict['creation']} |",
            "完善本报告的 TODO 部分": "复核本报告的自动分析内容",
        }

        for old, new in replacements.items():
            content = content.replace(old, new)

    # 2.5 转录失败警告注入
    warnings = data.get("warnings", [])
    transcription_status = data.get("transcription", {}).get("status", "")
    if transcription_status == "failed" or any("transcription_failed" in w for w in warnings):
        warning_block = "\n\n> **⚠️ 转录警告**：本视频的所有自动转录方式（B站API / 内嵌字幕 / OCR / FunASR）均未成功。以下分析仅基于画面帧，缺少字幕和语音上下文，部分结论（如叙事连贯性、情感表达）可能不够完整。\n"
        # 插入到报告正文最前面（模板标题之后）
        first_newline = content.find("\n", content.find("\n") + 1)
        if first_newline > 0:
            content = content[:first_newline] + warning_block + content[first_newline:]
        else:
            content = warning_block + content

    # 3. 拼接逐镜头分析正文
    scene_texts = []
    for entry in scene_entries:
        scene_texts.append(entry["path"].read_text(encoding="utf-8").strip())

    if "{detailed_scene_evaluations}" in content:
        content = content.replace("{detailed_scene_evaluations}", "\n\n---\n\n".join(scene_texts))
    else:
        content += "\n\n---\n\n## 📝 逐镜头分析正文\n\n" + "\n\n---\n\n".join(scene_texts)

    # 4. 写入报告
    detail_path.write_text(content.strip() + "\n", encoding="utf-8")
    return detail_path


def _write_simple_fallback_report(data: Dict, video_dir: Path, scene_report_info: Dict, strict: bool) -> Path:
    video_id = data.get("video_id", "unknown")
    detail_path = video_dir / f"{video_id}_detailed_analysis.md"
    scene_entries = scene_report_info["scene_entries"]
    incomplete_entries = scene_report_info["incomplete_entries"]
    scenes = data.get("scenes", [])
    complete_count = scene_report_info["complete_count"]

    status_text = "正式报告" if not incomplete_entries else "进度报告（未完成）"
    lines: List[str] = [
        f"# 🎬 视频逐镜头详细分析 - {status_text}",
        "",
        "## 📋 概览",
        "",
        f"- **视频 ID**: {video_id}",
        f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **总场景数**: {len(scenes)}",
        f"- **已完成场景**: {complete_count}",
        f"- **未完成场景**: {len(incomplete_entries)}",
        "",
    ]
    # ... (原有逻辑)
    detail_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return detail_path


def _build_scene_summary_table(data: Dict) -> str:
    lines = [
        "| 场景编号 | 类型 | 加权得分 | 筛选建议 | 片段路径 |",
        "|---------|------|---------|---------|---------|",
    ]
    for scene in data.get("scenes", []):
        lines.append(
            f"| Scene {scene.get('scene_number'):03d} | {_safe_text(scene.get('type_classification'))} | {_safe_score(scene.get('weighted_score'))} | {_safe_text(scene.get('selection'))} | `{_safe_text(scene.get('file_path'), scene.get('filename', ''))}` |"
        )
    return "\n".join(lines)


def _build_best_shots_table(data: Dict) -> str:
    best_scenes = [s for s in data.get("scenes", []) if "KEEP" in s.get("selection", "").upper() or s.get("weighted_score", 0) >= data.get("best_threshold", 7.5)]
    if not best_scenes:
        return "*暂无入选片段*"

    lines = [
        "| 场景编号 | 最终得分 | 筛选理由 |",
        "|---------|---------|---------|",
    ]
    for s in best_scenes:
        lines.append(f"| Scene {s.get('scene_number'):03d} | {s.get('weighted_score')} | {s.get('selection_reasoning')} |")
    return "\n".join(lines)


# 辅助工具
from collections import Counter



def generate_detailed_analysis_outputs(data: Dict, video_dir: Path, *, strict: bool) -> Dict:
    scene_report_info = write_scene_reports(data, video_dir)
    detail_path = write_detailed_report(data, video_dir, scene_report_info, strict=strict)
    return {
        "detailed_report_path": detail_path,
        **scene_report_info,
    }
