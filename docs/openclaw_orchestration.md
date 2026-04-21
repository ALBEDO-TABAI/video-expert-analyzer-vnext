# OpenClaw Orchestration

只在宿主是 OpenClaw、并且自动主流程因为受限环境、人工复核或修单需求而必须临时接力时再读这份文档。

默认情况下，`score_batches` 会自己自动找配置、并行评分并直接写回结果，不需要 routine 地再派一个子 agent 去手工补每一批。

## 目标

- 让主控 agent 始终保持轻上下文，只记阶段状态，不背整条长历史
- 让子 agent 只接当前批次，不接整条分析链
- 让每一棒交接都有文件凭据，避免“看起来做了”但其实没有真正落盘

## 标准循环

1. 先正常运行自动主流程；只有确认需要接力时，主控再运行 `python3 scripts/orchestrate_vnext.py "<scene_scores.json 或视频链接>" --dispatch-json`
2. 只根据它输出的派单结果决定下一步，不自己脑补阶段
3. 如果 `controller_action` 是 `spawn_batch_worker`，说明当前批次需要人工/子 agent 介入；仍然只派一个短生命周期子 agent
4. 子 agent 退出后，主控重新运行 `orchestrate_vnext.py --dispatch-json`
5. 重复直到 `controller_action` 变成 `run_finalize` 或 `done`

如果只想单独取派单包，仍可使用 `python3 scripts/openclaw_dispatch.py "<scene_scores.json>"`。

## controller_action 含义

- `spawn_batch_worker`
  - 当前批次需要人工/子 agent 介入，不是默认常态
  - 主控只传 `brief`、`contact_sheet`、`input`、`output`
- `wait_current_worker`
  - 已经有 worker 在做当前批次
  - 主控不要再派第二个 worker，也不要提前 finalize
- `resume_orchestrator`
  - 当前批次已经写回
  - 主控重新运行总控，让系统合并结果并准备下一步
- `run_finalize`
  - 所有批次已完成
  - 主控本地进入正式收尾
- `resolve_blocker`
  - 当前流程已阻塞
  - 先修 `run_state.json` / `delivery_report.json` 里列出的真实问题
- `repair_current_batch`
  - 当前批次 worker 已明确写成 `blocked`
  - 先修这一批，不要派下一批
- `done`
  - 已完成，不再派单

## 主控规则

- 主控只常驻看这几样：`run_state.json`、`delivery_report.json`、`openclaw_dispatch.py` 输出、当前批次四件套
- 不要把整份 `scene_scores.json`、所有历史批次、所有 scene 说明一起灌给下一个子 agent
- 同一时间只保留一个活跃批次 worker；阶段推进必须串行，以 `run_state.json` 为准
- 每次 worker 完成后，主控必须重新跑总控和派单脚本，不要自己猜下一步
- 如果自动主流程已经能直接跑通，就不要为了“保持旧习惯”额外派 worker

## 子 agent 交接规则

子 agent 只做当前批次，并且必须更新 `batch-XXX-output.json` 顶层 `receipt`：

- 接手后立刻写：
  - `status = "in_progress"`
  - `started_at`
  - `updated_at`
- 正常完成后写：
  - `status = "completed"`
  - `has_todo = false`
  - `worker_summary`
  - `updated_at`
  - `completed_at`
- 遇到阻塞时写：
  - `status = "blocked"`
  - `has_todo = true`
  - `worker_summary`
  - `needs_review`
- 禁止调用本地 `PIL` / `OpenCV` 亮度、颜色、对比度特征脚本来冒充已看图；模型不可用时只能写 `blocked`

## 上下文控制

- 主控不要在子 agent prompt 里重复贴整份 skill
- 子 agent prompt 只需要：
  - skill 路径
  - 当前批次编号
  - 四件套绝对路径
  - receipt 更新规则
  - “不要继续下一批，不要 finalize”

## 真正的完成条件

- 不看 agent 口头汇报，只看落盘结果
- 交付是否完成，以 `delivery_report.json` 和实际输出文件为准
- 只要还有 `blocked`、`needs_review`、本地特征兜底痕迹、缺文件、缺图、缺 PDF、或 `run_state.json` 仍指向脏的 `next_batch`，就不算完成
