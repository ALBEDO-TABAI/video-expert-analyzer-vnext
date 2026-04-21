# 视听报告 Template 设计规范
# 供各路由 template 编写参考 + Python 调用说明

---

## 一、模板文件命名规范

每个路由对应一个 template 文件：

```
templates/
  template_mix_music.md
  template_concept_mv.md
  template_narrative_performance.md
  ...
```

当前模板体系有两层复用：
- 所有路由都会通过 `<!-- INCLUDE:_base_*.md -->` 复用共用块
- 部分路由会直接落到 family 文件（如 `_family_atmospheric.md`、`_family_meme.md`）做共享

`load_route_template` 会优先加载 `template_<framework>.md`；如果缺失，再回退到对应的 `_family_<family>.md`。
同时它会递归解析 `<!-- INCLUDE:... -->`，并检查缺文件、循环引用与嵌套 include 的相对路径。

---

## 二、每个 Template 的四层结构

### 层 1：`<!-- SYSTEM -->`（作为 API system prompt，不出现在报告中）

定义 agent 的角色和写作风格。
这一层填充后直接作为 `system=` 参数传入 Claude API，不会出现在 user message 里。

**必须包含的写作约束：**
- 聚焦这条具体片子，不写通用规律
- 结论要落到具体 Scene 编号
- 不重复堆砌数字，数字只是判断的起点
- 不输出通用占位句（"整体良好"、"基本成立"、"节奏感不错"）
- 严格按指定节名输出，不增减节名，节之间用 `---` 分隔
- 不输出前言、结语或节名之外的任何内容

---

### 层 2：`<!-- DATA -->`（作为 user message 的数据部分，agent 只读不输出）

Python 填充 `{{placeholder}}` 后注入。这一层提供分析所需的原始材料。

**关键设计：场景数据按分析维度分组提供，而不是只给一个按总分排序的平铺列表。**

每个 template 的注入内容分三类：

**A. 通用注入（所有路由都有）：**
```
场景总览数字（总数、均值、占比）
视听对齐数据
高光场景列表（系统选出的 highlight_specs）
```

**B. 路由专属注入（按 framework 定义）：**
```
mix_music：节奏一致性、卡点场景、情绪曲线波动、二创重组价值
narrative_performance：叙事角色分组（setup/conflict/climax）、音乐层分析
commentary_mix：论点密度、信息分工冲突场景数、5W1H 覆盖度
...
```

**C. 按维度分组的场景数据：**
```
--- 节奏相关 ---
Scene 023 | 1.2s | 描述：快速切换的角色特写 | 冲击 8.5 | 记忆度 7.2
Scene 041 | 0.8s | 描述：卡点爆破段落 | 冲击 9.1 | 记忆度 8.0

--- 素材质量相关 ---
Scene 012 | 3.5s | 描述：逆光下的角色全身镜 | 美学 9.0 | 风格：赛博朋克
...
```
这样 agent 在写不同节时可以直接引用对应维度的场景，不用自己翻全部数据。

---

### 层 3：`<!-- TASKS -->`（作为 user message 的写作任务部分，agent 按此输出）

这是 template 最核心的部分。每个需要 agent 写作的节：

```
### 节名

**写作任务（字数约束）：**
[2-4 个有锋芒的核心问题]

不要写：[具体列出要避免的废话模式]

<!-- FIGURE: figure_slot_name -->
```

`<!-- FIGURE:xxx -->` 标记配图占位位置，agent 在这个位置之前写完该节的分析文字，
Python 后处理时替换为实际场景截图的 figure block。

**关键原则：**
- 问题要有锋芒——不问"节奏好不好"，问"它是等速切还是渐进加速，弱点在哪段"
- 不同路由的分析任务要真正不同，不能互换

---

### 层 4：`<!-- PYTHON_DIRECT -->`（Python 后插，agent 不碰）

评分表、路由判断信息、对齐度原始数据等**纯计算结果**，
Python 在 agent 输出之后直接拼入最终 markdown，不经过 agent。
这些内容在 template 里用 `<!-- PYTHON_DIRECT:section_name -->` 标记。

