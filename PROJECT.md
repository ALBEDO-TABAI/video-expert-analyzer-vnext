[![Version](https://img.shields.io/badge/version-3.0.0-blue)](.) [![License](https://img.shields.io/badge/license-MIT-green)](.) [![Python](https://img.shields.io/badge/python-3.9+-yellow)](.) [![AI Models](https://img.shields.io/badge/AI-Claude%20%7C%20Gemini%20%7C%20GPT--4o%20%7C%20Kimi-purple)](.)

**Language / 语言**  
[English](#english) | [中文](#中文)

---

<a id="english"></a>

# Video Expert Analyzer VNext

> Long-task-oriented video analysis skill with **resumable staged execution**, automatic parallel scoring, OpenClaw orchestration support, and comprehensive audiovisual analysis — built for Claude Code as a `/vea` skill.

## What's New in VNext

| Aspect | v2 (Legacy) | VNext |
|--------|-------------|-------|
| **Execution model** | Single-pass, restarts on failure | Resumable multi-stage pipeline |
| **Scoring** | Manual per-batch or single API call | Automatic parallel scoring with batch management |
| **Long videos** | Context blowup on 50+ scenes | Batched processing, state files, incremental progress |
| **OpenClaw** | Not supported | First-class main-controller + worker relay |
| **Audiovisual analysis** | N/A | Full audiovisual report with agent handoff (body/diagram/overview/illustrate) |
| **Storyboard** | Basic | Enriched storyboard with PDF export |
| **Delivery validation** | Trust oral report | Machine-verified `delivery_report.json` |

## Features

- **Resumable Pipeline** — Prepare → Score Batches → Merge/Validate → Finalize. Crash at any stage? Pick up exactly where you left off via `run_state.json`.
- **Automatic Parallel Scoring** — Vision models score every scene in parallel batches; no manual per-batch intervention required.
- **Zero Sampling** — Every scene is analyzed. No skipping, no guessing on unseen frames.
- **OpenClaw Orchestration** — Serial relay mode: one main controller + one current-batch worker. Dispatch packets generated automatically.
- **Audiovisual Analysis with Agent Handoff** — Long-form audiovisual reports are written by the hosting agent via structured task packets (`body` → `diagram`/`overview` → `illustrate`), with machine validation on word counts, section coverage, and screenshot references.
- **Smart Subtitle Extraction** — 4-tier fallback: Bilibili API → Embedded subtitles → RapidOCR → FunASR/mlx-whisper.
- **Multi-language Final Reports** — Processing always runs in Chinese; final deliverables are rewritten to the user's chosen language post-finalize.
- **Delivery Verification** — Completion is determined by `delivery_report.json` and actual output files, not by oral summary.

## Supported Platforms

| Platform | Status | Notes |
|----------|--------|-------|
| **Bilibili** | Full support | yt-dlp download + Bilibili API subtitles |
| **YouTube** | Full support | yt-dlp download |
| **Douyin** | Full support | Dedicated downloader, no browser cookies needed |
| **Xiaohongshu** | Full support | Dedicated downloader |
| **Local files** | Full support | Any video file FFmpeg can decode |
| **Others** | May work | Depends on yt-dlp support |

## Pipeline Stages

```
User Input (video URL / local file / existing scene_scores.json)
    │
    ▼
┌─────────────────────────────────────────────┐
│  0. Orchestrator  (orchestrate_vnext.py)     │
│     Reads vnext_config.json, routes to the   │
│     correct stage, handles resume logic      │
└──────────────────┬──────────────────────────┘
                   │
    ▼──────────────┘
┌─────────────────────────────────────────────┐
│  1. Prepare  (pipeline_enhanced.py)          │
│     Download → Scene detection → Frame       │
│     extraction → Subtitle extraction →       │
│     Initialize scene_scores.json &           │
│     run_state.json                           │
└──────────────────┬──────────────────────────┘
                   │
    ▼──────────────┘
┌─────────────────────────────────────────────┐
│  2. Score Batches  (ai_analyzer.py)          │
│     Auto-discover model config →             │
│     Parallel vision scoring per batch →      │
│     Write batch-XXX-output.json              │
└──────────────────┬──────────────────────────┘
                   │
    ▼──────────────┘
┌─────────────────────────────────────────────┐
│  3. Merge / Validate  (ai_analyzer.py)       │
│     Merge batch results → Check coverage →   │
│     Fix stale resource paths → Backfill      │
│     missing screenshots                      │
└──────────────────┬──────────────────────────┘
                   │
    ▼──────────────┘
┌─────────────────────────────────────────────┐
│  4. Finalize  (ai_analyzer.py)               │
│     Generate reports → Classification        │
│     summary → Audiovisual handoff →          │
│     Storyboard → Delivery validation         │
└──────────────────┬──────────────────────────┘
                   │
    ▼──────────────┘
┌─────────────────────────────────────────────┐
│  4.1 Audiovisual Agent Handoff               │
│     body → diagram/overview → illustrate     │
│     (completed by the hosting agent,         │
│      then re-run finalize)                   │
└─────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

```bash
# System dependency
brew install ffmpeg          # macOS
# apt install ffmpeg         # Linux

# Python dependencies
pip3 install -r requirements.txt

# Verify environment
python3 scripts/check_environment.py
```

### As a Claude Code Skill

Install this directory as a Claude Code skill. Then invoke with:

```
/vea https://www.bilibili.com/video/BV1xxxxx
/vea /path/to/local-video.mp4
/vea /path/to/existing/scene_scores.json    # resume
```

### Standalone CLI

```bash
# Full pipeline (new video)
python3 scripts/orchestrate_vnext.py "https://www.bilibili.com/video/BV1xxxxx"

# Resume from existing state
python3 scripts/orchestrate_vnext.py /path/to/scene_scores.json

# Individual stages
python3 scripts/pipeline_enhanced.py "<video URL or local file>"
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode score_batches
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode merge_validate
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode finalize
```

### OpenClaw Relay Mode

```bash
python3 scripts/orchestrate_vnext.py /path/to/scene_scores.json --dispatch-json
```

## First-Run Configuration

On the first run with a new video, the skill asks three questions (all at once):

1. **Output root directory** — Where to store results. Each video gets a subdirectory.
2. **Report language** — For the four final report types (`*_storyboard.*`, `*_audiovisual_analysis.*`, `*_detailed_analysis.md`, `*_complete_analysis.md`). Intermediate artifacts stay in Chinese.
3. **Model preference** — OpenClaw models, your own API key, or auto-discovery.

Answers are persisted to `<output_root>/vnext_config.json` so you're never asked twice.

## Scoring System

### Five Dimensions

| Dimension | Weight | What It Measures |
|-----------|--------|------------------|
| **Aesthetic Beauty** | 20% | Composition, lighting, color harmony |
| **Credibility** | 20% | Authenticity, natural performance |
| **Impact** | 20% | Visual saliency, attention-grabbing power |
| **Memorability** | 20% | Uniqueness, Von Restorff distinctiveness |
| **Fun/Interest** | 20% | Engagement, entertainment, social currency |

### Dynamic Scene Weighting

| Scene Type | Primary Weights | Typical Use |
|------------|-----------------|-------------|
| **TYPE-A Hook** | Impact 40% + Memorability 30% | Opening hooks, high-energy moments |
| **TYPE-B Narrative** | Credibility 40% + Memorability 30% | Story segments, emotional scenes |
| **TYPE-C Aesthetic** | Aesthetics 50% + Sync 30% | B-roll, atmosphere shots |
| **TYPE-D Commercial** | Credibility 40% + Memorability 40% | Product showcases, ads |

### Selection Levels

| Level | Criteria | Usage |
|-------|----------|-------|
| **MUST KEEP** | Score >= 8.5 or any dimension = 10 | Core material |
| **USABLE** | 7.0 <= Score < 8.5 | Supporting shots |
| **DISCARD** | Score < 7.0 | Not recommended |

## Model Compatibility

Auto-discovery priority:

1. OpenClaw `~/.openclaw/agents/main/agent/models.json`
2. Environment variables: `ANTHROPIC_API_KEY` + `ANTHROPIC_MODEL` or `OPENAI_API_KEY` + `OPENAI_MODEL`
3. Fallback models defined in pipeline

Any vision-capable model works for scoring. Text-only models cannot score.

## Output Structure

```
<output_root>/<video_name>/
├── <video>.mp4                        # Full video
├── <video>.m4a                        # Audio track
├── <video>.srt                        # Subtitles (smart extraction)
├── scene_scores.json                  # Complete scene analysis data
├── run_state.json                     # Pipeline state for resume
├── vnext_config.json                  # User configuration
├── classification_result.json         # Video type routing result
├── delivery_report.json               # Delivery validation report
│
├── host_batches/                      # Batch processing workspace
│   ├── index.json
│   ├── batch-001-brief.md
│   ├── batch-001-contact-sheet.png
│   ├── batch-001-input.json
│   └── batch-001-output.json
│
├── scene_reports/                     # Per-scene markdown reports
│   ├── scene_001_report.md
│   └── ...
│
├── scenes/
│   └── best_shots/                    # Auto-selected highlight frames
│
├── *_storyboard.md / .pdf             # Storyboard export
├── *_storyboard_context.*             # Storyboard enrichment data
├── *_detailed_analysis.md             # Detailed analysis report
├── *_complete_analysis.md             # Complete analysis with metadata
├── *_classification_summary.md / .json # Lightweight type classification
├── *_audiovisual_analysis.md / .pdf   # Audiovisual analysis report
│
└── audiovisual_handoff/               # Agent handoff task packets
    ├── brief.md
    ├── receipt.json
    ├── body/
    │   ├── task.md
    │   └── output.md
    ├── diagram/                       # or overview/ (mutually exclusive)
    │   ├── task.md
    │   └── output.svg
    └── illustrate/
        ├── task.md
        └── output.md
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENCLAW_ROOT` | `~/.openclaw` | Override OpenClaw root directory |
| `OPENCLAW_MODELS_JSON` | `$OPENCLAW_ROOT/agents/main/agent/models.json` | Override models.json path |
| `VNEXT_STALE_MINUTES` | `30` | Minutes before a stale worker is reset to pending |
| `VNEXT_TEXT_MODEL_RETRIES` | `2` | Retry count for transient text model errors |
| `AUDIOVISUAL_REPORT_MAX_TOKENS` | — | Token limit for audiovisual report generation |
| `AUDIOVISUAL_REPORT_MODEL` | — | Model override for audiovisual reports |

## Project Structure

```
video-expert-analyzer-vnext/
├── SKILL.md                           # Skill manifest (rules for the hosting agent)
├── README.md                          # Quick-start reference
├── PROJECT.md                         # This document
├── pyproject.toml                     # Python project metadata
├── requirements.txt                   # Dependencies
├── .env.example                       # Environment variable template
│
├── scripts/
│   ├── orchestrate_vnext.py           # Top-level orchestrator
│   ├── pipeline_enhanced.py           # Prepare stage
│   ├── ai_analyzer.py                 # Score / Merge / Finalize stages
│   ├── host_batching.py               # Batch management & recovery
│   ├── run_state.py                   # Atomic state file management
│   ├── openclaw_dispatch.py           # OpenClaw dispatch packet builder
│   ├── storyboard_generator.py        # Storyboard enrichment & export
│   ├── detailed_report_builder.py     # Detailed report generation
│   ├── classification_summary.py      # Lightweight classification summary
│   ├── delivery_validation.py         # Final delivery validation & PDF
│   ├── motion_analysis.py             # Frame extraction & FFmpeg utils
│   ├── scoring_helper_enhanced.py     # Image analysis & scoring logic
│   ├── text_model_runtime.py          # Text model request wrapper
│   ├── video_type_router_runtime.py   # Video classification & routing
│   ├── extract_subtitle_funasr.py     # ASR subtitle extraction
│   ├── fetch_bilibili_subtitle.py     # Bilibili subtitle fetching
│   ├── download_douyin.py             # Douyin video download
│   ├── xiaohongshu_downloader.py      # Xiaohongshu video download
│   ├── lyric_ocr_refiner.py           # Music lyric OCR & correction
│   ├── check_environment.py           # Environment checker
│   │
│   └── audiovisual/                   # Audiovisual analysis sub-module
│       ├── routing/
│       │   ├── infer.py               # Video type inference
│       │   ├── features.py            # Feature extraction
│       │   ├── enrich.py              # Feature enrichment
│       │   └── constants.py           # Routing constants
│       └── reporting/
│           ├── builder.py             # Audiovisual report orchestrator
│           ├── template_engine.py     # Markdown synthesis engine
│           ├── handoff.py             # Agent handoff coordinator
│           ├── common.py              # Shared analysis utilities
│           ├── raw_prompt_adapter.py  # Prompt management
│           ├── scene_utils.py         # Scene data utilities
│           ├── markdown.py            # Markdown helpers
│           ├── mv_overview.py         # MV content architecture
│           └── pdf.py                 # PDF rendering
│
├── templates/
│   ├── report_template.md             # Report markdown template
│   └── detailed_report_template.md    # Detailed analysis template
│
├── docs/
│   ├── openclaw_orchestration.md      # OpenClaw relay rules
│   └── appendices.md                  # Platform quirks, OCR, routing, recovery
│
└── tests/                             # 25+ test files
    ├── test_orchestrate_vnext.py
    ├── test_ai_analyzer.py
    ├── test_audiovisual_template_engine.py
    ├── test_host_batching_recovery.py
    ├── test_openclaw_dispatch.py
    ├── test_e2e_pipeline.py
    └── ...
```

## Dependencies

| Category | Packages |
|----------|----------|
| **Video processing** | yt-dlp, scenedetect, ffmpeg-python |
| **AI / ML** | openai, anthropic, funasr, modelscope, torch, mlx-whisper |
| **OCR & imaging** | rapidocr-onnxruntime, Pillow, numpy |
| **Network** | requests, browser_cookie3 |

## Theory Background

Based on **Walter Murch's Six Rules of Editing**:

> Emotion > Story > Rhythm > Eye-trace > 2D Plane > 3D Space

A shot with genuine emotion but slight camera shake is always preferred over a technically perfect but emotionally empty frame.

## Credits

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — Video download
- [FunASR](https://github.com/modelscope/FunASR) — Chinese speech recognition
- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) — Scene detection
- [FFmpeg](https://ffmpeg.org/) — Media processing
- [RapidOCR](https://github.com/RapidAI/RapidOCR) — Burned subtitle OCR
- [mlx-whisper](https://github.com/ml-explore/mlx-examples) — Apple Silicon accelerated ASR

---

<a id="中文"></a>

# 视频专家分析器 VNext

> 面向长任务的视频分析 skill，支持**可续跑的分段式执行**、自动并行评分、OpenClaw 编排接力和完整视听剖析 — 作为 Claude Code 的 `/vea` skill 使用。

## VNext 相比旧版的变化

| 维度 | v2（旧版） | VNext |
|------|-----------|-------|
| **执行模型** | 单次执行，失败从头来 | 可续跑的多阶段流水线 |
| **评分方式** | 手动逐批或单次 API | 自动并行评分 + 批次管理 |
| **长视频** | 50+ 场景时上下文爆炸 | 分批处理、状态文件、增量推进 |
| **OpenClaw** | 不支持 | 一等支持：主控 + 当前批次 worker 串行接力 |
| **视听剖析** | 无 | 完整视听报告 + agent 接力（body/diagram/overview/illustrate） |
| **分镜表** | 基础版 | 增强版 + PDF 导出 |
| **交付验证** | 口头汇报 | 机器校验的 `delivery_report.json` |

## 核心特性

- **可续跑流水线** — Prepare → Score Batches → Merge/Validate → Finalize。任何阶段崩溃都能通过 `run_state.json` 精确续跑。
- **自动并行评分** — 视觉模型按批次并行评分每个场景，无需人工逐批干预。
- **零抽样** — 每个场景都会被分析，不跳过、不猜测。
- **OpenClaw 编排** — 串行接力模式：一个主控 + 一个当前批次 worker，自动生成派单包。
- **视听剖析 Agent 接力** — 长文视听报告由宿主 agent 通过结构化任务包完成（`body` → `diagram`/`overview` → `illustrate`），带字数、章节覆盖和截图引用的机器校验。
- **智能字幕提取** — 四级降级：B站API → 内嵌字幕 → RapidOCR → FunASR/mlx-whisper。
- **多语言最终报告** — 处理过程始终中文；最终交付物在 finalize 后重写为用户选择的语言。
- **交付验证** — 是否完成以 `delivery_report.json` 和实际输出文件为准，不以口头汇报为准。

## 支持平台

| 平台 | 支持状态 | 说明 |
|------|--------|------|
| **Bilibili** | 完全支持 | yt-dlp 下载 + B站 API 字幕 |
| **YouTube** | 完全支持 | yt-dlp 下载 |
| **抖音** | 完全支持 | 专用下载器，无需浏览器 cookie |
| **小红书** | 完全支持 | 专用下载器 |
| **本地文件** | 完全支持 | FFmpeg 能解码的任何视频文件 |
| **其他** | 可能支持 | 取决于 yt-dlp |

## 流水线阶段

```
用户输入（视频链接 / 本地文件 / 已有 scene_scores.json）
    │
    ▼
┌─────────────────────────────────────────────┐
│  0. 总控入口  (orchestrate_vnext.py)          │
│     读取 vnext_config.json，路由到正确阶段，    │
│     处理续跑逻辑                               │
└──────────────────┬──────────────────────────┘
                   │
    ▼──────────────┘
┌─────────────────────────────────────────────┐
│  1. 准备  (pipeline_enhanced.py)              │
│     下载 → 场景检测 → 抽帧 → 字幕提取 →        │
│     初始化 scene_scores.json 和 run_state.json │
└──────────────────┬──────────────────────────┘
                   │
    ▼──────────────┘
┌─────────────────────────────────────────────┐
│  2. 批次评分  (ai_analyzer.py)                │
│     自动发现模型配置 → 并行视觉评分 →           │
│     写回 batch-XXX-output.json                │
└──────────────────┬──────────────────────────┘
                   │
    ▼──────────────┘
┌─────────────────────────────────────────────┐
│  3. 合并/校验  (ai_analyzer.py)               │
│     合并批次结果 → 检查覆盖率 → 修复资源路径 →   │
│     补抽缺失截图                               │
└──────────────────┬──────────────────────────┘
                   │
    ▼──────────────┘
┌─────────────────────────────────────────────┐
│  4. 定稿  (ai_analyzer.py)                    │
│     生成报告 → 分类摘要 → 视听剖析接力 →        │
│     分镜表 → 交付验证                          │
└──────────────────┬──────────────────────────┘
                   │
    ▼──────────────┘
┌─────────────────────────────────────────────┐
│  4.1 视听剖析 Agent 接力                       │
│     body → diagram/overview → illustrate      │
│    （由宿主 agent 完成，完成后重跑 finalize）    │
└─────────────────────────────────────────────┘
```

## 快速开始

### 环境准备

```bash
# 系统依赖
brew install ffmpeg          # macOS
# apt install ffmpeg         # Linux

# Python 依赖
pip3 install -r requirements.txt

# 检查环境
python3 scripts/check_environment.py
```

### 作为 Claude Code Skill 使用

将此目录安装为 Claude Code skill，然后用：

```
/vea https://www.bilibili.com/video/BV1xxxxx
/vea /path/to/local-video.mp4
/vea /path/to/existing/scene_scores.json    # 续跑
```

### 命令行直接使用

```bash
# 完整流水线（新视频）
python3 scripts/orchestrate_vnext.py "https://www.bilibili.com/video/BV1xxxxx"

# 从已有状态续跑
python3 scripts/orchestrate_vnext.py /path/to/scene_scores.json

# 单独执行某一阶段
python3 scripts/pipeline_enhanced.py "<视频链接或本地文件>"
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode score_batches
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode merge_validate
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode finalize
```

### OpenClaw 接力模式

```bash
python3 scripts/orchestrate_vnext.py /path/to/scene_scores.json --dispatch-json
```

## 首次使用配置

首次分析新视频时，skill 会一次性问三个问题：

1. **输出主目录** — 结果存放位置。每个视频会建子目录。
2. **报告语言** — 针对四类最终报告（`*_storyboard.*`、`*_audiovisual_analysis.*`、`*_detailed_analysis.md`、`*_complete_analysis.md`）。中间产物保持中文。
3. **模型偏好** — OpenClaw 可用模型、自有 API key、或自动发现。

回答会持久化到 `<主目录>/vnext_config.json`，下次不再重复询问。

## 评分体系

### 五维评分

| 维度 | 权重 | 评估要点 |
|------|------|--------|
| **美感 (Aesthetic)** | 20% | 构图、光影、色彩和谐 |
| **可信度 (Credibility)** | 20% | 表演自然度、物理逻辑 |
| **冲击力 (Impact)** | 20% | 视觉显著性、动态张力 |
| **记忆度 (Memorability)** | 20% | 独特视觉符号、冯·雷斯托夫效应 |
| **趣味度 (Fun)** | 20% | 参与感、娱乐价值、社交货币 |

### 动态场景权重

| 场景类型 | 主权重 | 典型场景 |
|---------|-------|---------|
| **TYPE-A Hook** | 冲击力 40% + 记忆度 30% | 开场钩子、高能时刻 |
| **TYPE-B 叙事** | 可信度 40% + 记忆度 30% | 故事段落、情感场景 |
| **TYPE-C 氛围** | 美感 50% + 同步 30% | B-roll、氛围镜头 |
| **TYPE-D 商业** | 可信度 40% + 记忆度 40% | 产品展示、广告 |

### 筛选等级

| 等级 | 标准 | 用途 |
|------|------|------|
| **MUST KEEP** | 总分 >= 8.5 或单项 = 10 | 核心素材 |
| **USABLE** | 7.0 <= 总分 < 8.5 | 辅助素材 |
| **DISCARD** | 总分 < 7.0 | 建议舍弃 |

## 输出结构

```
<主目录>/<视频名>/
├── <video>.mp4                        # 完整视频
├── <video>.m4a                        # 音频
├── <video>.srt                        # 字幕（智能提取）
├── scene_scores.json                  # 完整场景分析数据
├── run_state.json                     # 流水线状态（续跑用）
├── vnext_config.json                  # 用户配置
├── classification_result.json         # 视频类型路由结果
├── delivery_report.json               # 交付验证报告
│
├── host_batches/                      # 批次处理工作区
│   ├── index.json
│   ├── batch-001-brief.md
│   ├── batch-001-contact-sheet.png
│   ├── batch-001-input.json
│   └── batch-001-output.json
│
├── scene_reports/                     # 逐场景 Markdown 报告
│
├── scenes/
│   └── best_shots/                    # 自动筛选的精选帧
│
├── *_storyboard.md / .pdf             # 分镜表
├── *_detailed_analysis.md             # 详细分析报告
├── *_complete_analysis.md             # 含全部元数据的完整分析
├── *_classification_summary.*         # 轻量分类摘要
├── *_audiovisual_analysis.md / .pdf   # 视听剖析报告
│
└── audiovisual_handoff/               # Agent 接力任务包
    ├── brief.md
    ├── receipt.json
    ├── body/
    ├── diagram/ 或 overview/           # 互斥
    └── illustrate/
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|-------|------|
| `OPENCLAW_ROOT` | `~/.openclaw` | 覆盖 OpenClaw 根目录 |
| `OPENCLAW_MODELS_JSON` | `$OPENCLAW_ROOT/agents/main/agent/models.json` | 覆盖 models.json 路径 |
| `VNEXT_STALE_MINUTES` | `30` | worker 超时重置阈值（分钟） |
| `VNEXT_TEXT_MODEL_RETRIES` | `2` | 文本模型瞬时错误重试次数 |

## 依赖

| 类别 | 包 |
|------|---|
| **视频处理** | yt-dlp, scenedetect, ffmpeg-python |
| **AI / ML** | openai, anthropic, funasr, modelscope, torch, mlx-whisper |
| **OCR 与图像** | rapidocr-onnxruntime, Pillow, numpy |
| **网络** | requests, browser_cookie3 |

## 理论背景

基于 **Walter Murch 剪辑六法则**：

> 情感 > 故事 > 节奏 > 视线追踪 > 2D 平面 > 3D 空间

一个情感真挚但画面微抖的镜头，永远优于一个技术完美但内容空洞的镜头。

## 致谢

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — 视频下载
- [FunASR](https://github.com/modelscope/FunASR) — 中文语音识别
- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) — 场景检测
- [FFmpeg](https://ffmpeg.org/) — 媒体处理
- [RapidOCR](https://github.com/RapidAI/RapidOCR) — 烧录字幕识别
- [mlx-whisper](https://github.com/ml-explore/mlx-examples) — Apple Silicon 加速语音识别

---

MIT License
