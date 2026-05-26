# Project Cognition System / 项目认知系统

> English version below.

## 中文说明

Project Cognition System 是一套给长期 AI 编程 Agent 使用的本地认知治理系统。

它解决的问题不是“让 Agent 记住更多”，而是“什么内容有资格成为项目事实”。当上下文被截断、会话被压缩、历史对话丢失时，Agent 可以通过短小、稳定、可追溯的项目状态重新进入正确工作坐标，同时避免把大量历史对话塞回上下文。

它不是：

- 普通 RAG
- 无限膨胀的 `memory.md`
- 每轮都注入完整历史对话的上下文工程
- 让模型自动总结并覆盖用户原话的记忆系统

它是：

- 一个本地文件版 cognition governance runtime
- 一个把用户原话、工具结果、Agent 理解、日志分层保存的系统
- 一个从证据中生成短 `WORLD_STATE.md` / `WORLD_STATE_COMPACT.md` 的管线
- 一个通过评分、冲突检测、自动治理准入来降低认知漂移的最小闭环

### 核心原则

- 用户原话是最高权重证据。
- 用户原话会保留原文，但会区分直接意图、带引用的请求和外部评价；用户粘贴的评价材料默认不进入核心状态。
- 真实工具结果是一等证据，但不能未经治理准入就覆盖用户原话。
- Agent 最终回答只进日志，不作为核心事实。
- Agent 理解过程可以用于审计，但不能直接成为真相。
- 默认上下文必须短，只注入 compact state。
- 冲突必须记录、阻断并按规则处理，不能静默覆盖。
- 项目状态按项目隔离；用户画像按 Agent 全局隔离。
- 默认只使用本地规则脚本，不调用 LLM 总结历史。

### 快速开始

要求：Python 3，标准库即可。

运行样例会话：

```bash
python .project_cognition/scripts/ingest_session.py \
  --input examples/sample_session.jsonl \
  --session-id sample_demo

python .project_cognition/scripts/extract_candidates.py
python .project_cognition/scripts/score_candidates.py
python .project_cognition/scripts/detect_conflicts.py
python .project_cognition/scripts/cluster_candidates.py
python .project_cognition/scripts/cluster_conflicts.py
python .project_cognition/scripts/auto_governance_gate.py
python .project_cognition/scripts/build_world_state.py
```

查看生成的项目状态：

```bash
cat .project_cognition/WORLD_STATE.md
cat .project_cognition/WORLD_STATE_COMPACT.md
```

运行 post hook 封装：

```bash
python .project_cognition/scripts/codex_post_hook.py \
  --session-jsonl examples/sample_session.jsonl \
  --session-id sample_demo
```

运行 pre hook 输出 compact context：

```bash
python .project_cognition/scripts/codex_pre_hook.py \
  --format markdown \
  --profile-mode ultra \
  --world-mode compact \
  --max-chars 1600
```

校验状态文件并运行回归测试：

```bash
python .project_cognition/scripts/validate_state.py
python evals/run_minimal_eval.py
```

按需查找证据：

```bash
python .project_cognition/scripts/index_segments.py
python .project_cognition/scripts/lookup_evidence.py --query "WORLD_STATE" --limit 5
python .project_cognition/scripts/build_vector_index.py
python .project_cognition/scripts/vector_lookup.py --query "WORLD_STATE" --limit 5
```

lookup 和 vector lookup 只返回 `source_id`、路径和非权威预览。使用证据前，应按 `source_id` 回读完整原始记录。

### 已有项目初始化

把本系统用于已有项目：

```bash
python .project_cognition/scripts/bootstrap_existing_project.py \
  --target-root /path/to/existing/project \
  --history /path/to/history.jsonl
```

`--history` 必须显式指定。系统不会自动扫描历史目录，也不会把全部历史对话默认塞进上下文。

### 基本数据流

```text
session transcript
  -> raw evidence
  -> cognition candidates
  -> scoring
  -> conflict detection
  -> candidate/conflict clustering
  -> automated governance gate
  -> WORLD_STATE.md / WORLD_STATE_COMPACT.md
```

每轮任务开始时，hook 读取 compact state。每轮任务结束时，post hook 可以导入本轮 transcript，自动聚类重复候选和冲突，运行自动治理准入，并重建项目状态。治理准入带有预算控制，会优先保留高权重证据和代表性认知，重复或低优先级条目留在 distilled 层而不进入核心状态。

### 目录结构

```text
.project_cognition/
  WORLD_STATE.md
  WORLD_STATE_COMPACT.md
  raw/          # 用户原话、工具证据、冲突、决策
  distilled/    # 候选认知、置信度表、自动聚类结果
  proposals/    # 显式更新建议
  logs/         # assistant 输出、工具调用等审计日志
  scripts/      # 本地管线脚本
  schemas/      # JSON/JSONL schema
docs/           # 架构、hook、集成说明
examples/       # 最小样例
evals/          # 回归测试 fixture
integrations/   # Codex / Hermes 集成
```

### 重要边界

用户画像不放在项目目录内：

- Codex: `~/.codex/USER_PROFILE.md`
- Hermes: `~/.hermes/USER_PROFILE.md`

不要让本系统创建项目级 `AGENTS.md`。

### 文档

- [Architecture](docs/architecture.md)
- [Hooks](docs/hooks.md)
- [Codex integration](integrations/codex/README.md)
- [Hermes integration](integrations/hermes/README.md)

### 隐私

本仓库只应提交空状态文件和脱敏样例。真实项目的 `raw/`、`logs/`、`distilled/`、`proposals/` 可能包含私有对话、工具输出、本地路径或用户偏好，发布前必须脱敏并移除私有内容。

