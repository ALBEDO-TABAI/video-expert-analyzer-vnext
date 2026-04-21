#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, List, Sequence

from audiovisual.shared import _analysis_rows, _onscreen_text, _safe_text, _scene_desc, _voiceover


_DROP_SECTION_PREFIXES = (
    "THEORETICAL ANCHORS",
    "INPUT FORMAT",
    "REFERENCES",
)
_MODULE_RE = re.compile(r"^### MODULE\s+\d+\s+[—-]\s*(.+)$", re.MULTILINE)
_SCENE_EVIDENCE_RE = re.compile(r"(具体场景编号|场景编号或时间戳|具体场景编号或\s*时间戳|时间戳作为依据)")
_SUBSECTION_RE = re.compile(r"^####\s+\d+(?:\.\d+)?\s+(.+)$", re.MULTILINE)
_ANCHOR_SPLIT_RE = re.compile(r"[：:、,，/／\s]+|与|和|及|并|vs\.?|→|↔")
_ANCHOR_STOP_WORDS = {
    "分析",
    "拆解",
    "系统",
    "结构",
    "识别",
    "评估",
    "判定",
    "序列",
    "映射",
    "关系",
    "逻辑",
    "路径",
    "设计",
    "功能",
    "策略",
    "类型",
    "模式",
    "机制",
    "效果",
}

_RAW_PROMPT_ALIASES: Dict[str, str] = {
    "commentary_remix": "video-essay-storyboard-analysis-prompt.md",
    "documentary_essay": "documentary-storyboard-analysis-prompt.md",
    "brand_film": "ad-brand-campaign-storyboard-analysis-prompt.md",
    "narrative_trailer": "trailer-analysis-prompt.md",
}

_PATTERN_SUFFIX = "-storyboard-analysis-prompt.md"


def _prompts_root(prompts_dir: Path | None = None) -> Path:
    return prompts_dir or Path(__file__).resolve().parents[3] / "chart" / "file-Prompt"


def _build_prompt_type_map(prompts_dir: Path | None = None) -> Dict[str, str]:
    """Combine alias map with auto-discovered pattern-based prompt files.

    Files matching `<slug>-storyboard-analysis-prompt.md` are exposed as
    type key `<slug with - replaced by _>`. Aliases override discovery.
    """
    root = _prompts_root(prompts_dir)
    discovered: Dict[str, str] = {}
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            name = entry.name
            if not name.endswith(_PATTERN_SUFFIX):
                continue
            slug = name[: -len(_PATTERN_SUFFIX)]
            type_key = slug.replace("-", "_")
            discovered.setdefault(type_key, name)
    discovered.update(_RAW_PROMPT_ALIASES)
    return discovered


def available_raw_prompt_types(prompts_dir: Path | None = None) -> List[str]:
    return sorted(_build_prompt_type_map(prompts_dir).keys())


def _resolve_type_key(data: Dict[str, Any], route: Dict[str, Any]) -> str:
    classification_result = data.get("classification_result") or {}
    if isinstance(classification_result, dict):
        classification = classification_result.get("classification") or {}
        if isinstance(classification, dict):
            type_key = _safe_text(classification.get("type"))
            if type_key:
                return type_key

    child_type = _safe_text(route.get("child_type"))
    if child_type:
        return child_type
    return ""


def resolve_raw_prompt_path_for_data(
    data: Dict[str, Any],
    route: Dict[str, Any],
    prompts_dir: Path | None = None,
) -> Path | None:
    type_key = _resolve_type_key(data, route)
    prompt_name = _build_prompt_type_map(prompts_dir).get(type_key)
    if not prompt_name:
        return None
    prompt_path = _prompts_root(prompts_dir) / prompt_name
    return prompt_path if prompt_path.exists() else None


def raw_prompt_available_for_data(
    data: Dict[str, Any],
    route: Dict[str, Any],
    prompts_dir: Path | None = None,
) -> bool:
    return resolve_raw_prompt_path_for_data(data, route, prompts_dir=prompts_dir) is not None


