#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_prompt(system_prompt: str, user_message: str) -> str:
    return _hash_text(f"{system_prompt}\n---\n{user_message}")


HANDOFF_DIRNAME = "audiovisual_handoff"


class AudiovisualHandoffPending(RuntimeError):
    """Raised after the script writes a task packet for the hosting agent.

    The orchestrator should catch this exception, leave run_state as blocked
    with reason `await_audiovisual_agent`, and surface the handoff directory
    so the user can complete the pending task and re-run.
    """

    def __init__(
        self,
        handoff_dir: Path,
        pending_task: str,
        message: str,
        *,
        task_path: Optional[Path] = None,
        video_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.handoff_dir = handoff_dir
        self.pending_task = pending_task
        self.task_path = task_path
        self.video_id = video_id


_SUBTASK_LABELS = {
    "body": "视听剖析正文",
    "diagram": "SVG 结构图",
    "overview": "MV 内容架构总览",
    "illustrate": "视听剖析配图",
}


def _format_pending_message(video_id: str, name: str, task_path: Path, video_dir: Path) -> str:
    label = _SUBTASK_LABELS.get(name, name)
    try:
        rel_task = task_path.relative_to(video_dir)
    except ValueError:
        rel_task = task_path
    abs_task = task_path.resolve()
    return (
        f"[{video_id}] 视听剖析子任务 `{name}`（{label}）待 agent 处理："
        f"完成 `{rel_task}` 后重新运行 finalize。"
        f"（绝对路径，请按原样复制，不要替换其中的弯引号/特殊字符：{abs_task}）"
    )


class AudiovisualHandoffCoordinator:
    """Coordinates agent-handoff task packets for audiovisual report synthesis.

    Body / diagram / overview must be produced in order because each later
    task embeds the previous output in its prompt. The coordinator writes one
    task packet at a time: when a `request_*` method sees the output missing,
    it writes the packet and raises `AudiovisualHandoffPending`. After the
    agent fills the output file and the script re-runs, the same call reads
    the cached output and returns it.
    """

    def __init__(self, video_dir: Path, video_id: str):
        self.video_dir = video_dir
        self.video_id = video_id
        self.handoff_dir = video_dir / HANDOFF_DIRNAME
        self.receipt_path = self.handoff_dir / "receipt.json"

    def _subtask_dir(self, name: str) -> Path:
        return self.handoff_dir / name

    def _ensure_handoff_dir(self) -> None:
        self.handoff_dir.mkdir(parents=True, exist_ok=True)
        if not self.receipt_path.exists():
            self._write_receipt({"video_id": self.video_id, "tasks": {}})

    def _read_receipt(self) -> Dict[str, Any]:
        if not self.receipt_path.exists():
            return {"video_id": self.video_id, "tasks": {}}
        data = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"video_id": self.video_id, "tasks": {}}
        return data

    def _write_receipt(self, payload: Dict[str, Any]) -> None:
        self.handoff_dir.mkdir(parents=True, exist_ok=True)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.receipt_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _read_output(self, name: str, filename: str) -> Optional[str]:
        path = self._subtask_dir(name) / filename
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            return None
        return text

    def _is_cached_output_stale(self, name: str, system_prompt: str, user_message: str) -> bool:
        receipt = self._read_receipt()
        task_info = (receipt.get("tasks") or {}).get(name) or {}
        recorded = task_info.get("input_hash")
        if not recorded:
            return False
        return recorded != _hash_prompt(system_prompt, user_message)

    def _mark_task(self, name: str, status: str, **fields: Any) -> None:
        receipt = self._read_receipt()
        tasks = receipt.setdefault("tasks", {})
        now = datetime.now(timezone.utc).isoformat()
        task_info = tasks.get(name, {})
        task_info.update({"status": status, "updated_at": now, **fields})
        if status == "pending" and "created_at" not in task_info:
            task_info["created_at"] = now
        tasks[name] = task_info
        self._write_receipt(receipt)

    def _write_task_packet(
        self,
        name: str,
        *,
        filename: str,
        title: str,
        system_prompt: str,
        user_message: str,
        output_instruction: str,
        prompt_source: Optional[str] = None,
    ) -> Path:
        subdir = self._subtask_dir(name)
        subdir.mkdir(parents=True, exist_ok=True)
        task_path = subdir / "task.md"
        output_path = subdir / filename
        lines = [
            f"# 视听剖析 · 子任务：{title}",
            "",
            "> 当前 skill 运行已暂停，正在等待运行该 skill 的 agent（也就是你）完成本任务。",
            "> 完成后把结果写入下方指定的输出文件，再重新运行 skill 脚本继续。",
            "",
        ]
        if prompt_source:
            lines.extend(
                [
                    "## 来源",
                    "",
                    f"- System Prompt 源文件：`{prompt_source}`",
                    "- 已自动剔除：THEORETICAL ANCHORS / INPUT FORMAT / REFERENCES",
                    "- 其余章节（SYSTEM ROLE / ANALYSIS PIPELINE / OUTPUT REQUIREMENTS / CALIBRATION / APPENDIX）必须原样遵循，不得替换为压缩版模板手感。",
                    "",
                ]
            )
        lines.extend(
            [
                "## 输出文件",
                "",
                f"- `{output_path.relative_to(self.video_dir)}` — {output_instruction}",
                "",
                "## System Prompt",
                "",
                system_prompt.strip(),
                "",
                "## User Message",
                "",
                user_message.strip(),
                "",
            ]
        )
        task_path.write_text("\n".join(lines), encoding="utf-8")
        return task_path

    def _write_brief(self) -> None:
        receipt = self._read_receipt()
        tasks = receipt.get("tasks", {})
        abs_handoff_dir = self.handoff_dir.resolve()
        lines = [
            "# 视听剖析 · Agent 任务简报",
            "",
            f"视频 ID：{self.video_id}",
            f"Handoff 目录（绝对路径，按原样复制，不要替换其中的弯引号/特殊字符）：`{abs_handoff_dir}`",
            "",
            "## 规则",
            "",
            "- 视听剖析的长文、SVG 结构图、MV 架构总览都改由运行 skill 的 agent（也就是你）来完成，脚本不再访问远端文本模型。",
            "- 每个子任务会把 system prompt 与 user message 写入各自目录下的 `task.md`，你需要严格按任务要求生成输出，并写入指定的输出文件。",
            "- 任务按以下顺序：先 body；再 diagram 或 overview（由路由决定，两者**互斥**，大多数子类型只触发其中一个）；最后 illustrate。完成一个任务后重新运行 skill 的 finalize 步骤，脚本会读取你的输出并决定下一步。",
            "- 不要手工改 `receipt.json`，也不要用 `python3 - <<'PY'` 这类 heredoc 绕过；harness 的 preflight 会拦截，任何手工改动都会被脚本在下次 finalize 时覆盖。只需重跑 finalize。",
            "",
            "## 视听剖析正文的硬指标",
            "",
            '- 输出必须逐模块展开，不是"每模块一段话总结"。`task.md` 里"输出骨架"列出的每个 `## 模块` 和 `### 子条目` 都必须按字面出现，不得合并、改写或省略。',
            "- 每个 `##` 模块默认不少于 700 字；每个 `###` 子条目默认不少于 180 字；每个模块至少引用 3 个不同 Scene 编号作为证据。",
            "- 凡 prompt 要求的表格（`| 字段 | 内容 |` 等）必须原样用 Markdown 表格呈现，不可改写成段落。",
            '- 脚本会在 finalize 时机器校验这些指标；不合规会抛 ValueError，你需要对照错误信息补齐后再跑 finalize，不要把"已经写过"当成"已经合规"。',
            "",
            "## 子任务状态",
            "",
        ]
        for key in ("body", "diagram", "overview", "illustrate"):
            info = tasks.get(key)
            if not info:
                continue
            status = info.get("status", "unknown")
            task_path = info.get("task", "")
            output_path = info.get("output", "")
            prompt_source = info.get("prompt_source", "")
            lines.append(f"- `{key}`：{status}")
            if prompt_source:
                lines.append(f"  - System Prompt 源文件：`{prompt_source}`")
            if task_path:
                lines.append(f"  - 任务包：`{task_path}`")
            if output_path:
                lines.append(f"  - 输出：`{output_path}`")
        lines.append("")
        brief_path = self.handoff_dir / "brief.md"
        brief_path.write_text("\n".join(lines), encoding="utf-8")

    def request_body(
        self,
        system_prompt: str,
        user_message: str,
        prompt_source: Optional[str] = None,
    ) -> str:
        input_hash = _hash_prompt(system_prompt, user_message)
        if not self._is_cached_output_stale("body", system_prompt, user_message):
            body = self._read_output("body", "output.md")
            if body is not None:
                self._mark_task(
                    "body",
                    "completed",
                    output="body/output.md",
                    input_hash=input_hash,
                    output_hash=_hash_text(body),
                )
                return body
        self._ensure_handoff_dir()
        task_path = self._write_task_packet(
            "body",
            filename="output.md",
            title="视听剖析正文",
            system_prompt=system_prompt,
            user_message=user_message,
            output_instruction=(
                '写入完整的视听剖析正文 Markdown：严格复刻 user message 中"输出骨架"列出的 `##` 模块与 `###` 子条目标题；'
                "每个 `##` 模块 ≥ 700 字、每个 `###` 子条目 ≥ 180 字、每个 `##` 模块至少出现 3 个不同 Scene 编号；"
                "不要加顶层 `#` 标题，也不要用代码块围栏包住整份正文。"
            ),
            prompt_source=prompt_source,
        )
        extra_fields: Dict[str, Any] = {"input_hash": input_hash}
        if prompt_source:
            extra_fields["prompt_source"] = prompt_source
        self._mark_task(
            "body",
            "pending",
            task=str(task_path.relative_to(self.video_dir)),
            output="body/output.md",
            **extra_fields,
        )
        self._write_brief()
        raise AudiovisualHandoffPending(
            self.handoff_dir,
            "body",
            _format_pending_message(self.video_id, "body", task_path, self.video_dir),
            task_path=task_path,
            video_id=self.video_id,
        )

    def request_diagram(self, system_prompt: str, user_message: str) -> str:
        input_hash = _hash_prompt(system_prompt, user_message)
        if not self._is_cached_output_stale("diagram", system_prompt, user_message):
            svg = self._read_output("diagram", "output.svg")
            if svg is not None:
                self._mark_task(
                    "diagram",
                    "completed",
                    output="diagram/output.svg",
                    input_hash=input_hash,
                    output_hash=_hash_text(svg),
                )
                return svg
        self._ensure_handoff_dir()
        task_path = self._write_task_packet(
            "diagram",
            filename="output.svg",
            title="SVG 结构图",
            system_prompt=system_prompt,
            user_message=user_message,
            output_instruction="写入合法 `<svg>...</svg>` 文件内容；只保留 SVG 源码，不要附带 Markdown、反引号或说明文字。",
        )
        self._mark_task(
            "diagram",
            "pending",
            task=str(task_path.relative_to(self.video_dir)),
            output="diagram/output.svg",
            input_hash=input_hash,
        )
        self._write_brief()
        raise AudiovisualHandoffPending(
            self.handoff_dir,
            "diagram",
            _format_pending_message(self.video_id, "diagram", task_path, self.video_dir),
            task_path=task_path,
            video_id=self.video_id,
        )

    def request_overview(self, system_prompt: str, user_message: str) -> str:
        input_hash = _hash_prompt(system_prompt, user_message)
        if not self._is_cached_output_stale("overview", system_prompt, user_message):
            payload = self._read_output("overview", "output.json")
            if payload is not None:
                self._mark_task(
                    "overview",
                    "completed",
                    output="overview/output.json",
                    input_hash=input_hash,
                    output_hash=_hash_text(payload),
                )
                return payload
        self._ensure_handoff_dir()
        task_path = self._write_task_packet(
            "overview",
            filename="output.json",
            title="MV 内容架构总览",
            system_prompt=system_prompt,
            user_message=user_message,
            output_instruction="写入 JSON 对象，严格遵守 prompt 描述的字段结构；不要输出 Markdown 说明或代码块围栏。",
        )
        self._mark_task(
            "overview",
            "pending",
            task=str(task_path.relative_to(self.video_dir)),
            output="overview/output.json",
            input_hash=input_hash,
        )
        self._write_brief()
        raise AudiovisualHandoffPending(
            self.handoff_dir,
            "overview",
            _format_pending_message(self.video_id, "overview", task_path, self.video_dir),
            task_path=task_path,
            video_id=self.video_id,
        )

    def request_illustrate(self, system_prompt: str, user_message: str) -> str:
        input_hash = _hash_prompt(system_prompt, user_message)
        if not self._is_cached_output_stale("illustrate", system_prompt, user_message):
            illustrated = self._read_output("illustrate", "output.md")
            if illustrated is not None:
                self._mark_task(
                    "illustrate",
                    "completed",
                    output="illustrate/output.md",
                    input_hash=input_hash,
                    output_hash=_hash_text(illustrated),
                )
                return illustrated
        self._ensure_handoff_dir()
        task_path = self._write_task_packet(
            "illustrate",
            filename="output.md",
            title="视听剖析正文配图",
            system_prompt=system_prompt,
            user_message=user_message,
            output_instruction=(
                "写入「插图后的完整 Markdown」——"
                "保留原文每一行文字、每一个标题、每一张已存在的图片链接不变，"
                "仅在 `##` 正文模块内被提及到 Scene 的段落后面插入 `![简短说明](<截图路径>)` 行，"
                "严禁改写文字、重排段落、删除原有内容，也不要用代码块围栏包住整份输出。"
            ),
        )
        self._mark_task(
            "illustrate",
            "pending",
            task=str(task_path.relative_to(self.video_dir)),
            output="illustrate/output.md",
            input_hash=input_hash,
        )
        self._write_brief()
        raise AudiovisualHandoffPending(
            self.handoff_dir,
            "illustrate",
            _format_pending_message(self.video_id, "illustrate", task_path, self.video_dir),
            task_path=task_path,
            video_id=self.video_id,
        )