### 许可证

本项目使用 PolyForm Noncommercial License 1.0.0。

未经单独书面许可，不允许商业使用。本项目是 source-available for noncommercial use，不是 OSI 批准意义上的开源项目。

---

## English

Project Cognition System is a local cognition governance system for long-running AI coding agents.

It does not try to make an agent remember more. It asks what is allowed to become project truth. After context truncation, session compaction, or lost chat history, the agent can re-enter the project through a short, stable, auditable world state without stuffing old conversations back into the prompt.

It is not:

- generic RAG
- a growing `memory.md`
- prompt stuffing with full chat history
- model-generated memory that overwrites user wording

It is:

- a local-file cognition governance runtime
- a layered evidence system for user utterances, tool results, agent interpretations, and logs
- a pipeline that builds short `WORLD_STATE.md` / `WORLD_STATE_COMPACT.md` files
- a minimal loop for reducing drift through scoring, conflict detection, and automated governance gates

### Core Principles

- User utterances are the highest-weight evidence.
- User utterances are preserved verbatim, but direct intent, requests with quotes, and external commentary are distinguished; pasted evaluation text does not enter core state by default.
- Real tool results are first-class evidence, but they do not override user evidence without governance acceptance.
- Agent final answers are logs, not core facts.
- Agent interpretations are useful for audit, not automatic truth.
- Default context must stay short and inject only compact state.
- Conflicts must be recorded, blocked, and resolved by rules or explicit commands, not silently overwritten.
- Project cognition is per project; user profile is global and agent-specific.
- The default pipeline uses local rules and does not call an LLM to summarize history.

### Quick Start

Requirement: Python 3, standard library only.

Run the sample session:

```bash
python .project_cognition/scripts/ingest_session.py \
  --input examples/sample_session.jsonl \
  --session-id sample_demo

python .project_cognition/scripts/extract_candidates.py
python .project_cognition/scripts/score_candidates.py
python .project_cognition/scripts/detect_conflicts.py
python .project_cognition/scripts/cluster_candidates.py
python .project_cognition/scripts/cluster_conflicts.py
python .project_cognition/scripts/auto_governance_gate.py
python .project_cognition/scripts/build_world_state.py
```

Inspect the generated state:

```bash
cat .project_cognition/WORLD_STATE.md
cat .project_cognition/WORLD_STATE_COMPACT.md
```

Run the post-hook wrapper:

```bash
python .project_cognition/scripts/codex_post_hook.py \
  --session-jsonl examples/sample_session.jsonl \
  --session-id sample_demo
```

Run the pre-hook compact context output:

```bash
python .project_cognition/scripts/codex_pre_hook.py \
  --format markdown \
  --profile-mode ultra \
  --world-mode compact \
  --max-chars 1600
```

Validate state files and run regression tests:

```bash
python .project_cognition/scripts/validate_state.py
python evals/run_minimal_eval.py
```

Look up evidence on demand:

```bash
python .project_cognition/scripts/index_segments.py
python .project_cognition/scripts/lookup_evidence.py --query "WORLD_STATE" --limit 5
python .project_cognition/scripts/build_vector_index.py
python .project_cognition/scripts/vector_lookup.py --query "WORLD_STATE" --limit 5
```

Lookup and vector lookup only return `source_id`, paths, and non-authoritative previews. Read the full raw record by `source_id` before using it as evidence.

### Bootstrap An Existing Project

Use this system with an existing project:

```bash
python .project_cognition/scripts/bootstrap_existing_project.py \
  --target-root /path/to/existing/project \
  --history /path/to/history.jsonl
```

`--history` must be explicit. The system does not auto-scan history directories and does not inject all historical chats into context by default.

### Basic Data Flow

```text
session transcript
  -> raw evidence
  -> cognition candidates
  -> scoring
  -> conflict detection
  -> candidate/conflict clustering
  -> automated governance gate
  -> WORLD_STATE.md / WORLD_STATE_COMPACT.md
```

At task start, hooks read compact state. At task end, the post hook can ingest the current transcript, automatically cluster duplicate candidates and conflicts, run the governance gate, and rebuild project state. The governance gate applies admission budgets, keeping high-authority representative cognition in core state while leaving duplicate or lower-priority items in the distilled layer.

### Directory Layout

```text
.project_cognition/
  WORLD_STATE.md
  WORLD_STATE_COMPACT.md
  raw/          # user utterances, tool evidence, conflicts, decisions
  distilled/    # cognition candidates and confidence table
  proposals/    # pending updates
  logs/         # assistant outputs, tool calls, audit logs
  scripts/      # local pipeline scripts
  schemas/      # JSON/JSONL schemas
docs/           # architecture, hooks, integration notes
examples/       # minimal examples
evals/          # regression fixtures
integrations/   # Codex / Hermes integrations
```

### Boundaries

User profile does not live in project folders:

- Codex: `~/.codex/USER_PROFILE.md`
- Hermes: `~/.hermes/USER_PROFILE.md`

This system should not create project-level `AGENTS.md` files.

### Documentation

- [Architecture](docs/architecture.md)
- [Hooks](docs/hooks.md)
- [Codex integration](integrations/codex/README.md)
- [Hermes integration](integrations/hermes/README.md)

### Privacy

Only empty state files and sanitized examples should be committed. Real `raw/`, `logs/`, `distilled/`, and `proposals/` content may contain private conversations, tool output, local paths, or user preferences. Sanitize and remove private content before publishing.

### License

This project uses the PolyForm Noncommercial License 1.0.0.

Commercial use is not permitted without separate written permission. The project is source-available for noncommercial use, but it is not OSI-approved open source.