def _strip_low_value_sections(prompt_text: str) -> str:
    kept: List[str] = []
    dropping = False
    for line in prompt_text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            dropping = any(heading.startswith(prefix) for prefix in _DROP_SECTION_PREFIXES)
        if not dropping:
            kept.append(line)
    return "\n".join(kept).strip()


def load_sanitized_raw_prompt_for_data(
    data: Dict[str, Any],
    route: Dict[str, Any],
    prompts_dir: Path | None = None,
) -> str:
    prompt_path = resolve_raw_prompt_path_for_data(data, route, prompts_dir=prompts_dir)
    if prompt_path is None:
        type_key = _resolve_type_key(data, route) or "unknown"
        available = available_raw_prompt_types(prompts_dir)
        raise FileNotFoundError(
            f"No raw prompt mapping for route type '{type_key}'. "
            f"Available types ({len(available)}): {', '.join(available)}. "
            f"To add a new type, drop a file named '<type>-storyboard-analysis-prompt.md' "
            f"into {_prompts_root(prompts_dir)} or extend _RAW_PROMPT_ALIASES."
        )
    prompt_text = prompt_path.read_text(encoding="utf-8")
    return _strip_low_value_sections(prompt_text)


def extract_required_sections_from_raw_prompt(prompt_text: str) -> List[str]:
    sections: List[str] = []
    for match in _MODULE_RE.finditer(prompt_text):
        heading = match.group(1).strip()
        heading = re.sub(r"\s*[（(].*?[）)]\s*$", "", heading).strip()
        if heading and heading not in sections:
            sections.append(heading)
    return sections


def extract_prompt_fidelity_rules(prompt_text: str) -> Dict[str, Any]:
    return {
        "require_scene_evidence_per_section": bool(_SCENE_EVIDENCE_RE.search(prompt_text)),
        "section_anchor_terms": extract_module_anchor_terms(prompt_text),
        "required_subsections": extract_required_subsections_from_raw_prompt(prompt_text),
        "min_chars_per_section": _env_int("AUDIOVISUAL_MIN_CHARS_PER_SECTION", 700),
        "min_subsection_chars": _env_int("AUDIOVISUAL_MIN_CHARS_PER_SUBSECTION", 180),
        "min_scene_evidence_per_section": _env_int("AUDIOVISUAL_MIN_SCENE_EVIDENCE_PER_SECTION", 3),
    }


