---
name: vea
description: Video Expert Analyzer VNext — use when the user wants a public or local video analyzed with resumable staged execution, especially for long videos, OpenClaw handoff, multi-batch scene scoring, storyboard output, highlight selection, subtitle or lyric correction, or audiovisual analysis.
---

# Video Expert Analyzer VNext

面向长任务的视频分析 skill。目标不是改输出，而是让长视频、长会话、OpenClaw 接力这类场景更稳、更省上下文、更容易续跑，同时尽量避免漏做。

## 先看什么

先读这个文件拿到主规则。只有在确实需要时，再按需读取：

- `README.md`：整体流程与入口命令
- `docs/openclaw_orchestration.md`：只在 OpenClaw 主控 + 子代理接力时再读
- `docs/appendices.md`：平台差异、歌词 OCR、视听路由、异常恢复

## 何时用这个版本

- 用户明确提到 `video-expert-analyzer-vnext`
- 视频较长、scene 很多，或用户强调”别卡死””能续跑””省上下文”
- 需要生成场景评分、分镜表、精选镜头、字幕/歌词校正、视听剖析
- 宿主是 OpenClaw 时，支持主控加当前批次 worker 串行接力

不要默认替换旧版 `video-expert-analyzer`。这个版本优先用于长任务。

**默认行为是一口气自动做完**，不是人工逐批填表。接力模式只在 OpenClaw 场景下启用。

## 首次使用引导

只要这次任务是"新视频"（用户给的是视频链接或本地视频文件，而不是已有的 `scene_scores.json` / 已有视频子目录的续跑），在调用任何脚本之前，先按这三步确认：

**先找 `vnext_config.json`，有就直接用。**
- 查找顺序：用户在对话里显式点名的输出根目录 → `~/.config/video-expert-analyzer-vnext/config.json` 的 `output_base_dir`。
- 在候选根目录下若能找到 `vnext_config.json`，直接读出 `output_root` / `primary_language` / `model_preferences`，跳过下面的提问。
- 续跑场景（用户给的是 `scene_scores.json` 或已有视频子目录）也按上一级目录找 `vnext_config.json`；找不到不要硬问，沿用现有配置继续跑即可。

**找不到就顺序问这三件事（一次问完，不要一问一等）：**

1. **分析结果主目录**：告诉用户"之后每个视频会在这个目录下按视频名建子目录，形如 `<主目录>/<视频名>/scene_scores.json …`"，要一个绝对路径。拿到后同时做两件事：写进 `<主目录>/vnext_config.json`；并把 `~/.config/video-expert-analyzer-vnext/config.json` 的 `output_base_dir` 改成这个路径（或在之后每次脚本调用显式带 `-o <主目录>`，两种任选其一，别混用）。
2. **四类最终报告的主语言**：范围只包含 `*_storyboard.*`、`*_audiovisual_analysis.*`、`*_detailed_analysis.md`、`*_complete_analysis.md` 这四类；其它中间产物（`scene_reports/`、`brief.md`、分类摘要、`delivery_report.json`）保持原样。让用户给一个语言（示例：中文 / English / 日本語），用 ISO 码存 `primary_language`（例如 `zh-CN`、`en-US`、`ja-JP`）。**如果选的不是中文**：脚本仍先产中文版本，你必须在 `finalize` 全部跑完、`delivery_report.json` 落盘之后，逐个把上面四类文件重写为目标语言并覆盖原文件 —— 文件名、章节结构、Scene 编号、截图路径、SVG/JSON 字段名保持不变，只重写自然语言文本；没翻完不算交付完成。
3. **视觉分析 / 报告生成的模型偏好**：问清楚有没有特殊要求，并主动帮用户落盘：
   - 有 OpenClaw：看 `~/.openclaw/agents/main/agent/models.json` 列出可用模型让用户挑，把选中的写进 `~/.config/video-expert-analyzer-vnext/config.json` 的 `auto_scoring.preferred_model` 和 `auto_scoring.fallback_models`（按优先级顺序）。
   - 只有自己的 API key：帮用户把 `OPENAI_API_KEY + OPENAI_MODEL` 或 `ANTHROPIC_API_KEY + ANTHROPIC_MODEL` 以 `export` 形式给出（由用户自己在终端里执行，不要替他 `echo` 进 shell profile）；在 `vnext_config.json` 里只留 `model_preferences.preferred_model` 等**模型名**备忘，**绝不把 API key 明文写进任何 json**。
   - 说"不需要特殊配置"：什么都不改，继续走默认发现链（先 OpenClaw 再环境变量），并在 `vnext_config.json` 里把 `model_preferences` 记为 `{"source": "auto"}`。

