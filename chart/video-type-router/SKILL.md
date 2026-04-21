---
name: video-type-router
description: Use when a video needs routing classification before detailed audiovisual analysis, especially when `*_classification_summary.*`, `scene_scores.json`, `*_storyboard_context.json`, or storyboard markdown is available and the agent needs to decide the right analysis framework.
---

# Video Type Router — 视频类型路由分类器

优先读取轻量“分类摘要”，再对视频进行类型分类和分面标注。

## 核心目标

读取标题、分段画面描述、旁白/歌词，输出：

```
类型: concept_mv
视觉来源: P（演绎拍摄）
听觉主导: M（音乐主导）
置信度: 高
```

不是"猜这个视频是什么"，而是"这个视频需要什么分析视角"。分类结果直接决定下游分析模板的选择。

## 输入

接受以下任一输入形式，按优先级从上到下使用：

1. **分类摘要文件**：`*_classification_summary.md` 或 `*_classification_summary.json`
2. **结构化结果文件**：`scene_scores.json` 或 `*_storyboard_context.json`
3. **分镜表 markdown 文件**（video-expert-analyzer 的输出）
4. **用户口头描述**（"这是一个韩国女团的舞蹈MV"）

不要默认去读整份长分镜表，更不要优先读 PDF。长表格 token 重、噪音大、还会把分类信号冲淡。这个 skill 现在默认先用轻量摘要。

## 执行流程

### 情况 A：已经有分类摘要文件

直接读取摘要，跳到“读取分类体系”。

### 情况 B：有结构化结果文件（`scene_scores.json` 或 `*_storyboard_context.json`）

**Step 1 — 生成分类摘要**

运行前置脚本生成轻量分类摘要：

```bash
python3 chart/video-type-router/scripts/extract_signals.py "<输入路径>" 21 "<输出摘要路径>"
```

这个脚本会：
- 优先读取结构化结果，不再重新解析整份长表格
- 把全片按前 / 中 / 后均匀切成约 21 组
- 每组保留镜头相关的画面描述、旁白、画面文字和时间范围
- 统计旁白覆盖率、语言分布、旁白性质
- 同时输出 markdown 和 json 两份摘要

为什么不直接读全量 `scene_scores.json` 或整份分镜表：全量文本太重，而且单镜头噪音很多。按前中后切成约 21 组，能保住结构变化，同时把上下文压到足够轻。

### 情况 C：只有分镜表 markdown

同样先运行：

```bash
python3 chart/video-type-router/scripts/extract_signals.py "<分镜表路径>" 21 "<输出摘要路径>"
```

这里只把 markdown 当兜底输入。优先级低于分类摘要和结构化 JSON。

**Step 2 — 读取分类体系**

读取 `references/taxonomy.md`，获取 19 个类型的定义、判断信号和区分要点。

**Step 3 — 执行分类推理**

按 taxonomy.md 中"分类决策流程"的 6 步执行：

1. 标题快筛
2. 旁白性质判断
3. 画面内容模式识别
4. 交叉验证
5. 分面标注
6. 置信度评估

推理过程应展示给用户，这样用户可以验证分类逻辑。

**Step 4 — 输出结果**

格式：

```yaml
video_title: "(여자)아이들((G)I-DLE) - 'Nxde' Official Music Video"
classification:
  type: concept_mv
  type_cn: 概念 MV
  confidence: high
facets:
  visual_source: P  # 演绎拍摄
  audio_dominance: M  # 音乐主导
reasoning_summary: |
  标题含"Official Music Video"→ MV 类。
  旁白为韩英混合歌词，覆盖率 97%→ 音乐主导。
  画面描述出现 5+ 个独立概念场景（百老汇舞台、化妆间、新闻发布会、博物馆展柜、户外群舞），
  有系统性服装和色调变化→ 非纯表演 MV，是概念 MV。
```

### 情况 D：收到生成好的摘要文件

跳过 Step 1，直接从 Step 2 开始。

### 情况 E：用户口头描述

无需运行脚本，直接根据描述内容执行 Step 2-4 的推理。置信度上限为"中"（因为信息不完整）。

### 情况 F：嵌入 pipeline 使用

当作为 video-expert-analyzer 或其他分析流程的前置路由时：

1. 优先读取主流程在 `finalize` 自动生成的 `*_classification_summary.md/json`
2. 用这份摘要完成正式分类，并写出 `classification_result.json`
3. 如果摘要缺失，再从 `scene_scores.json` 或 `*_storyboard_context.json` 生成
4. 下游工具优先读取 `classification_result.json`，不要再自己重猜路由

主流程默认会在 `finalize` 之后自动产出：

```bash
<工作目录>/<video_id>_classification_summary.md
<工作目录>/<video_id>_classification_summary.json
<工作目录>/classification_result.json
```

如果需要手动补：

```bash
python3 chart/video-type-router/scripts/extract_signals.py "<scene_scores.json 或 storyboard_context.json>" 21
```

```bash
# 输出路径约定
<工作目录>/classification_result.json
```

```json
{
  "video_title": "...",
  "type": "concept_mv",
  "type_cn": "概念 MV",
  "confidence": "high",
  "visual_source": "P",
  "audio_dominance": "M",
  "reasoning": "..."
}
```

## 分类体系速查

共 19 个类型，按分析方法亲缘度分组：

**音乐表演类**
- `concept_mv` — 概念 MV（多场景、有视觉概念设计的音乐视频）
- `performance_mv` — 表演 MV（以舞蹈/舞台为核心的音乐视频）
- `live_session` — 现场演出（演唱会、live stage、录音室 session）

**叙事类**
- `narrative_short` — 叙事短片（有故事线的微电影/短剧）
- `narrative_trailer` — 预告/先导片

**讲述/论证类**
- `talking_head` — 口播/讲述
- `documentary_essay` — 纪实/影像论文
- `commentary_remix` — 评论向二创

**商业类**
- `brand_film` — 品牌影片
- `event_promo` — 活动/促销广告

**知识/信息类**
- `explainer` — 讲解/教学
- `infographic_motion` — 信息动画

**剪辑/混编类**
- `rhythm_remix` — 节奏混剪
- `mood_montage` — 情绪蒙太奇

**生活/记录类**
- `cinematic_vlog` — 生活影像/Vlog
- `reality_record` — 现实纪录
- `meme_viral` — 梗/病毒内容

**视觉/实验类**
- `motion_graphics` — 纯动态图形
- `experimental` — 形式实验

完整定义、判断信号和区分要点见 `references/taxonomy.md`。

## 常见边界情况

**"这个 MV 里有大量剧情，是 concept_mv 还是 narrative_short？"**
→ 如果歌词贯穿始终且剧情服务于歌曲概念，是 concept_mv。如果剧情是独立自足的，歌曲只是背景音乐，是 narrative_short。

**"有品牌植入的 vlog 算 cinematic_vlog 还是 brand_film？"**
→ 看主体。如果主体是个人生活记录、品牌只是其中一个场景，是 cinematic_vlog。如果整个视频围绕品牌展开，是 brand_film。

**"纯舞蹈练习室视频算什么？"**
→ 如果有音乐、有编排、有后期剪辑，是 performance_mv。如果是一镜到底的练习记录，更接近 live_session。

**"科普动画算 explainer 还是 infographic_motion？"**
→ 如果有口播/旁白驱动讲解，是 explainer。如果纯靠视觉信息图自身传递信息，是 infographic_motion。