def _env_int(name: str, default: int) -> int:
    import os

    try:
        return max(0, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def extract_required_subsections_from_raw_prompt(prompt_text: str) -> Dict[str, List[str]]:
    """Return module_heading -> list of subsection titles (without numeric prefix).

    Module headings come from lines like `### MODULE 1 — 视觉修辞语法`.
    Subsection titles are extracted from lines like `#### 1.1 景别分布与说服功能`
    scoped to their parent module block.
    """
    subsections: Dict[str, List[str]] = {}
    matches = list(_MODULE_RE.finditer(prompt_text))
    for index, match in enumerate(matches):
        heading = _normalize_module_heading(match.group(1))
        block_start = match.end()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(prompt_text)
        block = prompt_text[block_start:block_end]
        titles: List[str] = []
        for subsection in _SUBSECTION_RE.findall(block):
            title = re.sub(r"\s*[（(].*?[）)]\s*$", "", subsection).strip()
            if title and title not in titles:
                titles.append(title)
        if heading:
            subsections[heading] = titles
    return subsections


def _normalize_module_heading(heading: str) -> str:
    return re.sub(r"\s*[（(].*?[）)]\s*$", "", heading).strip()


def _anchor_terms_from_subheading(subheading: str) -> List[str]:
    normalized = re.sub(r"\s*[（(].*?[）)]", "", subheading).strip()
    parts = [part.strip(" -—") for part in _ANCHOR_SPLIT_RE.split(normalized) if part.strip(" -—")]
    terms: List[str] = []
    for part in parts:
        if len(part) < 2:
            continue
        if part in _ANCHOR_STOP_WORDS:
            continue
        if part not in terms:
            terms.append(part)
    return terms


def extract_module_anchor_terms(prompt_text: str) -> Dict[str, List[str]]:
    anchors: Dict[str, List[str]] = {}
    matches = list(_MODULE_RE.finditer(prompt_text))
    for index, match in enumerate(matches):
        heading = _normalize_module_heading(match.group(1))
        block_start = match.end()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(prompt_text)
        block = prompt_text[block_start:block_end]
        terms: List[str] = []
        for subsection in _SUBSECTION_RE.findall(block):
            for term in _anchor_terms_from_subheading(subsection):
                if term not in terms:
                    terms.append(term)
        if heading and terms:
            anchors[heading] = terms
    return anchors


def _scene_packet_lines(rows: Sequence[Dict[str, Any]], compact: bool = False) -> List[str]:
    lines: List[str] = []
    for scene in rows:
        scene_number = int(scene.get("scene_number", 0))
        timestamp = _safe_text(scene.get("timestamp") or scene.get("timestamp_range")) or "-"
        visual = _safe_text(scene.get("visual_description") or scene.get("visual_summary") or scene.get("description")) or "-"
        voiceover = _voiceover(scene) or "-"
        onscreen = _onscreen_text(scene) or "-"
        shot = _safe_text(scene.get("shot_size") or scene.get("storyboard", {}).get("shot_size")) or "-"
        lighting = _safe_text(scene.get("lighting") or scene.get("storyboard", {}).get("lighting")) or "-"
        movement = _safe_text(scene.get("camera_movement") or scene.get("storyboard", {}).get("camera_movement")) or "-"
        role = _safe_text(scene.get("story_role")) or "-"
        function = _safe_text(scene.get("story_function")) or "-"
        if compact:
            lines.append(
                f"- Scene {scene_number:03d} | {timestamp} | 角色:{role} | 功能:{function} | 画面:{visual[:80]} | 旁白:{voiceover[:48]} | 文字:{onscreen[:36]}"
            )
        else:
            lines.append(
                f"- Scene {scene_number:03d} | {timestamp} | 段落角色:{role} | 主要作用:{function} | 画面:{visual[:120]} | 旁白:{voiceover[:80]} | 文字:{onscreen[:60]} | 镜头:{shot}/{lighting}/{movement}"
            )
    return lines


def build_raw_prompt_scene_packet(data: Dict[str, Any], max_chars: int = 24000) -> str:
    rows = _analysis_rows(data)
    verbose = "\n".join(_scene_packet_lines(rows, compact=False))
    if len(verbose) <= max_chars:
        return verbose

    compact = "\n".join(_scene_packet_lines(rows, compact=True))
    if len(compact) <= max_chars:
        return compact

    compressed: List[str] = []
    for scene in rows:
        scene_number = int(scene.get("scene_number", 0))
        visual = _safe_text(scene.get("visual_description") or scene.get("visual_summary") or scene.get("description")) or "-"
        voiceover = _voiceover(scene) or "-"
        compressed.append(f"- Scene {scene_number:03d} | 画面:{visual[:64]} | 旁白:{voiceover[:32]}")
    return "\n".join(compressed)


def build_raw_prompt_user_message(
    data: Dict[str, Any],
    route: Dict[str, Any],
    context: Dict[str, str],
    required_sections: Sequence[str],
    required_subsections: Dict[str, List[str]] | None = None,
    min_chars_per_section: int = 700,
    min_subsection_chars: int = 180,
    min_scene_evidence_per_section: int = 3,
) -> str:
    lines: List[str] = [
        "## 路由与摘要",
        f"- 路由结果：{_safe_text(route.get('route_label'), '未识别路由')}" + (f"（{route['route_subtype']}）" if _safe_text(route.get("route_subtype")) else ""),
        f"- 参考框架：{_safe_text(route.get('reference'), '未知')}",
        f"- 总场景数：{_safe_text(context.get('total_scenes'), '0')}",
        f"- 平均加权分：{_safe_text(context.get('weighted_avg'), '0.0')}/10",
        f"- 可用素材占比：{_safe_text(context.get('usable_ratio'), '0')}%",
        "",
        "## 内容摘要",
        context.get("content_synopsis_data", "").strip(),
    ]

    highlight_specs = context.get("highlight_specs_list", "").strip()
    if highlight_specs:
        lines.extend(["", "## 高光场景", highlight_specs])

    lines.extend(
        [
            "",
            "## 分镜表上下文",
            build_raw_prompt_scene_packet(data),
        ]
    )

    lines.extend(_build_output_scaffold_block(required_sections, required_subsections or {}))
    lines.extend(
        _build_delivery_rules_block(
            required_sections=required_sections,
            required_subsections=required_subsections or {},
            min_chars_per_section=min_chars_per_section,
            min_subsection_chars=min_subsection_chars,
            min_scene_evidence_per_section=min_scene_evidence_per_section,
        )
    )
    return "\n".join(part for part in lines if part is not None).strip()


def _build_output_scaffold_block(
    required_sections: Sequence[str],
    required_subsections: Dict[str, List[str]],
) -> List[str]:
    lines: List[str] = ["", "## 输出骨架（必须严格复刻）", ""]
    lines.append("请把正文写成下述层级结构，标题字面完全复制，不要合并、不要改写、不要省略：")
    lines.append("")
    lines.append("```")
    for heading in required_sections:
        lines.append(f"## {heading}")
        for subtitle in required_subsections.get(heading, []) or []:
            lines.append(f"### {subtitle}")
        lines.append("")
    lines.append("```")
    return lines


def _build_delivery_rules_block(
    required_sections: Sequence[str],
    required_subsections: Dict[str, List[str]],
    min_chars_per_section: int,
    min_subsection_chars: int,
    min_scene_evidence_per_section: int,
) -> List[str]:
    lines: List[str] = ["", "## 交付规则（交付会被机器校验，不达标直接打回）", ""]
    lines.append(f"- 每个 `##` 模块的正文长度不少于 **{min_chars_per_section}** 字；不允许用单段总结覆盖整个模块。")
    has_subsections = any(bool(required_subsections.get(heading)) for heading in required_sections)
    if has_subsections:
        lines.append(
            f"- 每个 `##` 模块下列出的所有 `###` 子条目都必须出现，标题字面严格一致；每个子条目正文不少于 **{min_subsection_chars}** 字。"
        )
        lines.append("- `###` 子条目之间可以分段、可以包含表格或列表，但不得合并、跳号或改写标题文字。")
    else:
        lines.append("- 原 prompt 未列出固定子条目的模块，仍须按原 prompt 的要点写足分析，不得一笔带过。")
    lines.append(
        f"- 每个 `##` 模块至少引用 **{min_scene_evidence_per_section}** 个不同的 Scene 编号（形如 `Scene 012`）作为证据；编号必须来自上方分镜表。"
    )
    lines.append("- 原 prompt 若在某子条目明确要求表格（例如“| 字段 | 内容 |”），必须以 Markdown 表格呈现，不能改写成段落。")
    lines.append("- 理论引用必须说明其如何作用于当前分析；不要只挂名。未在 prompt 中出现的理论不要引入。")
    lines.append("- 每一条结论都必须有具体 Scene 编号或时间戳作为依据；禁止悬空论断、禁止编造未记录的细节。")
    lines.append("")
    lines.append("## 禁止项")
    lines.append("")
    lines.append('- 禁止把一个模块压缩成单段"总结话"；禁止用同一批 Scene 编号贯穿八个模块。')
    lines.append('- 禁止跳过或合并任何 `###` 子条目；即使判断"不适用"也要显式写出"不适用"与理由，不要静默省略。')
    lines.append('- 禁止只复述分镜表，必须有"数据 → 模式 → 修辞功能 → 战略推导"完整链条。')
    lines.append('- 禁止输出代码块围栏包裹整份报告；禁止在顶层使用 `#` 一级标题（脚本会自己加）。')
    return lines