**落盘格式**（写到 `<主目录>/vnext_config.json`）：

```json
{
  "output_root": "/Users/.../测试",
  "primary_language": "zh-CN",
  "model_preferences": {
    "source": "openclaw" ,
    "preferred_model": "...",
    "fallback_models": ["..."]
  },
  "created_at": "2026-04-21T..."
}
```

用户拒绝回答或说"按你默认来"时：该项取默认值（主目录 `~/Downloads/video-analysis`、语言 `zh-CN`、模型 `{"source": "auto"}`），仍然把这个默认决定写进 `vnext_config.json`，不要下次又来问一遍。

## 默认执行模式

**默认由主流程自己执行评分。** 除非宿主明确是 OpenClaw 并且用了 `--dispatch-json`，否则：

- `score_batches` 会自动读配置、并行看图、直接写回 `host_batches/*-output.json`，不再要求当前 agent 手工逐批补分。
- 首次启动时，优先自动读取本机 OpenClaw 的 `~/.openclaw/agents/*/agent/models.json`；找不到时再看当前环境变量里的 API 配置。
- 如果自动发现不到可用配置，流程必须明确报 `缺少自动评分配置`，并提示如何补，不允许静默退回人工模式。
- 所有批次完成后，自动进入 `finalize` 生成最终输出。
- 整条链路（prepare → score_batches → finalize）应当尽量一口气做完，中间不需要用户干预。

只有当宿主是 OpenClaw 且明确走接力模式时，才按 `docs/openclaw_orchestration.md` 的规则分段执行。

## 不可妥协规则

1. 不允许抽样、跳过，或对没看过的画面做判断。
2. 每个 scene 都必须有独立结果，并及时写回文件。
3. 如果已有 `scene_scores.json`、`run_state.json`、`host_batches/` 或批次 output，优先续跑，不重做已完成阶段。
4. 每次开始前先读 `run_state.json`；只做当前阶段允许的动作，不自己跳步。
5. `score_batches` 的正常路径是自动并行评分，不要再把“当前 agent 自己逐批看图填 JSON”当成默认方案。
6. OpenClaw 子代理接手当前批次后，必须先更新 `receipt.status = "in_progress"`，并写 `started_at`、`updated_at`。
7. 当前批次完成后，必须把 `receipt.status = "completed"`、`has_todo = false`、`worker_summary`、`updated_at`、`completed_at` 写回。
8. 如果素材缺失、截图坏掉、当前批次无法判断，必须写成 `blocked` 并停止，不能假装完成。
9. OpenClaw 主控不要把整条长历史、整份 `scene_scores.json`、所有历史批次一起塞给下一个 worker。
10. 交付是否完成，以 `delivery_report.json` 和实际输出文件为准，不以口头汇报为准。
11. 用户请求里包含 `pdf` 时，任何一个必需 PDF 缺失都不算完成。
12. Windows 上如果本地链路明确报 `HTTP Error 429`，应直接当成平台限流阻塞回报，不要擅自改走浏览器下载、录屏或别的旁路。
13. 禁止用本地 `PIL` / `OpenCV` 的亮度、颜色、对比度特征脚本冒充“已看图”；这类结果只能算失败或诊断，不能算正式评分。
14. 视听剖析的正文长文、SVG 结构图、MV 内容架构总览改由运行本 skill 的 agent（也就是你）直接完成；脚本不再调远端文本模型做这几段，也不再保留任何本地兜底文本。遇到 `audiovisual_handoff/` 下的任务包必须按序（body → 然后 diagram **或** overview（互斥，由路由决定，通常只触发其一）→ 最后 illustrate）完成，再重新跑 `finalize`。正文 `body/output.md` 必须逐模块展开：task.md 里"输出骨架"列出的每个 `##` 模块、`###` 子条目都要字面出现，不得合并/省略；每个 `##` ≥ 700 字、每个 `###` ≥ 180 字、每个 `##` 至少引用 3 个不同 Scene 编号。脚本会在 finalize 时机器校验，不达标会抛 `ValueError`，并把缺项写到 `audiovisual_handoff/body/validation_errors.json`，按错误提示补齐再跑，不要把"已经写过"当成"合规"。
15. `illustrate/output.md` 只能使用 `audiovisual_handoff/illustrate/task.md` 中「场景目录」列出的截图路径，不得凭空编造；同一张截图也不能在连续 3 段以内重复出现，否则脚本会抛 `ValueError`。
16. Handoff `receipt.json` 会记录每个子任务的 `input_hash`；当分类结果或 prompt 变化时，已有 `output.md/svg/json` 会被自动作废，需要重新生成。

