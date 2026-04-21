# 视听报告 Template 化迁移计划

## 背景与目标

当前视听报告由 Python 函数硬编码全部评语文本（`audiovisual_report_builder.py` 约 100+ 个 `_xxx_analysis` 函数，
`audiovisual_report_sections.py` 的 `_dimension_commentary` 约 100+ 条 if/else 分支）。
这导致同路由下所有报告措辞雷同、分析角度被锁死、维护成本极高。

**目标**：保留 Python 的计算能力（指标、排序、筛选），把"解读和表达"交给 agent，
通过模板系统让每条片子拿到针对自身内容的深度分析。

**约束**：每个路由只增加一次 LLM call，用结构化输出控制各段边界，延迟可控。

---

## 阶段零：基础设施搭建（不改现有代码，新增模块）

### 0.1 新建 template 引擎模块

新建 `scripts/audiovisual_template_engine.py`，包含：
- `load_route_template(framework)` — 加载模板 + 解析 `<!-- INCLUDE -->` 指令
- `_split_template_sections(text)` — 按 `<!-- SYSTEM -->` / `<!-- DATA -->` / `<!-- TASKS -->` / `<!-- PYTHON_DIRECT -->` 四层拆分
- `fill_template(text, context)` — `{{placeholder}}` 替换
- `_assemble_final_report(agent_text, context, direct_blocks, data, route)` — 后插组装（配图、评分表、直插块）
- 辅助函数：`_fmt_avg`、`_fmt_pct`、`_format_scenes_by_dimension`、`_build_figure_map`

### 0.2 新建 template 目录结构

```
scripts/templates/
  _base_system.md                          # 所有路由共用的 system prompt 前缀
  _base_scoring_table.md                   # 共用的评分表 PYTHON_DIRECT 块
  _base_alignment.md                       # 共用的对齐度 PYTHON_DIRECT 块
  template_mix_music.md                    # 已有，需按新四层格式调整
  template_concept_mv.md
  template_narrative_performance.md
  template_narrative_trailer.md
  template_documentary_generic.md
  template_commentary_mix.md
  template_cinematic_life.md
  template_technical_explainer.md
  template_event_brand_ad.md
  template_journey_brand_film.md
  template_meme.md
  template_hybrid_commentary.md
  template_hybrid_music.md
  template_hybrid_meme.md
  template_hybrid_narrative.md
  template_hybrid_ambient.md
  template_silent_reality.md
  template_silent_performance.md
  template_pure_visual_mix.md
  template_infographic_animation.md
  template_abstract_sfx.md
  template_pure_motion_graphics.md
  template_narrative_motion_graphics.md
  template_reality_sfx.md
  template_narrative_mix.md
  template_lecture_performance.md
```

### 0.3 新建上下文构建器注册表

在 `audiovisual_template_engine.py` 中建立路由 → context builder 函数的注册表：

```python
_ROUTE_CONTEXT_BUILDERS = {
    "mix_music": _build_mix_music_context,
    "concept_mv": _build_concept_mv_context,
    # ...
}
```

每个 builder 接收 `(context, data, ordered)` 参数，负责：
1. 计算路由专属指标
2. 按维度分组筛选场景
3. 把结果写入 context dict

---

## 阶段一：单路由 PoC 验证（mix_music）

### 1.1 完善 template_mix_music.md

当前模板已有基本四层结构，需要补充：
- 顶部 `<!-- INCLUDE:_base_system.md -->` 引入共用 system 前缀
- 底部 `<!-- INCLUDE:_base_scoring_table.md -->` 引入共用评分表
- 确认 FIGURE 占位名称与 `_highlight_specs_for_route` 的 title 字段对齐
- 确认 PYTHON_DIRECT 块的 section_name 在 `_assemble_final_report` 中能被正确替换

### 1.2 实现 mix_music 的 context builder

从现有 `_mix_music_rhythm_analysis`、`_mix_music_source_quality`、`_mix_music_creative_value` 三个函数中提取纯计算逻辑：

| 原函数 | 提取的计算 | 去掉的文字 |
|--------|-----------|-----------|
| `_mix_music_rhythm_analysis` | avg_duration、short_cut_ratio、beat_hit_scenes、rhythm_consistency | if/else 拼接的评语 |
| `_mix_music_source_quality` | high_score_ratio、avg_aesthetic、style_consistency | if/else 拼接的评语 |
| `_mix_music_creative_value` | emotion_variance、peak_count、peak_scene_refs、avg_memorability | if/else 拼接的评语 |

计算逻辑不变，结果写入 context dict，供模板注入。

### 1.3 实现单路由 API 调用链路

```
data + route
  → load_route_template("mix_music")
  → _split_template_sections
  → build_template_context(data, route)
  → fill_template(system_section, context) → system prompt
  → fill_template(data_section, context) + fill_template(tasks_section, context) → user message
  → Anthropic API call
  → _assemble_final_report → 最终 markdown
```

### 1.4 对比测试

