[![Version](https://img.shields.io/badge/version-3.0.0-blue)](https://img.shields.io/badge/version-3.0.0-blue) [![License](https://img.shields.io/badge/license-MIT-green)](https://img.shields.io/badge/license-MIT-green) [![Python](https://img.shields.io/badge/python-3.9+-yellow)](https://img.shields.io/badge/python-3.9+-yellow) [![AI Models](https://img.shields.io/badge/AI-GPT--5.4%20%7C%20Kimi%20K2.6%20%7C%20GLM--5v--turbo%20%7C%20Xiaomi--v2--omni-purple)](https://img.shields.io/badge/AI-multi--model-purple)

**🌐 Language / 语言**
[English](#-video-expert-analyzer-vnext) | [中文](#-视频专家分析器-vnext)

---

# 🎬 Video Expert Analyzer VNext

> **Next-generation** AI-powered professional video analysis tool — evolved from [v2.x](https://github.com/ALBEDO-TABAI/video-expert-analyzer) with **standardized storyboard tables**, **multi-dimensional audiovisual reports**, and a **resumable parallel pipeline** designed for long videos.

## 🆕 What's New in VNext (vs v2.x)

| Area | v2.x | **VNext** |
|------|------|-----------|
| 📋 **Storyboard** | Basic scene list | **Standardized storyboard table** with shot size, lighting, camera movement, visual style, technique, voiceover, on-screen text, and screenshot per scene |
| 📊 **Audiovisual Report** | 5D scoring report | **Multi-dimensional audiovisual analysis** — 25 route-specific frameworks across 4 families (Narrative / Atmospheric / Meme / Graphic), with SVG diagrams |
| 🔄 **Pipeline** | Single-pass, restarts on failure | **Resumable staged execution** — prepare → score → merge → finalize, with `run_state.json` checkpoints |
| ⚡ **Performance** | Sequential scoring | **Parallel batch scoring** — configurable concurrency (default: 4 workers), vision API calls run simultaneously |
| 🎯 **Video Routing** | 4 scene types | **19 video type classifications** via dual-axis routing (5 Visual × 5 Audio = 25 route combinations) |
| 🤖 **Model Support** | Gemini / Kimi / Claude | **GPT-5.4, Kimi K2.6, GLM-5v-turbo, Xiaomi-v2-omni** tested for vision; **K2.6, GLM-5.1, Xiaomi-v2-pro** tested for report generation |
| 🔗 **Orchestration** | Standalone only | **OpenClaw relay mode** — controller + batch worker handoff for distributed execution |

## ✨ Core Features

| Feature | Description |
|---------|-------------|
| 🤖 **Real AI Vision Scoring** | Multimodal models analyze actual frame content — no sampling, no guessing |
| 📋 **Standardized Storyboard** | Per-scene table: shot size / lighting / camera movement / visual style / technique / voiceover / on-screen text |
| 📊 **Multi-Dimensional Audiovisual Report** | Route-specific deep analysis with validated word counts (≥700 chars/section) and ≥3 scene references per section |
| ⚡ **Parallel Batch Scoring** | Frames sent to AI providers in parallel batches, with auto-retry and stale detection |
| 🔄 **Resumable Pipeline** | Crash-safe staged execution — automatically picks up where it left off |
| 🎯 **19-Type Video Classifier** | Dual-axis routing (Visual Source × Audio Dominance) maps to specialized analysis templates |
| 🎤 **Smart Subtitle Extraction** | 4-tier fallback: Platform API → Embedded → RapidOCR → FunASR/mlx-whisper |
| ⭐ **Best Shots** | Auto-select highlight clips (score ≥ 7.5) to `best_shots/` |
| 🌐 **Bilingual Reports** | Reports generated in your chosen language (zh-CN, en-US, ja-JP, etc.) |

## 📱 Supported Platforms

| Platform | Status | Notes |
|----------|--------|-------|
| 🎬 **Bilibili** | ✅ Full Support | yt-dlp download + Bilibili API subtitles |
| 📺 **YouTube** | ✅ Full Support | yt-dlp download |
| 🎵 **Douyin (抖音)** | ✅ Full Support | Dedicated downloader (share links, no cookies needed) |
| 📕 **Xiaohongshu (小红书)** | ✅ Full Support | Dedicated downloader |
| 🌍 **Others** | ⚠️ May Work | Depends on yt-dlp support |

## 🤖 Model Compatibility

### Vision Analysis (Scene Scoring)

> Models used for analyzing individual frames across 5 scoring dimensions.

| Model | Status | Notes |
|-------|--------|-------|
| **GPT-5.4** | ✅ Tested | Strong visual understanding |
| **Kimi K2.6** | ✅ Tested | Excellent for Chinese context |
| **GLM-5v-turbo** | ✅ Tested | Fast, good cost-performance ratio |
| **Xiaomi-v2-omni** | ✅ Tested | Solid multimodal capability |
| Other OpenAI-compatible vision models | ⚠️ May Work | Must support image input |
| Text-only models | ❌ No | Cannot score without vision |

### Report Generation (Audiovisual Analysis)

> Models used for synthesizing the final multi-dimensional audiovisual report.

| Model | Status | Notes |
|-------|--------|-------|
| **Kimi K2.6** | ✅ Tested | Rich Chinese output, strong reasoning |
| **GLM-5.1** | ✅ Tested | Good structure and coherence |
| **Xiaomi-v2-pro** | ✅ Tested | Detailed and analytical |
| Other strong text models | ⚠️ May Work | Needs long-context capability |

## ⚡ Performance & Batch Processing

The vision analysis stage sends frames to AI providers in **parallel batches** rather than sequentially:

| Parameter | Default | Description |
|-----------|---------|-------------|
| **Batch size** | 6 scenes/batch | Scenes grouped for each API call |
| **Concurrency** | 4 workers | Number of parallel API calls |
| **Stale timeout** | 30 min | Auto-retry threshold for hung batches |

### 📐 Benchmark Reference

| Video Length | Scenes | Estimated Time | Notes |
|-------------|--------|----------------|-------|
| **3 min 40 sec** | ~155 shots | **40 – 110 min** | Depends on hardware, network, and AI provider throughput |

> ⚠️ **Before increasing concurrency**, verify your AI provider's rate limits and maximum parallel request policy. Some providers enforce strict concurrency caps.

Factors affecting speed:
- 💻 **Local hardware** — frame extraction and contact sheet generation
- 🌐 **Network quality** — upload speed for frame images
- 🤖 **AI provider throughput** — model response time and queue depth

## 🚀 Quick Start

### Prerequisites

```bash
# System dependencies
brew install ffmpeg          # macOS
# sudo apt install ffmpeg    # Ubuntu/Debian

# Install Python dependencies
pip3 install -r requirements.txt
```

### One-Command Analysis

```bash
# Analyze any video (auto-detects platform)
python3 scripts/orchestrate_vnext.py "https://www.bilibili.com/video/BV1xxxxx"
python3 scripts/orchestrate_vnext.py "https://www.douyin.com/video/xxxxx"
python3 scripts/orchestrate_vnext.py /path/to/local_video.mp4

# Resume from previous run
python3 scripts/orchestrate_vnext.py /path/to/scene_scores.json
```

### Stage-by-Stage (Advanced)

```bash
# 1. Prepare: download, scene detect, extract subtitles
python3 scripts/pipeline_enhanced.py "<video_url>"

# 2. Score: parallel batch vision analysis
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode score_batches

# 3. Merge: combine batch results, validate
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode merge_validate

# 4. Finalize: generate storyboard + audiovisual report
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode finalize
```

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `VIDEO_ANALYZER_API_KEY` | Vision model API key | `sk-xxx` |
| `VIDEO_ANALYZER_BASE_URL` | API endpoint | `https://api.openai.com/v1` |
| `VIDEO_ANALYZER_MODEL` | Vision model name | `gpt-5.4` |
| `OPENAI_API_KEY` | Alternative: OpenAI key | `sk-xxx` |
| `OPENAI_MODEL` | Alternative: OpenAI model | `gpt-5.4` |
| `SCENE_THRESHOLD` | Scene detection sensitivity | `27.0` (default) |
| `BEST_SHOT_THRESHOLD` | Best shots threshold | `7.5` (default) |

## 📊 Scoring System

### Five Dimensions

| Dimension | Weight | What It Measures |
|-----------|--------|------------------|
| 🎨 **Aesthetic Beauty** 美感 | 20% | Composition (rule of thirds), lighting, color harmony |
| 🎭 **Credibility** 可信度 | 20% | Authenticity, natural performance, physical logic |
| 💥 **Impact** 冲击力 | 20% | Visual saliency, dynamic tension, first-glance draw |
| 🧠 **Memorability** 记忆度 | 20% | Unique visual symbols, Von Restorff Effect |
| 😄 **Fun / Interest** 趣味度 | 20% | Engagement, entertainment, social currency potential |

### Dynamic Weighting by Scene Type

| Scene Type | Primary Weights | Typical Content |
|------------|----------------|-----------------|
| ⚡ **TYPE-A Hook** | Impact 40% + Memorability 30% | Opening hooks, high-energy moments |
| 📖 **TYPE-B Narrative** | Credibility 40% + Memorability 30% | Story segments, emotional scenes |
| 🎨 **TYPE-C Aesthetic** | Aesthetics 50% + Sync 30% | B-roll, atmosphere shots |
| 🛍️ **TYPE-D Commercial** | Credibility 40% + Memorability 40% | Product showcases, ads |

### Selection Levels

| Level | Criteria | Usage |
|-------|----------|-------|
| 🌟 **MUST KEEP** | Score ≥ 8.5 or any dimension = 10 | Core material |
| 📁 **USABLE** | 7.0 ≤ Score < 8.5 | Supporting shots |
| 🗑️ **DISCARD** | Score < 7.0 | Not recommended |

## 🎯 Video Type Classification (Dual-Axis Routing)

VNext classifies every video along two axes before selecting a specialized analysis template:

### Visual Source Axis

| Code | Type | Description |
|------|------|-------------|
| **R** | Reality | Original live-action footage |
| **P** | Performance | Original staged/acted footage |
| **S** | Secondary | Derivative / remix footage |
| **D** | Design | Motion graphics / animated |
| **H** | Hybrid | Mixed visual sources |

### Audio Dominance Axis

| Code | Type | Description |
|------|------|-------------|
| **L** | Language-led | Dialogue / narration driven |
| **M** | Music-led | Music / rhythm driven |
| **E** | SFX / Meme-led | Sound effects / meme audio |
| **LM** | Language + Music | Both equally present |
| **N** | Weak Audio | Minimal audio participation |

### Route Framework Families

The 25 axis combinations map to specialized analysis frameworks grouped into 4 families:

| Family | Frameworks | Focus Areas |
|--------|------------|-------------|
| 📖 **Narrative** | narrative_performance, documentary_generic, commentary_mix, lecture_performance, hybrid_commentary, narrative_mix, hybrid_narrative | Story structure, dialogue, argument, credibility |
| 🌊 **Atmospheric** | mix_music, concept_mv, cinematic_life, hybrid_music, hybrid_ambient, pure_visual_mix, silent_reality, silent_performance, narrative_mix | Rhythm, mood, visual poetry, music sync |
| 😂 **Meme** | meme, hybrid_meme, reality_sfx, abstract_sfx | Timing, subculture markers, comedic intent |
| 🎨 **Graphic** | pure_motion_graphics, infographic_animation, narrative_motion_graphics | Flow analysis, information hierarchy, transition coherence |

## 📊 Audiovisual Analysis Methodology

The audiovisual report goes far beyond simple scoring — it provides a **route-specific deep analysis** tailored to the video's classified type:

### Analysis Process

```
Video → Scene Detection → Frame Extraction → Vision Scoring
  → Video Type Classification (dual-axis routing)
    → Route-specific Template Selection
      → Multi-section Deep Analysis (≥700 chars/section, ≥3 scene refs)
        → SVG Structural Diagram (or MV Overview JSON)
          → Screenshot-illustrated Final Report
```

### What the Report Covers

| Component | Content |
|-----------|---------|
| 📝 **Body Analysis** | Route-specific multi-section deep analysis: narrative structure, rhythm patterns, mood architecture, comedic timing, information flow, etc. Each section references specific scenes with timestamps |
| 📊 **Structural Diagram** | SVG visualization of the video's architecture — scene groupings, emotional arcs, rhythm maps, or information flow depending on type |
| 🖼️ **Illustrated Report** | Key screenshots embedded at analysis anchors, connecting visual evidence to written insights |
| 🎯 **Highlight Specs** | Best shot recommendations per route type with reasoning |
| ⚠️ **Failure Risk** | Route-specific risk assessment (e.g., pacing issues, credibility gaps, rhythm breaks) |

### Quality Gates

| Metric | Minimum |
|--------|---------|
| Characters per `##` section | ≥ 700 |
| Characters per `###` subsection | ≥ 180 |
| Scene references per `##` section | ≥ 3 |

## 📁 Output Structure

```
<output_root>/<video_name>/
│
├── 📹 Media
│   ├── <video>.mp4                       # Full video
│   ├── <video>.m4a                       # Audio track
│   └── <video>.srt                       # Subtitles (4-tier fallback)
│
├── 📊 Core Data
│   ├── scene_scores.json                 # Master scene analysis data
│   ├── run_state.json                    # Pipeline state (for resume)
│   ├── classification_result.json        # Video type routing result
│   └── delivery_report.json              # Final validation report
│
├── 📋 Reports
│   ├── *_storyboard.md / .pdf            # Standardized storyboard table
│   ├── *_audiovisual_analysis.md / .pdf  # Multi-dimensional audiovisual report
│   ├── *_detailed_analysis.md            # Detailed analysis
│   ├── *_complete_analysis.md            # Complete analysis with metadata
│   └── *_classification_summary.md/.json # Video type classification
│
├── 🎬 Scenes
│   ├── scenes/                           # Scene clips
│   │   └── best_shots/                   # Auto-selected highlights
│   └── frames/                           # Preview frames
│
├── 📦 Batch Workspace
│   └── host_batches/
│       ├── index.json                    # Batch index
│       ├── batch-XXX-contact-sheet.png   # Frame preview grid
│       ├── batch-XXX-input.json          # Input packet
│       └── batch-XXX-output.json         # Scored results
│
└── 🎨 Audiovisual Handoff
    └── audiovisual_handoff/
        ├── brief.md                      # Analysis brief
        ├── body/task.md → output.md      # Deep analysis
        ├── diagram/task.md → output.svg  # Structural diagram
        └── illustrate/task.md → output.md # Illustrated report
```

## 🔧 Configuration

### First-Run Setup

On first run, the orchestrator will ask for three things:

| Setting | Description | Default |
|---------|-------------|---------|
| 📂 **Output directory** | Root folder for all analyses | `~/Downloads/video-analysis` |
| 🌐 **Report language** | Language for final reports (ISO code) | `zh-CN` |
| 🤖 **Model preference** | Vision/text model selection | Auto-detect (OpenClaw → env vars) |

Settings are persisted to `<output_root>/vnext_config.json` — you won't be asked again.

### Pipeline Options

| Option | Description |
|--------|-------------|
| `--setup` | Configure output directory |
| `--scene-threshold` | Scene detection sensitivity (default: 27) |
| `--best-threshold` | Best shots threshold (default: 7.5) |
| `--dispatch-json` | OpenClaw relay mode |
| `-o, --output` | Output directory |

## 📚 Theory Background

Based on **Walter Murch's Six Rules of Editing**:

> 🎬 Emotion > Story > Rhythm > Eye-trace > 2D Plane > 3D Space

A shot with genuine emotion but slight shake is better than a perfect but empty frame.

## 🙏 Credits

| Tool | Purpose |
|------|---------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Video download |
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | Scene detection |
| [FFmpeg](https://ffmpeg.org/) | Media processing |
| [FunASR](https://github.com/modelscope/FunASR) | Chinese speech recognition |
| [mlx-whisper](https://github.com/ml-explore/mlx-examples) | Local ASR (Apple Silicon) |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | Burned subtitle OCR |

## 📖 References

### Core Theory

1. **Murch, W.** (2001). *In the Blink of an Eye* (2nd ed.). Silman-James Press.
2. **Murch, W.** (1995). *The Conversations*. Knopf.

### Psychology & Cognitive Science

3. **Von Restorff, H.** (1933). *Psychologische Forschung*, 18(1), 299-342.
4. **Itti, L., & Koch, C.** (2001). *Nature Reviews Neuroscience*, 2(3), 194-203.
5. **Kahneman, D.** (2011). *Thinking, Fast and Slow*. Farrar, Straus and Giroux.

### Social Media & Virality

6. **Berger, J.** (2013). *Contagious*. Simon & Schuster.
7. **Berger, J., & Milkman, K. L.** (2012). *Journal of Marketing Research*, 49(2), 192-205.

### Video & Film Analysis

8. **Bordwell, D., & Thompson, K.** (2012). *Film Art* (10th ed.). McGraw-Hill.
9. **Katz, S. D.** (1991). *Film Directing Shot by Shot*. Michael Wiese Productions.
10. **Brown, B.** (2016). *Cinematography: Theory and Practice* (3rd ed.). Routledge.

---

# 🎬 视频专家分析器 VNext

> **新一代** AI 驱动的专业视频分析工具 — 在 [v2.x](https://github.com/ALBEDO-TABAI/video-expert-analyzer) 基础上全面升级，新增**标准分镜表**、**多维度视听剖析报告**，以及面向长视频的**可续跑并行流水线**。

## 🆕 VNext 相比 v2.x 的升级

| 方面 | v2.x | **VNext** |
|------|------|-----------|
| 📋 **分镜表** | 基础场景列表 | **标准分镜表** — 逐场景记录景别、灯光、运镜、画风、手法、旁白、画面文字、截图 |
| 📊 **视听报告** | 五维评分报告 | **多维度视听剖析** — 4 大家族 25 条分析路线，按视频类型匹配专属模板，含 SVG 结构图 |
| 🔄 **流程** | 单次执行，中断需重来 | **可续跑分段流水线** — prepare → score → merge → finalize，`run_state.json` 断点续跑 |
| ⚡ **性能** | 逐场景串行评分 | **并行批次评分** — 可配置并发数（默认 4），视觉 API 调用同时执行 |
| 🎯 **视频路由** | 4 种场景类型 | **19 种视频类型** — 双轴路由（5 视觉来源 × 5 听觉主导 = 25 条路线组合） |
| 🤖 **模型支持** | Gemini / Kimi / Claude | 视觉分析实测 **GPT-5.4、Kimi K2.6、GLM-5v-turbo、Xiaomi-v2-omni**；报告生成实测 **K2.6、GLM-5.1、Xiaomi-v2-pro** |
| 🔗 **编排** | 仅单机 | **OpenClaw 接力模式** — 主控 + 批次 worker 串行接力 |

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| 🤖 **真实 AI 视觉评分** | 多模态大模型分析真实画面内容 — 不抽样，不猜测 |
| 📋 **标准分镜表** | 逐场景结构化表格：景别 / 灯光 / 运镜 / 画风 / 手法 / 旁白 / 画面文字 |
| 📊 **多维度视听剖析** | 按视频类型匹配分析路线，每节 ≥700 字、≥3 处场景引用 |
| ⚡ **并行批次评分** | 画面帧并行发送到 AI 供应商，自动重试和超时检测 |
| 🔄 **可续跑流水线** | 崩溃安全的分段执行 — 自动从上次中断处继续 |
| 🎯 **19 类视频分类器** | 双轴路由（视觉来源 × 听觉主导）映射到专属分析模板 |
| 🎤 **智能字幕提取** | 四级降级：平台 API → 内嵌字幕 → RapidOCR → FunASR/mlx-whisper |
| ⭐ **精选镜头** | 自动筛选高分片段（≥7.5）到 `best_shots/` |
| 🌐 **多语言报告** | 支持指定报告语言（zh-CN、en-US、ja-JP 等） |

## 📱 支持平台

| 平台 | 支持状态 | 说明 |
|------|---------|------|
| 🎬 **Bilibili** | ✅ 完全支持 | yt-dlp 下载 + B站 API 字幕 |
| 📺 **YouTube** | ✅ 完全支持 | yt-dlp 下载 |
| 🎵 **抖音 (Douyin)** | ✅ 完全支持 | 专用下载器（分享链接无需 cookie） |
| 📕 **小红书 (Xiaohongshu)** | ✅ 完全支持 | 专用下载器 |
| 🌍 **其他平台** | ⚠️ 可能支持 | 取决于 yt-dlp 支持情况 |

## 🤖 模型兼容性

### 视觉分析（场景评分）

> 用于逐帧分析五维评分的视觉模型。

| 模型 | 状态 | 说明 |
|------|------|------|
| **GPT-5.4** | ✅ 已测试 | 视觉理解能力强 |
| **Kimi K2.6** | ✅ 已测试 | 中文语境优秀 |
| **GLM-5v-turbo** | ✅ 已测试 | 速度快，性价比高 |
| **Xiaomi-v2-omni** | ✅ 已测试 | 多模态能力扎实 |
| 其他兼容 OpenAI 的视觉模型 | ⚠️ 可能可用 | 需支持图像输入 |
| 纯文本模型 | ❌ 不可用 | 无视觉能力 |

### 报告生成（视听剖析）

> 用于合成最终多维度视听报告的文本模型。

| 模型 | 状态 | 说明 |
|------|------|------|
| **Kimi K2.6** | ✅ 已测试 | 中文输出丰富，推理能力强 |
| **GLM-5.1** | ✅ 已测试 | 结构清晰，连贯性好 |
| **Xiaomi-v2-pro** | ✅ 已测试 | 细节丰富，分析深入 |
| 其他强文本模型 | ⚠️ 可能可用 | 需长上下文能力 |

## ⚡ 性能与批次处理

视觉分析阶段将画面帧以**并行批次**方式发送到 AI 供应商，而非串行逐个处理：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| **批次大小** | 6 场景/批 | 每次 API 调用包含的场景数 |
| **并行数** | 4 个 worker | 同时进行的 API 调用数 |
| **超时阈值** | 30 分钟 | 自动重试挂起批次的阈值 |

### 📐 性能基准参考

| 视频时长 | 场景数 | 预计耗时 | 说明 |
|---------|--------|---------|------|
| **3 分 40 秒** | ~155 个镜头 | **40 – 110 分钟** | 取决于电脑性能、网络质量和 AI 供应商处理效率 |

> ⚠️ **提高并行数前**，请确认你的 AI 供应商没有最大并行请求限制。部分供应商有严格的并发上限。

影响速度的因素：
- 💻 **本地硬件** — 帧提取和联系表生成
- 🌐 **网络质量** — 帧图片上传速度
- 🤖 **AI 供应商吞吐** — 模型响应时间和队列深度

## 🚀 快速开始

### 环境准备

```bash
# 系统依赖
brew install ffmpeg          # macOS
# sudo apt install ffmpeg    # Ubuntu/Debian

# 安装 Python 依赖
pip3 install -r requirements.txt
```

### 一键分析

```bash
# 分析任意视频（自动识别平台）
python3 scripts/orchestrate_vnext.py "https://www.bilibili.com/video/BV1xxxxx"
python3 scripts/orchestrate_vnext.py "https://www.douyin.com/video/xxxxx"
python3 scripts/orchestrate_vnext.py /path/to/本地视频.mp4

# 从上次中断处续跑
python3 scripts/orchestrate_vnext.py /path/to/scene_scores.json
```

### 分步执行（进阶）

```bash
# 1. 准备：下载、场景检测、字幕提取
python3 scripts/pipeline_enhanced.py "<视频链接>"

# 2. 评分：并行批次视觉分析
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode score_batches

# 3. 合并：汇总批次结果、校验
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode merge_validate

# 4. 收尾：生成分镜表 + 视听报告
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode finalize
```

### 环境变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `VIDEO_ANALYZER_API_KEY` | 视觉模型 API key | `sk-xxx` |
| `VIDEO_ANALYZER_BASE_URL` | API 端点 | `https://api.openai.com/v1` |
| `VIDEO_ANALYZER_MODEL` | 视觉模型名 | `gpt-5.4` |
| `OPENAI_API_KEY` | 备选：OpenAI key | `sk-xxx` |
| `OPENAI_MODEL` | 备选：OpenAI 模型 | `gpt-5.4` |
| `SCENE_THRESHOLD` | 场景检测灵敏度 | `27.0`（默认） |
| `BEST_SHOT_THRESHOLD` | 精选阈值 | `7.5`（默认） |

## 📊 评分体系

### 五维评分

| 维度 | 权重 | 评估要点 |
|------|------|---------|
| 🎨 **美感 (Aesthetic)** | 20% | 构图（三分法）、光影质感、色彩和谐度 |
| 🎭 **可信度 (Credibility)** | 20% | 表演自然度、物理逻辑、无出戏感 |
| 💥 **冲击力 (Impact)** | 20% | 视觉显著性、动态张力、第一眼吸引力 |
| 🧠 **记忆度 (Memorability)** | 20% | 独特视觉符号、冯·雷斯托夫效应 |
| 😄 **趣味度 (Fun)** | 20% | 参与感、娱乐价值、社交货币潜力 |

### 场景类型动态权重

| 场景类型 | 主要权重 | 典型内容 |
|---------|---------|---------|
| ⚡ **TYPE-A Hook** | 冲击力 40% + 记忆度 30% | 开头 Hook、高能时刻 |
| 📖 **TYPE-B 叙事** | 可信度 40% + 记忆度 30% | 故事段落、情感场景 |
| 🎨 **TYPE-C 氛围** | 美感 50% + 节奏 30% | B-roll、氛围镜头 |
| 🛍️ **TYPE-D 商业** | 可信度 40% + 记忆度 40% | 产品展示、广告 |

### 筛选等级

| 等级 | 标准 | 用途 |
|------|------|------|
| 🌟 **MUST KEEP** | 加权总分 ≥ 8.5 或单项 = 10 | 核心素材 |
| 📁 **USABLE** | 7.0 ≤ 总分 < 8.5 | 辅助素材 |
| 🗑️ **DISCARD** | 总分 < 7.0 | 建议舍弃 |

## 🎯 视频类型分类（双轴路由）

VNext 对每个视频沿两个轴进行分类，然后选择对应的专属分析模板：

### 视觉来源轴

| 编码 | 类型 | 说明 |
|------|------|------|
| **R** | 现实拍摄 | 原创现实拍摄 |
| **P** | 演绎拍摄 | 原创导演/表演拍摄 |
| **S** | 二创素材 | 衍生 / 混剪素材 |
| **D** | 设计制作 | 动态图形 / 动画 |
| **H** | 混合型 | 多种视觉来源混合 |

### 听觉主导轴

| 编码 | 类型 | 说明 |
|------|------|------|
| **L** | 语言主导 | 对白 / 旁白驱动 |
| **M** | 音乐主导 | 音乐 / 节奏驱动 |
| **E** | 音效/梗音 | 音效 / 梗音驱动 |
| **LM** | 语言+音乐 | 两者并重 |
| **N** | 弱听觉 | 听觉参与度低 |

### 路线家族

25 种轴组合映射到 4 大家族的专属分析框架：

| 家族 | 包含框架 | 分析侧重 |
|------|---------|---------|
| 📖 **叙事家族** | narrative_performance, documentary_generic, commentary_mix, lecture_performance, hybrid_commentary, narrative_mix, hybrid_narrative | 叙事结构、对白、论证、可信度 |
| 🌊 **氛围家族** | mix_music, concept_mv, cinematic_life, hybrid_music, hybrid_ambient, pure_visual_mix, silent_reality, silent_performance, narrative_mix | 节奏、情绪、视觉诗意、音画同步 |
| 😂 **梗视频家族** | meme, hybrid_meme, reality_sfx, abstract_sfx | 节奏时机、亚文化标记、喜剧意图 |
| 🎨 **图形家族** | pure_motion_graphics, infographic_animation, narrative_motion_graphics | 运动流分析、信息层级、转场连贯性 |

## 📊 视听剖析方法论

视听报告远不止简单评分 — 它提供**按视频类型定制的深度分析**：

### 分析流程

```
视频 → 场景检测 → 帧提取 → 视觉评分
  → 视频类型分类（双轴路由）
    → 选择匹配的分析模板
      → 多章节深度分析（每节 ≥700 字、≥3 处场景引用）
        → SVG 结构图（或 MV 总览 JSON）
          → 配图最终报告
```

### 报告包含内容

| 组件 | 内容 |
|------|------|
| 📝 **主体分析** | 按视频类型定制的多章节深度分析：叙事结构、节奏模式、情绪建构、喜剧时机、信息流等，每节引用具体场景和时间码 |
| 📊 **结构图** | SVG 可视化 — 场景分组、情绪弧线、节奏图谱或信息流向（因类型而异） |
| 🖼️ **配图报告** | 关键截图嵌入分析锚点，将视觉证据与文字洞察关联 |
| 🎯 **精选推荐** | 按路线类型推荐最佳镜头及理由 |
| ⚠️ **风险评估** | 路线特定的问题评估（如节奏断裂、可信度缺口、韵律中断） |

### 质量门禁

| 指标 | 最低要求 |
|------|---------|
| 每个 `##` 章节字数 | ≥ 700 字 |
| 每个 `###` 子节字数 | ≥ 180 字 |
| 每个 `##` 章节场景引用数 | ≥ 3 处 |

## 📁 输出结构

```
<输出根目录>/<视频名>/
│
├── 📹 媒体文件
│   ├── <video>.mp4                       # 完整视频
│   ├── <video>.m4a                       # 音频轨
│   └── <video>.srt                       # 字幕（四级降级）
│
├── 📊 核心数据
│   ├── scene_scores.json                 # 场景分析主数据
│   ├── run_state.json                    # 流水线状态（用于续跑）
│   ├── classification_result.json        # 视频类型路由结果
│   └── delivery_report.json              # 最终校验报告
│
├── 📋 报告
│   ├── *_storyboard.md / .pdf            # 标准分镜表
│   ├── *_audiovisual_analysis.md / .pdf  # 多维度视听剖析报告
│   ├── *_detailed_analysis.md            # 详细分析
│   ├── *_complete_analysis.md            # 完整分析（含元数据）
│   └── *_classification_summary.md/.json # 视频类型分类摘要
│
├── 🎬 场景
│   ├── scenes/                           # 场景片段
│   │   └── best_shots/                   # 自动精选片段
│   └── frames/                           # 预览帧
│
├── 📦 批次工作区
│   └── host_batches/
│       ├── index.json                    # 批次索引
│       ├── batch-XXX-contact-sheet.png   # 帧预览网格
│       ├── batch-XXX-input.json          # 输入包
│       └── batch-XXX-output.json         # 评分结果
│
└── 🎨 视听交接区
    └── audiovisual_handoff/
        ├── brief.md                      # 分析简报
        ├── body/task.md → output.md      # 深度分析
        ├── diagram/task.md → output.svg  # 结构图
        └── illustrate/task.md → output.md # 配图报告
```

## 🔧 配置

### 首次运行引导

首次运行时，编排器会询问三项设置：

| 设置项 | 说明 | 默认值 |
|--------|------|--------|
| 📂 **输出目录** | 所有分析结果的根目录 | `~/Downloads/video-analysis` |
| 🌐 **报告语言** | 最终报告语言（ISO 码） | `zh-CN` |
| 🤖 **模型偏好** | 视觉/文本模型选择 | 自动检测（OpenClaw → 环境变量） |

设置持久化到 `<输出根目录>/vnext_config.json` — 不会重复询问。

### 流水线选项

| 选项 | 说明 |
|------|------|
| `--setup` | 配置输出目录 |
| `--scene-threshold` | 场景检测阈值（默认: 27） |
| `--best-threshold` | 精选阈值（默认: 7.5） |
| `--dispatch-json` | OpenClaw 接力模式 |
| `-o, --output` | 输出目录 |

## 📚 理论背景

基于 **Walter Murch 剪辑六法则**：

> 🎬 情感 > 故事 > 节奏 > 视线追踪 > 2D 平面 > 3D 空间

一个情感真挚但画面略抖的镜头，优于一个画面完美但内容空洞的镜头。

## 🙏 致谢

| 工具 | 用途 |
|------|------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 视频下载 |
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | 场景检测 |
| [FFmpeg](https://ffmpeg.org/) | 媒体处理 |
| [FunASR](https://github.com/modelscope/FunASR) | 中文语音识别 |
| [mlx-whisper](https://github.com/ml-explore/mlx-examples) | 本地 ASR（Apple Silicon） |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | 烧录字幕 OCR |

## 📖 参考文献

### 核心理论

1. **Murch, W.** (2001). *In the Blink of an Eye* (2nd ed.). Silman-James Press.
2. **Murch, W.** (1995). *The Conversations*. Knopf.

### 心理学与认知科学

3. **Von Restorff, H.** (1933). *Psychologische Forschung*, 18(1), 299-342.
4. **Itti, L., & Koch, C.** (2001). *Nature Reviews Neuroscience*, 2(3), 194-203.
5. **Kahneman, D.** (2011). *Thinking, Fast and Slow*. Farrar, Straus and Giroux.

### 社交媒体与传播

6. **Berger, J.** (2013). *Contagious*. Simon & Schuster.
7. **Berger, J., & Milkman, K. L.** (2012). *Journal of Marketing Research*, 49(2), 192-205.

### 视频与电影分析

8. **Bordwell, D., & Thompson, K.** (2012). *Film Art* (10th ed.). McGraw-Hill.
9. **Katz, S. D.** (1991). *Film Directing Shot by Shot*. Michael Wiese Productions.
10. **Brown, B.** (2016). *Cinematography: Theory and Practice* (3rd ed.). Routledge.

---

## 📜 License

MIT License — 自由使用和修改 / Free to use and modify