## OpenClaw 主控原则（仅 OpenClaw 接力场景适用）

只有宿主明确是 OpenClaw 并且走接力模式时，才适用以下原则：

1. 跑总控入口
2. 读 `run_state.json`
3. 优先直接跑 `python3 scripts/orchestrate_vnext.py /path/to/scene_scores.json --dispatch-json`
4. 如果确实只想单独取派单包，再跑 `python3 scripts/openclaw_dispatch.py /path/to/scene_scores.json`
5. 只把当前批次四件套交给一个短生命周期 worker
6. worker 写回后，主控重新跑总控入口；需要时再取新的派单包

默认采用”单主控 + 单当前批次 worker”的串行接力，不要同时派两个批次。

**如果不是 OpenClaw 接力场景，忽略这一节，直接按”默认执行模式”自己完成。**

## 主流程

### 0. 总控入口

新视频任务在跑这一步之前，先过一遍上面的"首次使用引导"（有 `vnext_config.json` 就直接读，没有就问用户并落盘）。

优先使用：

```bash
python3 scripts/orchestrate_vnext.py "<视频链接或本地视频>"
python3 scripts/orchestrate_vnext.py /path/to/scene_scores.json
```

总控负责准备素材、续跑到正确阶段，并在已有结果上自动接着走。

### 1. Prepare

```bash
python3 scripts/pipeline_enhanced.py "<视频链接或本地视频>"
```

这一步负责下载或读取视频、切场景、抽主截图、提字幕或转写，并初始化：

- `scene_scores.json`
- `run_state.json`
- `scene_reports/` 草稿
- 当前批次任务包

Windows 上处理 YouTube / Bilibili 时，也必须先走这条本地 pipeline。不要因为 `yt-dlp` 命令名一时不可见，就改走浏览器、录屏或手动搬运。

### 2. Score Batches

```bash
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode score_batches
```

这一阶段会自动处理批次分析：

- 先读 `run_state.json`
- 自动发现可用模型配置
- 并行读取每个 scene 的 `primary / start / mid / end` 帧
- 直接写回对应的 `batch-XXX-output.json`
- 自动合并、校验覆盖率，并在条件满足时进入 `finalize`

当前批次最小任务包只有四个文件：

- `batch-XXX-brief.md`
- `batch-XXX-contact-sheet.png`
- `batch-XXX-input.json`
- `batch-XXX-output.json`

**默认模式**：自动并行评分，不需要当前 agent 手工逐批看图填结果。

**OpenClaw 接力模式**：只在明确走 `--dispatch-json` 时使用；主控仍以自动链路为主，子代理只接手被派发的那一小段工作。

### 3. Merge / Validate

```bash
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode merge_validate
```

这一步负责合并批次结果，检查覆盖率，并优先修正旧数据里的资源路径或缺失截图问题。

### 4. Finalize

```bash
python3 scripts/ai_analyzer.py /path/to/scene_scores.json --mode finalize
```

只有在覆盖率完整、资源齐全、没有 `blocked`、没有 `needs_review`、也没有本地特征兜底痕迹后，才进入这一步。

这一步除了正式输出，还会自动生成给路由子 skill 使用的轻量分类摘要：

- `*_classification_summary.md`
- `*_classification_summary.json`
- `classification_result.json`

其中：
- 分类摘要直接来自结构化结果，不额外跑模型，默认把全片切成约 21 组前 / 中 / 后分段信号。
- `classification_result.json` 会继续调用子路由逻辑，成为主流程后续视听报告的正式路由来源。

#### 4.1 视听剖析 Agent 接力

`finalize` 生成视听剖析（`*_audiovisual_analysis.*`）时，会按子类型路由触发最多四个交由 agent 完成的子任务：

- `body`：完整的视听剖析正文 Markdown
- `diagram`：SVG 结构图（仅支持该能力的子类型）
- `overview`：MV 内容架构总览 JSON（仅音乐/MV 路由）
- `illustrate`：在近终态 Markdown 中按 Scene 引用插入对应截图

脚本为每个子任务按顺序写一个任务包到 `audiovisual_handoff/<subtask>/task.md`，并把当次 `run_state` 标成 `blocked`（`pending_task = await_audiovisual_agent`），同时抛 `AudiovisualHandoffPending`。这是运行 skill 的 agent（也就是你）应当：

