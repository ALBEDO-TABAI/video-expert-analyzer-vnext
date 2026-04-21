# Video Expert Analyzer VNext

面向长视频和长任务的分段式视频分析 skill。

它保留原来的结果形态，但把流程拆成可续跑的几个阶段，并把最耗时的看图评分改成自动并行执行，减少长会话越跑越重、半路中断后只能从头再来的问题。

## 适用场景

- 公开视频或本地视频分析
- 长视频、多场景视频、需要分批处理的视频
- 场景评分、精选镜头筛选、分镜表生成
- 字幕或歌词校正
- 视听剖析报告生成

## 入口命令

优先走总控入口：

```bash
python3 scripts/orchestrate_vnext.py "<视频链接或本地视频>"
python3 scripts/orchestrate_vnext.py /path/to/scene_scores.json
```

如果只需要单独执行某一段：

```bash
python3 scripts/pipeline_enhanced.py "<视频链接或本地视频>"
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode score_batches
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode merge_validate
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode finalize
```

如果是在 OpenClaw 里跑，想把“总控 + 派单”合成一次调用，可直接用：

```bash
python3 scripts/orchestrate_vnext.py /path/to/scene_scores.json --dispatch-json
```

## 使用原则

- 不抽样，不跳过，不猜没看过的画面
- 每个场景都要独立判断并写回结果文件
- 发现已有 `scene_scores.json`、`run_state.json` 或批次结果时优先续跑
- `score_batches` 会自动找本机可用配置并直接并行评分，不再把人工逐批填写当成默认流程
- 首次优先尝试读取 OpenClaw 的 `models.json`；如果没有，再看当前环境变量里的 API 配置（支持 `OPENAI_API_KEY` + `OPENAI_MODEL`，或 `ANTHROPIC_API_KEY` + `ANTHROPIC_MODEL`）
- 如果自动找不到配置，会明确报“缺少自动评分配置”并告诉你该补什么
- 只有在全部批次完成后才进入 `finalize`
- `finalize` 生成视听剖析时，长文、SVG 结构图、MV 总览由运行 skill 的 agent 按 `audiovisual_handoff/` 任务包顺序亲自完成；脚本不再走远端文本模型，也不再有本地兜底
- 真正是否完成，以结果文件和 `delivery_report.json` 为准

## 主要结果

正常收尾后，至少应看到这些结果：

- `scene_scores.json`
- `scene_reports/`
- `*_detailed_analysis.md`
- `*_complete_analysis.md`
- `*_classification_summary.*`
- `classification_result.json`
- `*_storyboard.*`
- `*_storyboard_context.*`
- `*_audiovisual_analysis.*`
- `scenes/best_shots/`
- `delivery_report.json`

## 目录说明

- `SKILL.md`：给宿主助手的主规则
- `scripts/`：主流程、批次处理、报告生成和平台下载脚本
- `templates/`：报告模板
- `docs/openclaw_orchestration.md`：只在 OpenClaw 主控加子代理接力时再看
- `docs/appendices.md`：平台差异、歌词 OCR、视听路由、异常恢复等补充规则

## 平台说明

- Windows 下如果 `yt-dlp` 命令名不可见，仍应优先走本地 pipeline，不要擅自改成浏览器下载或录屏。
- macOS 和 Linux 也走同一套本地流程；是否启用更快的编解码能力，以当前机器的 FFmpeg 能力为准。
- 本地视频输入与公开视频链接都支持，长任务默认按可续跑方式落盘。