这样做的好处：
- 不浪费 agent token 让它复述数字
- 避免 agent 误读或改写计算值
- 保证数值和 Python 计算完全一致

---

## 三、Python 调用方式

```python
import re
from pathlib import Path
from anthropic import Anthropic

# ── 模板加载 ──────────────────────────────────────────────────

_INCLUDE_RE = re.compile(r"<!--\s*INCLUDE:(.*?)\s*-->")


def load_route_template(framework: str, templates_dir: Path | None = None) -> str:
    """加载路由 template，解析 INCLUDE 指令拼接 base template"""
    base_dir = templates_dir or Path(__file__).parent / "templates"
    template_path = base_dir / f"template_{framework}.md"
    if not template_path.exists():
        family = _framework_family_name(framework)
        template_path = base_dir / f"_family_{family}.md"
    return _resolve_includes(
        template_path.read_text(encoding="utf-8"),
        template_path.parent,
        include_stack=(template_path.resolve(),),
    )


def _resolve_includes(text: str, base_dir: Path, include_stack: Sequence[Path] | None = None) -> str:
    """递归解析 include，并处理缺文件、循环引用和相对路径"""
    def _replacer(m):
        include_path = base_dir / m.group(1).strip()
        included = include_path.read_text(encoding="utf-8")
        return _resolve_includes(included, include_path.parent, include_stack=(*include_stack, include_path.resolve()))
    return _INCLUDE_RE.sub(_replacer, text)


# ── 模板拆分 ──────────────────────────────────────────────────

def _split_template_sections(template_text: str) -> dict:
    """把模板拆成 system / data / tasks / python_direct 四部分"""
    sections = {}
    # 匹配 <!-- SYSTEM --> ... <!-- /SYSTEM --> 格式
    for tag in ("SYSTEM", "DATA", "TASKS"):
        pattern = rf"<!--\s*{tag}\s*-->(.*?)<!--\s*/{tag}\s*-->"
        m = re.search(pattern, template_text, re.DOTALL)
        sections[tag.lower()] = m.group(1).strip() if m else ""

    # 提取所有 PYTHON_DIRECT 标记及其位置
    direct_blocks = []
    for m in re.finditer(
        r"<!--\s*PYTHON_DIRECT:(\w+)\s*-->(.*?)<!--\s*/PYTHON_DIRECT\s*-->",
        template_text, re.DOTALL,
    ):
        direct_blocks.append({"name": m.group(1), "template": m.group(2).strip()})
    sections["python_direct"] = direct_blocks
    return sections


# ── 上下文构建 ──────────────────────────────────────────────────

def build_template_context(data: dict, route: dict) -> dict:
    """
    把 Python 计算好的所有指标组装成 template 的占位符 dict。
    通用字段 + 路由专属字段 + 按维度分组的场景数据。
    """
    scenes = data.get("scenes", [])
    ordered = _analysis_rows(data)

    # ── 通用字段 ──
    context = {
        "route_label": route["route_label"],
        "route_subtype_str": f"（{route['route_subtype']}）" if route.get("route_subtype") else "",
        "total_scenes": len(scenes),
        "weighted_avg": _fmt_avg([float(s.get("weighted_score") or 0) for s in scenes if float(s.get("weighted_score") or 0) > 0]),
        "usable_ratio": _fmt_pct(sum(1 for s in scenes if "[MUST KEEP]" in _safe_text(s.get("selection")) or "[USABLE]" in _safe_text(s.get("selection"))), len(scenes)),
        "avg_aesthetic": _fmt_avg([float(s.get("scores", {}).get("aesthetic_beauty") or 0) for s in scenes]),
        "avg_impact": _fmt_avg([float(s.get("scores", {}).get("impact") or 0) for s in scenes]),
        "avg_memorability": _fmt_avg([float(s.get("scores", {}).get("memorability") or 0) for s in scenes]),
        "avg_fun": _fmt_avg([float(s.get("scores", {}).get("fun_interest") or 0) for s in scenes]),
        "avg_credibility": _fmt_avg([float(s.get("scores", {}).get("credibility") or 0) for s in scenes]),
        "avg_info_efficiency": _fmt_avg([float(s.get("analysis_dimensions", {}).get("information_efficiency") or 0) for s in scenes]),
        "alignment_level": _alignment_summary(data)["level"],
        "visual_peak_scenes": ", ".join(f"Scene {n:03d}" for n in _alignment_summary(data)["visual_peaks"]) or "无",
        "language_peak_scenes": ", ".join(f"Scene {n:03d}" for n in _alignment_summary(data)["language_peaks"]) or "无",
        "highlight_specs_list": _format_highlight_specs_for_template(data, route),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # ── 路由专属字段（由各路由的 builder 函数补充）──
    _build_route_context(context, data, route, ordered)

    return context


def _build_route_context(context: dict, data: dict, route: dict, ordered: list) -> None:
    """路由专属字段入口，按 framework 分发"""
    builder = _ROUTE_CONTEXT_BUILDERS.get(route["framework"])
    if builder:
        builder(context, data, ordered)


def _build_mix_music_context(context: dict, data: dict, ordered: list) -> None:
    durations = [float(s.get("duration_seconds") or 0) for s in ordered]
    avg_dur = _avg(durations)
    short_cuts = [s for s in ordered if float(s.get("duration_seconds") or 0) < avg_dur * 0.6]
    beat_hits = [s for s in short_cuts if float(s.get("scores", {}).get("impact") or 0) >= 7.0]
    rhythm_consistency = 1.0 - (max(durations) - min(durations)) / (max(durations) + 0.1) if durations else 0.0
    high_score = [s for s in ordered if float(s.get("weighted_score") or 0) >= 7.0]
    style_kw = [_safe_text(s.get("storyboard", {}).get("visual_style")) for s in ordered]
    style_div = len(set(style_kw)) / len(style_kw) if style_kw else 1.0
    emotion_curve = [float(s.get("analysis_dimensions", {}).get("emotional_effect") or 0) for s in ordered]
    peaks = [ordered[i] for i, v in enumerate(emotion_curve) if v >= 7.5]

    context.update({
        "avg_duration": f"{avg_dur:.1f}",
        "short_cut_ratio": _fmt_pct(len(short_cuts), len(ordered)),
        "beat_hit_scenes": _scene_refs(beat_hits[:4], 4) if beat_hits else "未检测到明显卡点",
        "rhythm_consistency": f"{rhythm_consistency * 10:.1f}",
        "high_score_ratio": _fmt_pct(len(high_score), len(ordered)),
        "high_score_scene_refs": _scene_refs(high_score[:5], 5),
        "style_consistency": f"{(1 - style_div) * 10:.1f}",
        "top_visual_styles": _top_text(style_kw, limit=3) or "多种风格混合",
        "emotion_variance": f"{max(emotion_curve) - min(emotion_curve):.1f}" if emotion_curve else "0.0",
        "emotion_peak_count": str(len(peaks)),
        "emotion_peak_scene_refs": _scene_refs(peaks[:4], 4) if peaks else "未检测到明显峰值",
    })

    # 按维度分组提供场景数据
    context["scenes_by_dimension"] = _format_scenes_by_dimension(
        ordered,
        groups={
            "节奏相关": lambda s: (
                float(s.get("duration_seconds") or 0) < avg_dur * 0.6
                or float(s.get("scores", {}).get("impact") or 0) >= 7.0
            ),
            "素材质量相关": lambda s: float(s.get("weighted_score") or 0) >= 7.0,
            "情绪相关": lambda s: float(s.get("analysis_dimensions", {}).get("emotional_effect") or 0) >= 7.0,
        },
        limit_per_group=5,
    )


# 其他路由的 builder 函数按同样模式添加
_ROUTE_CONTEXT_BUILDERS = {
    "mix_music": _build_mix_music_context,
    # "concept_mv": _build_concept_mv_context,
    # "narrative_performance": _build_narrative_performance_context,
    # ...
}


# ── 模板填充 ──────────────────────────────────────────────────

def fill_template(template_text: str, context: dict) -> str:
    """简单的 {{key}} 替换，不引入 Jinja 依赖"""
    for key, value in context.items():
        template_text = template_text.replace(f"{{{{{key}}}}}", str(value))
    return template_text


# ── 主入口 ──────────────────────────────────────────────────

def synthesize_audiovisual_report(data: dict, route: dict) -> str:
    """
    主入口：加载 template → 拆分层 → 填充数据 → 调用 API → 后插组装
    """
    template_text = load_route_template(route["framework"])
    sections = _split_template_sections(template_text)
    context = build_template_context(data, route)

    # system prompt：填充路由专属信息
    system_prompt = fill_template(sections["system"], context)

    # user message：数据 + 写作任务，不含 system prompt 内容
    data_text = fill_template(sections["data"], context)
    tasks_text = fill_template(sections["tasks"], context)
    user_message = f"## 分析数据\n\n{data_text}\n\n## 写作任务\n\n{tasks_text}"

    # 调用 API
    client = Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    agent_text = message.content[0].text

    # 后插：评分表、路由判断、配图等 Python 直接拼入
    return _assemble_final_report(agent_text, context, sections["python_direct"], data, route)


def _assemble_final_report(
    agent_text: str,
    context: dict,
    python_direct_blocks: list,
    data: dict,
    route: dict,
) -> str:
    """
    把 agent 输出和 Python 直插内容组装成最终 markdown。
    """
    parts = [agent_text]

    # 1. 替换 <!-- FIGURE:xxx --> 为实际场景截图块
    specs = _highlight_specs_for_route(data, route)
    figure_map = _build_figure_map(specs)
    for slot_name, figure_block in figure_map.items():
        parts[0] = parts[0].replace(f"<!-- FIGURE:{slot_name} -->", figure_block)

    # 2. 插入 PYTHON_DIRECT 块（评分表、路由信息等）
    for block in python_direct_blocks:
        filled = fill_template(block["template"], context)
        parts[0] = parts[0].replace(f"<!-- PYTHON_DIRECT:{block['name']} -->", filled)

    # 3. 末尾追加生成时间
    parts[0] += f"\n\n*生成时间：{context['generated_at']}*"
    return parts[0]


# ── 辅助函数 ──────────────────────────────────────────────────

def _fmt_avg(values: list) -> str:
    return f"{_avg(values):.1f}" if values else "0.0"


def _fmt_pct(numerator: int, denominator: int) -> str:
    return f"{numerator / max(denominator, 1) * 100:.0f}"


def _format_highlight_specs_for_template(data: dict, route: dict) -> str:
    specs = _highlight_specs_for_route(data, route)
    lines = []
    for title, scene, note in specs:
        if scene:
            num = int(scene.get("scene_number", 0))
            lines.append(f"- Scene {num:03d} · {title}：{note}")
    return "\n".join(lines) if lines else "- 暂无高光场景数据"


def _format_scenes_by_dimension(
    scenes: list,
    groups: dict[str, callable],
    limit_per_group: int = 5,
) -> str:
    """按维度分组格式化场景数据，方便 agent 按需引用"""
    parts = []
    for group_name, predicate in groups.items():
        matched = [s for s in scenes if predicate(s)][:limit_per_group]
        if not matched:
            continue
        parts.append(f"**{group_name}**")
        for s in matched:
            num = int(s.get("scene_number", 0))
            dur = float(s.get("duration_seconds") or 0)
            desc = _scene_desc(s)[:60]
            impact = float(s.get("scores", {}).get("impact") or 0)
            memo = float(s.get("scores", {}).get("memorability") or 0)
            aesthetic = float(s.get("scores", {}).get("aesthetic_beauty") or 0)
            parts.append(f"Scene {num:03d} | {dur:.1f}s | {desc} | 冲击 {impact:.1f} | 记忆 {memo:.1f} | 美学 {aesthetic:.1f}")
        parts.append("")
    return "\n".join(parts)


def _build_figure_map(specs: list) -> dict:
    """把 highlight_specs 转成 slot_name → figure_block 的映射"""
    figure_map = {}
    for title, scene, note in specs:
        if not scene:
            continue
        slot = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", title).strip("_").lower()
        num = int(scene.get("scene_number", 0))
        screenshot = _scene_screenshot(scene)
        if screenshot:
            figure_map[slot] = f"\n![Scene {num:03d} - {title}]({screenshot})\n*{note}*\n"
    return figure_map
```