1. 打开 `audiovisual_handoff/brief.md` 看整体状态，再读当前 `status = pending` 子任务的 `task.md`，严格按其中的 system prompt / user message 生成内容。
2. 把结果写入 task.md 指定的输出文件：
   - `body/output.md` — 只写正文 Markdown，保留 prompt 要求的所有 `##` 章节标题，不要额外加顶层 `#` 标题。
   - `diagram/output.svg` — 只写合法的 `<svg>...</svg>` 源码，不要反引号或说明文字。
   - `overview/output.json` — 只写 JSON 对象，字段严格按 prompt 描述，不要代码块围栏。
   - `illustrate/output.md` — 写"插图后的完整 Markdown"：保留原文每一行文字不变，只在 `##` 正文模块中被提及到 Scene 的段落后插入 `![简短说明](<截图路径>)`；截图路径必须来自 task.md 列出的"场景目录"，不要编造；同一张图在连续 3 段内不要重复；`## 路由判断`、`## 视听剖析概览 / 视频结构图 / 视频内容架构总览` 等已有图示的模块不再追加。
3. 完成后重新执行 `python3 scripts/ai_analyzer.py <scene_scores.json> --mode finalize`。脚本会读取你刚写入的输出文件，把该子任务标成 `completed`，然后推进到下一个子任务或完成剩余的交付物。
4. 不要手工改 `audiovisual_handoff/receipt.json`；脚本会自己维护。也不要用 `python3 - <<'PY' ...` 这类 heredoc 绕过 — harness 的 exec preflight 会拦，改了也会被下一次 finalize 覆盖，只需让脚本自己推进。
5. 如果某个子任务连续两次都缺关键素材，先排查素材问题，再回到这里重新跑；不要造一份占位文本塞进 `output.*`，那样会污染最终报告。
6. 子任务触发顺序是 body → (diagram 或 overview，两者互斥，由路由能力决定，多数情况只会触发一个) → illustrate。`illustrate` 最后执行，操作对象是已经拼好了路由判断块和结构图/总览图的近终态 Markdown，所以若 body 或 diagram/overview 需要重跑，对应 `output.*` 要一起删掉，避免 `illustrate/output.md` 基于旧文稿残留。
7. 视频目录名常含弯引号/特殊字符（例如 `‘GO’`、`’s`、`—`）。读取 `audiovisual_handoff/` 下的文件时，**只从脚本打印的错误信息或 `brief.md` 顶部的"Handoff 目录"绝对路径按原样复制**，不要自己重敲 —— 手敲时很容易把 `‘’` 改写成 `''`，导致 `ENOENT`。如果连续两次 ENOENT，先 `ls` 实际视频目录核对字符，再继续。

## 完成标准

最终至少应落出这些结果：

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

## 交付前检查

至少确认：

1. `run_state.json` 已更新到正确阶段，没有脏的 `next_batch`
2. 当前批次 coverage 和 `scene_scores.json` 完成情况一致
3. 当前要求的结果文件都已经真实存在
4. 如果用户请求了 PDF，对应 PDF 确实存在且不是空文件
5. 只要还有 `blocked`、`needs_review`、本地特征兜底痕迹、缺文件、缺图或缺 PDF，就不能报完成

## 环境变量与调参

以下环境变量控制脚本行为，仅在需要时覆盖默认：

- `OPENCLAW_ROOT`：覆盖 OpenClaw 根目录（默认 `~/.openclaw`）。
- `OPENCLAW_MODELS_JSON`：覆盖 `models.json` 完整路径（默认 `$OPENCLAW_ROOT/agents/main/agent/models.json`）。
- `VNEXT_STALE_MINUTES`：当前 worker 超过该分钟数未更新 `heartbeat_at`/`updated_at`/`started_at` 时，`reset_stale_in_progress_receipts` 会把 `receipt.status` 从 `in_progress` 重置为 `pending`（默认 30）。
- `VNEXT_TEXT_MODEL_RETRIES`：`request_text_with_runtime` 对单个 provider 的瞬时错误（rate limit / timeout / 5xx）重试次数（默认 2，指数退避 1s → 2s → 4s）。
- `AUDIOVISUAL_REPORT_MAX_TOKENS` / `AUDIOVISUAL_REPORT_MODEL`：视听剖析正文生成时直连文本模型的上限 / 模型名（仅在未启用 handoff 架构时生效）。

## 按需补充

- OpenClaw 接力规则：`docs/openclaw_orchestration.md`
- 平台差异、OCR、视听路由、异常恢复：`docs/appendices.md`