选 3-5 条已有分镜表的 mix_music 类型视频：
- 用旧系统（Python 硬编码）生成报告 A
- 用新模板系统生成报告 B
- 对比维度：
  - **针对性**：B 是否对每条片子的独特性有更具体的分析？
  - **准确性**：B 的判断是否与实际分镜内容吻合？
  - **结构一致性**：B 是否保持了报告应有的节名和格式？
  - **token 消耗**：单次 call 的 input/output token 数
  - **延迟**：端到端生成时间

**通过标准**：B 在针对性和准确性上明显优于 A，结构和格式稳定，单次延迟 < 30s。

---

## 阶段二：批量迁移（按优先级分批）

按路由使用频率和复杂度分三批。每批完成后都做对比测试。

### 第一批：高频路由（5 个）

| 路由 | template 文件 | 现有分析函数数 | context builder 重点 |
|------|-------------|-------------|-------------------|
| narrative_performance | template_narrative_performance.md | ~12 个 | 叙事分组(setup/conflict/climax/resolution)、双层分析、音乐层 |
| narrative_trailer | template_narrative_trailer.md | ~6 个 | 预告片分组(opening/setup/investigation/escalation/payoff/cards)、卖点分析 |
| concept_mv | template_concept_mv.md | ~3 个 | 意象一致性、情绪曲线与歌曲结构对应 |
| cinematic_life | template_cinematic_life.md | ~3 个 | 美学一致性、电影化与真实感平衡 |
| commentary_mix | template_commentary_mix.md | ~3 个 | 论点密度、信息分工冲突、5W1H 覆盖度 |

### 第二批：中频路由（8 个）

| 路由 | template 文件 | context builder 重点 |
|------|-------------|-------------------|
| meme | template_meme.md | 梗密度、视听同步率、圈层标记、反差效果 |
| documentary_generic | template_documentary_generic.md | 5W1H 覆盖度、可信度、现场感 |
| technical_explainer | template_technical_explainer.md | 讲解分组(question/overview/detail/step/recap)、步骤完整性 |
| hybrid_narrative | template_hybrid_narrative.md | 多手法层次、叙事统一性 |
| hybrid_music | template_hybrid_music.md | 多风格切换、情绪方向统一性 |
| hybrid_commentary | template_hybrid_commentary.md | 多素材价值、论证力度 |
| narrative_mix | template_narrative_mix.md | 素材重组、故事重写价值 |
| lecture_performance | template_lecture_performance.md | 讲述/表演分层、互动检测 |

### 第三批：低频路由（12 个）

| 路由 | template 文件 |
|------|-------------|
| event_brand_ad | template_event_brand_ad.md |
| journey_brand_film | template_journey_brand_film.md |
| hybrid_meme | template_hybrid_meme.md |
| hybrid_ambient | template_hybrid_ambient.md |
| silent_reality | template_silent_reality.md |
| silent_performance | template_silent_performance.md |
| pure_visual_mix | template_pure_visual_mix.md |
| infographic_animation | template_infographic_animation.md |
| abstract_sfx | template_abstract_sfx.md |
| pure_motion_graphics | template_pure_motion_graphics.md |
| narrative_motion_graphics | template_narrative_motion_graphics.md |
| reality_sfx | template_reality_sfx.md |

### 每个 template 的编写规范

每个路由 template 必须包含：

```
<!-- SYSTEM -->
[角色定义 + 路由类型说明 + 写作约束（6 条通用 + 路由专属约束）]
<!-- /SYSTEM -->

<!-- DATA -->
[路由判断信息]
[场景总览数字]
[路由专属指标数据]
[按维度分组的场景数据]
[高光场景列表]
<!-- /DATA -->

<!-- TASKS -->
[节 1：先看结论（核心逻辑 + 高光场景 + 总体评价）]
<!-- FIGURE:xxx -->
[节 2-N：路由专属分析节，每节 3-5 句，2-4 个有锋芒的核心问题]
<!-- FIGURE:xxx -->
[观看建议与失效风险节]
[综合述评节（内容身份 + 轨道分析 + 整体评价）]
<!-- PYTHON_DIRECT:alignment -->
<!-- PYTHON_DIRECT:scoring_table -->
<!-- /TASKS -->
```

---

## 阶段三：旧系统兼容与切换

### 3.1 双轨并行期

在 `synthesize_audiovisual_report` 入口处加开关：

```python
USE_TEMPLATE_ENGINE = os.environ.get("VNEXT_TEMPLATE_ENGINE", "0") == "1"

def synthesize_audiovisual_report(data, route):
    if USE_TEMPLATE_ENGINE:
        return _template_synthesize(data, route)
    else:
        return _legacy_synthesize(data, route)  # 现有逻辑不改
```

双轨期间，两种生成方式都可用。通过环境变量切换，不破坏现有功能。

### 3.2 `_dimension_commentary` 和 `_dimension_rows` 的处理

当前 `_dimension_commentary`（audiovisual_report_sections.py:25-163）为每个维度 × 每个路由硬编码评语。
迁移后这部分不再需要——评分表变成 PYTHON_DIRECT 块，维度解读变成 agent 写作任务的一部分。

