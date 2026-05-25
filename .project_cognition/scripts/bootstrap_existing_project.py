#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from common import COGNITION_ROOT, now_iso


DIRS = [
    "raw/sessions",
    "distilled",
    "proposals",
    "logs/sessions",
    "logs/tool_calls",
    "logs/outputs",
    "logs/file_changes",
    "scripts",
    "schemas",
]

EMPTY_JSONL = [
    "raw/user_utterances.jsonl",
    "raw/agent_interpretations.jsonl",
    "raw/tool_evidence.jsonl",
    "raw/decisions.jsonl",
    "raw/conflicts.jsonl",
    "proposals/proposed_updates.jsonl",
]


def write_if_missing(path: Path, content: str, overwrite: bool = False) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def copy_file_if_needed(source: Path, destination: Path, overwrite: bool = False) -> bool:
    if destination.exists() and not overwrite:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return True


def copy_tree_files(source_dir: Path, destination_dir: Path, overwrite: bool = False) -> int:
    copied = 0
    for source in source_dir.rglob("*"):
        if source.is_dir() or "__pycache__" in source.parts:
            continue
        destination = destination_dir / source.relative_to(source_dir)
        if copy_file_if_needed(source, destination, overwrite):
            copied += 1
    return copied


def initial_readme() -> str:
    return """# Project Cognition

This folder contains the per-project cognition files for this project.

Use:

```bash
python .project_cognition/scripts/codex_pre_hook.py --format markdown
python .project_cognition/scripts/codex_post_hook.py --session-jsonl path/to/session.jsonl --session-id SESSION_ID
```

`WORLD_STATE.md` is generated from raw evidence, scored candidates, conflict checks, and accepted updates. Do not treat assistant final answers as core memory.
"""


def initial_world_state(project_name: str) -> str:
    return f"""# WORLD_STATE.md

## 1. 项目本质
{project_name} 已启用项目认知系统，但尚未形成足够高置信的项目世界状态。需要通过历史对话、用户原话、真实文件和运行结果逐步提炼。

## 2. 用户核心意图
用户原话是最高权重事实。Agent 输出不能替代用户真实表达。

## 3. 当前项目状态
当前处于既有项目认知初始化阶段。历史材料已作为 raw 证据导入后，可通过受控管线生成更具体的世界状态。

## 4. 稳定架构原则
每个项目维护自己独立的 `.project_cognition/` 文件组。`AGENTS.md` 只保留用户级全局入口；项目 bootstrap 不创建项目级 `AGENTS.md`。跨项目用户画像是 Agent 级全局文件：Codex 使用 `~/.codex/USER_PROFILE.md`，Hermes 使用 `~/.hermes/USER_PROFILE.md`。

## 5. 不可违背事项
不得把历史对话直接整体塞进核心上下文。不得让 Agent 最终输出直接进入核心记忆。不得在没有证据来源时写入核心认知。

## 6. 高风险误解
不要把历史对话 bootstrap 当作自动真相恢复。历史材料只能提供证据，低置信和冲突内容必须保留在候选或冲突层。

## 7. 当前策略
先导入历史会话，抽取候选，评分，检测冲突，再生成短小的 `WORLD_STATE.md`。

## 8. 偏航检查
Agent 执行任务前必须自查：
- 是否违背用户原话？
- 是否把自己的总结当成事实？
- 是否擅自扩大任务范围？
- 是否忽略已有项目状态？
- 是否需要回查原始材料？
- 是否正在把低置信推断写成高置信结论？

## 9. 更新规则
`WORLD_STATE.md` 由 `.project_cognition/scripts/` 中的受控管线生成。模糊、低置信或存在严重未解决冲突的内容不得进入核心状态。
"""


def initial_confidence_table(project_name: str) -> dict[str, Any]:
    timestamp = now_iso()
    return {
        "items": [
            {
                "id": "cog_bootstrap_per_project_state",
                "claim": "每个项目文件夹应维护自己独立的 .project_cognition 文件组；AGENTS.md 只保留用户级全局入口，项目 bootstrap 不创建项目级 AGENTS.md；用户画像按 Agent 隔离存放在全局目录，Codex 使用 ~/.codex/USER_PROFILE.md，Hermes 使用 ~/.hermes/USER_PROFILE.md。",
                "category": "project_principle",
                "confidence": 95,
                "evidence": ["bootstrap_existing_project"],
                "conflicts": [],
                "last_verified": timestamp,
                "stability": "stable",
                "include_in_world_state": True,
                "source_type": "bootstrap_rule",
                "status": "accepted",
            },
            {
                "id": "cog_bootstrap_history_is_evidence",
                "claim": "历史对话只能作为 raw 证据导入，不能直接替代 WORLD_STATE.md。",
                "category": "constraint",
                "confidence": 95,
                "evidence": ["bootstrap_existing_project"],
                "conflicts": [],
                "last_verified": timestamp,
                "stability": "stable",
                "include_in_world_state": True,
                "source_type": "bootstrap_rule",
                "status": "accepted",
            },
            {
                "id": "cog_bootstrap_current_strategy",
                "claim": f"{project_name} 当前处于既有项目认知初始化阶段，应先从历史材料生成最小可用 WORLD_STATE.md。",
                "category": "strategy",
                "confidence": 90,
                "evidence": ["bootstrap_existing_project"],
                "conflicts": [],
                "last_verified": timestamp,
                "stability": "temporary",
                "include_in_world_state": True,
                "source_type": "bootstrap_rule",
                "status": "accepted",
            },
        ]
    }