迁移路径：
1. 旧系统保留 `_dimension_rows` 作为 fallback
2. 新系统中，维度评分表用 PYTHON_DIRECT 直插，维度评语由 agent 在"综合述评"节中自然覆盖
3. 全部路由迁移完成后，删除 `_dimension_commentary` 及其 100+ 条 if/else

### 3.3 `_route_specific_sections` 的处理

当前 `_route_specific_sections`（audiovisual_report_sections.py:354-649）是最大的单函数，
按路由 if/return 拼接完整报告结构。

迁移路径：
1. 每个路由的 template 替代对应的 if 分支
2. 全部迁移完成后，删除整个 `_route_specific_sections` 函数

### 3.4 `_identity` 函数的处理

`_identity`（audiovisual_report_sections.py:183-351）为每个路由硬编码 content_type / target_audience / core_intent。
迁移后由 agent 在"综合述评·内容身份"节中基于数据自行判断。

迁移路径：
1. 旧系统保留 `_identity` 作为 fallback
2. 新系统中不再调用 `_identity`，agent 直接输出
3. 全部迁移完成后删除

### 3.5 清理计划

全部路由迁移完成且测试通过后：

| 删除对象 | 文件 | 行数 |
|----------|------|------|
| `_dimension_commentary` 全部 if/else | report_sections.py | ~140 行 |
| `_route_specific_sections` 全部 if 分支 | report_sections.py | ~300 行 |
| `_identity` 全部 if/return | report_sections.py | ~170 行 |
| 所有 `_xxx_analysis` 文字拼接函数 | report_builder.py | ~600 行 |
| 保留的计算函数（`_pick_scenes`、`_ordered_scenes`、`_narrative_groups` 等） | report_builder.py | ~400 行 |

---

## 阶段四：优化与加固

### 4.1 输出格式约束强化

在 system prompt 中加入硬性格式要求，并在 `_assemble_final_report` 中做后校验。
当前已落地的第一步是：如果 agent 漏掉必需节名，直接报清晰错误并回退到 legacy 路径。
后续如果需要，再补“只补缺失节”的二次调用：

```python
REQUIRED_SECTIONS = ["## 先看结论", "## ...", "## 综合述评"]

def _validate_agent_output(text: str, required_sections: list) -> str:
    missing = [s for s in required_sections if s not in text]
    if missing:
        # 后续可选：补调一次 agent，只生成缺失的节
        ...
    return text
```

### 4.2 family base template 共享机制

四个 family 各一个共享模板：
- `_family_language_led.md` — 通用节（内容身份、轨道分析、评分表）+ 语言主导类共享的分析角度
- `_family_atmospheric.md`
- `_family_meme.md`
- `_family_graphic.md`

具体路由 template 通过 `<!-- INCLUDE -->` 引入 base，再覆盖差异部分。

### 4.3 模板版本管理

每个 template 顶部加版本号和变更日志：

```markdown
# version: 1.0.0
# last_updated: 2026-04-12
# changes: 初始版本
```

Python 加载时校验版本号，不匹配时 warn。

### 4.4 一次性调用优化

当前设计是每个路由一次 LLM call。如果后续发现单次 call 的 max_tokens 不够（某些路由的分析节较多），
可改为：
- 一次 call 输出 JSON 格式：`{"section_1": "...", "section_2": "...", ...}`
- Python 解析 JSON 后按顺序拼入报告

但初期建议先用 markdown 格式输出，观察实际 token 消耗再决定是否切 JSON。

---

## 时间线与里程碑

| 里程碑 | 内容 | 验收标准 |
|--------|------|----------|
| M0 | 基础设施搭建（template 引擎 + 目录结构 + context builder 注册表） | 引擎可加载模板、拆分层、填充数据、组装输出 |
| M1 | mix_music PoC 完成 + 对比测试通过 | 新系统在 3-5 条样本上针对性明显优于旧系统 |
| M2 | 第一批 5 个高频路由迁移完成 | 每个路由至少 2 条样本对比通过 |
| M3 | 第二批 8 个中频路由迁移完成 | 同上 |
| M4 | 第三批 12 个低频路由迁移完成 | 同上 |
| M5 | 旧代码清理 + 双轨切换为默认新系统 | 所有 `_xxx_analysis` 文字函数已删除，旧系统入口移除 |
| M6 | 输出格式校验 + family base template + 版本管理 | 后校验覆盖率 100%，base template 全部就位 |

---

## 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| Agent 输出格式不稳定（漏节、合并节） | 报告结构被破坏 | 后校验 + 缺失节补调 |
| 单次 call 延迟过高 | 用户体验差 | 监控 token 数，必要时拆成 2 次 call |
| 某些路由的模板质量不够，分析深度不如旧系统 | 降级 | 双轨并行期可随时回退，每个路由独立验证 |
| context 数据过大导致 input token 超限 | API 报错 | 按维度分组裁剪场景数据，每维度最多 5 条 |
| 模板维护分散到 25+ 个 md 文件 | 一致性难保 | family base template + 共享校验脚本 |