def initialize_project(target_root: Path, overwrite_runtime: bool) -> dict[str, Any]:
    cognition_root = target_root / ".project_cognition"
    project_name = target_root.name
    actions: list[str] = []

    for relative in DIRS:
        path = cognition_root / relative
        path.mkdir(parents=True, exist_ok=True)
        actions.append(f"ensured {path}")

    for relative in EMPTY_JSONL:
        if write_if_missing(cognition_root / relative, ""):
            actions.append(f"created {cognition_root / relative}")

    if write_if_missing(cognition_root / "README.md", initial_readme()):
        actions.append(f"created {cognition_root / 'README.md'}")
    if write_if_missing(cognition_root / "WORLD_STATE.md", initial_world_state(project_name)):
        actions.append(f"created {cognition_root / 'WORLD_STATE.md'}")
    if write_if_missing(cognition_root / "distilled" / "stable_user_principles.md", "# Stable User Principles\n\n"):
        actions.append("created stable_user_principles.md")
    if write_if_missing(cognition_root / "distilled" / "stable_project_principles.md", "# Stable Project Principles\n\n"):
        actions.append("created stable_project_principles.md")
    if write_if_missing(cognition_root / "distilled" / "recurring_constraints.md", "# Recurring Constraints\n\n"):
        actions.append("created recurring_constraints.md")
    if write_if_missing(cognition_root / "distilled" / "rejected_misunderstandings.md", "# Rejected Misunderstandings\n\n"):
        actions.append("created rejected_misunderstandings.md")
    if write_if_missing(cognition_root / "proposals" / "proposed_updates.md", "# Proposed Cognition Updates\n\nNo pending proposals.\n"):
        actions.append("created proposed_updates.md")

    confidence_path = cognition_root / "distilled" / "confidence_table.json"
    if not confidence_path.exists():
        confidence_path.write_text(json.dumps(initial_confidence_table(project_name), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        actions.append(f"created {confidence_path}")

    scripts_copied = copy_tree_files(COGNITION_ROOT / "scripts", cognition_root / "scripts", overwrite_runtime)
    schemas_copied = copy_tree_files(COGNITION_ROOT / "schemas", cognition_root / "schemas", overwrite_runtime)
    actions.append(f"copied_scripts={scripts_copied}")
    actions.append(f"copied_schemas={schemas_copied}")

    return {"target_root": str(target_root), "cognition_root": str(cognition_root), "actions": actions}


def run_target_script(target_root: Path, script_name: str, args: list[str]) -> dict[str, Any]:
    command = [sys.executable, str(target_root / ".project_cognition" / "scripts" / script_name), *args]
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("PROJECT_COGNITION_AGENT", "codex")
    completed = subprocess.run(command, cwd=target_root, env=env, text=True, capture_output=True, check=False)
    stdout = completed.stdout.strip()
    parsed: Any = stdout
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            pass
    result = {"script": script_name, "argv": args, "returncode": completed.returncode, "stdout": parsed, "stderr": completed.stderr.strip()}
    if completed.returncode != 0:
        raise RuntimeError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def ingest_histories(target_root: Path, histories: list[Path], session_prefix: str, source: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for index, history in enumerate(histories, 1):
        session_id = f"{session_prefix}_{index}_{history.stem}"
        steps.append(
            run_target_script(
                target_root,
                "ingest_session.py",
                ["--input", str(history.resolve()), "--session-id", session_id, "--source", source],
            )
        )
    return steps


def rebuild_world_state(target_root: Path) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for script_name in ["extract_candidates.py", "score_candidates.py", "detect_conflicts.py", "build_world_state.py", "build_user_profile.py"]:
        steps.append(run_target_script(target_root, script_name, []))
    return steps


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap .project_cognition for an existing project from historical conversation files.")
    parser.add_argument("--target-root", required=True, help="Existing project root that should receive its own .project_cognition folder.")
    parser.add_argument("--history", action="append", default=[], help="Historical chat file to import. Repeatable. Supports simple JSONL or text via ingest_session.py.")
    parser.add_argument("--session-prefix", default="history_bootstrap", help="Prefix for imported history session ids.")
    parser.add_argument("--source", default="historical_chat", help="Source label for imported user utterances.")
    parser.add_argument("--overwrite-runtime", action="store_true", help="Overwrite existing copied scripts/schemas in target project.")
    parser.add_argument("--no-create-agents", action="store_true", help="Deprecated no-op. Project bootstrap never creates AGENTS.md.")
    parser.add_argument("--update-agents", action="store_true", help="Deprecated no-op. Project bootstrap never updates AGENTS.md.")
    parser.add_argument("--skip-build", action="store_true", help="Only create files and ingest history; do not rebuild WORLD_STATE.md.")
    args = parser.parse_args()

    target_root = Path(args.target_root).expanduser().resolve()
    if not target_root.exists() or not target_root.is_dir():
        raise SystemExit(f"Target root is not a directory: {target_root}")

    histories = [Path(path).expanduser().resolve() for path in args.history]
    missing = [str(path) for path in histories if not path.exists()]
    if missing:
        raise SystemExit(f"History file(s) not found: {', '.join(missing)}")

    summary: dict[str, Any] = initialize_project(target_root, args.overwrite_runtime)
    summary["histories"] = [str(path) for path in histories]
    summary["ingest_steps"] = ingest_histories(target_root, histories, args.session_prefix, args.source) if histories else []
    summary["build_steps"] = [] if args.skip_build else rebuild_world_state(target_root)
    summary["completed_at"] = now_iso()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
