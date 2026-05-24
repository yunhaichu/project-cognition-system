# Project Cognition System / 项目认知系统

> English version below.

## 中文说明

Project Cognition System 是一套面向长期 AI 编程 Agent 的本地优先认知治理系统。

它不是普通 RAG，不是不断膨胀的 `memory.md`，也不是把所有历史对话塞进每次提示词的工具。它的目标是：当上下文被截断、会话被压缩、历史对话丢失时，Agent 仍能通过一个短小、稳定、可追溯的项目世界状态重新进入正确工作坐标，同时显著降低默认上下文开销。

### 核心理念

传统记忆系统主要问：“Agent 能不能记住更多？”

本系统问的是另一组问题：

- 这条记忆可靠吗？
- 它来自用户原话、真实工具结果、Agent 理解，还是 Agent 最终输出？
- 它是否应该进入核心项目状态？
- 它是否与旧的高置信认知冲突？
- 需要时能否回查到精确原始证据？
- 默认注入上下文能否保持很小？

系统将证据、理解、策略、用户画像和日志分层保存，并生成短小的 `WORLD_STATE.md` 与更短的 `WORLD_STATE_COMPACT.md` 供 hook 注入。

### 基本原则

- 用户原话具有最高证据权重。
- 真实工具结果是一等证据，但工具结果不会在未审查时自动覆盖用户原话。
- Agent 最终回答是输出，不是事实。
- Agent 的推理、工具调用和修改过程可用于审计，但不能自动成为真相。
- raw 材料可以增长，但默认上下文必须保持短小。
- 低置信认知不得进入核心项目状态。
- 冲突必须记录，不得静默覆盖。
- 核心状态由本地规则脚本重建，不通过隐藏 LLM 总结历史。
- 项目认知按项目隔离；用户画像是全局且按 Agent 隔离。

### 目录结构

```text
.project_cognition/
  WORLD_STATE.md
  WORLD_STATE_COMPACT.md
  raw/
  distilled/
  proposals/
  logs/
  scripts/
  schemas/
examples/
docs/
integrations/
```

### 快速开始

运行样例流程：

```bash
python .project_cognition/scripts/ingest_session.py \
  --input examples/sample_session.jsonl \
  --session-id sample_demo

python .project_cognition/scripts/extract_candidates.py
python .project_cognition/scripts/score_candidates.py
python .project_cognition/scripts/detect_conflicts.py
python .project_cognition/scripts/build_world_state.py
python .project_cognition/scripts/codex_pre_hook.py \
  --format markdown \
  --profile-mode ultra \
  --world-mode compact \
  --max-chars 1600
```

也可以直接运行本地 post hook 封装：

```bash
python .project_cognition/scripts/codex_post_hook.py \
  --session-jsonl examples/sample_session.jsonl \
  --session-id sample_demo
```

运行最小评测：

```bash
python evals/run_minimal_eval.py
```

评测会在临时项目副本中验证：用户原话进入 raw、assistant 输出只进 logs、工具结果进入 `raw/tool_evidence.jsonl`、候选认知带结构化字段、tool-only 候选默认需要审查后才能进入 `WORLD_STATE.md`。

当前 eval 还覆盖五个治理场景：用户推翻 agent、工具结果推翻 agent、同一规则不同 scope 不冲突、冲突 resolve 后 loser 被 superseded、accepted structured cognition 被渲染进 `WORLD_STATE.md`。

eval 还会读取 `evals/golden/minimal_invariants.json`，用 golden invariants 固化关键行为，而不是全文比对文案。当前 golden 覆盖 compact 字符预算、核心检查项、冲突场景、compact structured summary 和 dogfood 自测。

可选地，可以显式传入一段真实 Codex/Hermes transcript 做 dogfood，不会自动扫描历史目录：

```bash
python evals/run_minimal_eval.py --dogfood-transcript path/to/session.jsonl
```

### Hook 模型

会话开始时：

1. 读取当前 Agent 的全局 `USER_PROFILE.md`。
2. 读取当前项目的 `WORLD_STATE_COMPACT.md`。
3. 只注入紧凑状态，不注入 raw 历史。

会话结束时：

1. 如果有 transcript，则导入当前会话。
2. 用户消息进入 raw evidence。
3. assistant 输出进入 logs。
4. 用本地规则抽取候选认知。
5. 为候选认知评分。
6. 检测冲突。
7. 重建 `WORLD_STATE.md` 和 `WORLD_STATE_COMPACT.md`。

工具调用会同时进入两个层级：

- `logs/tool_calls/`：完整工具日志，供审计。
- `raw/tool_evidence.jsonl`：归一化后的正式证据，区分测试结果、git 结果、文件系统结果、网页结果和普通命令输出。

候选认知除了保留可读 `claim`，还会带一个最小结构化对象：`subject / predicate / object / scope / modality / valid_from / valid_until / source_refs / confidence_reason / supersedes`。

`predicate` 使用小型枚举并由本地规则归一化，例如 `enter_core_memory / store_log / create / render / override / require_review / inject_context / call_llm / read_source / update_world_state / score_evidence / resolve_conflict / test_passed`。保留 `states / requires / observed / infers` 用于兼容和兜底。

结构化对象还带 `object_key`，用于把 `assistant final answer`、`agent output`、`最终输出` 等本地归一到同一冲突对象。当前仍是规则归一化，不调用模型。

评分层会单独索引 `tool_evidence`。测试结果、git 结果和文件系统结果作为确定性工具证据加权高于 agent interpretation；网页结果和普通命令输出权重较低。tool-only 候选即使置信较高，也默认需要 review 后才可进入核心世界状态。

冲突检测优先比较 structured fields。相同 `subject / predicate / object / scope` 下相反 `modality` 会被视为冲突；scope 不同的规则默认不冲突。

`WORLD_STATE_COMPACT.md` 默认仍保持 doctrine-heavy，但可以吸收极少数高优先级结构化认知：只允许 `accepted`、`confidence >= 95`、`scope=project`、`modality=must/must_not` 的条目，最多 3 条。

冲突默认只发现并阻断。人工裁决可使用：

```bash
python .project_cognition/scripts/resolve_conflict.py --list-unresolved
python .project_cognition/scripts/resolve_conflict.py \
  --conflict-id conflict_xxx \
  --action choose-a \
  --reason "用户原话证据强于旧推断"
```

### 用户画像边界

项目状态属于每个项目自己的 `.project_cognition/`。

用户画像是全局文件，并按 Agent 隔离：

- Codex: `~/.codex/USER_PROFILE.md`
- Hermes: `~/.hermes/USER_PROFILE.md`

不要把用户画像放进项目文件夹。不要让本系统创建项目级 `AGENTS.md`。

### 既有项目初始化

```bash
python .project_cognition/scripts/bootstrap_existing_project.py \
  --target-root /path/to/existing/project \
  --history /path/to/history.jsonl
```

bootstrap 脚本会在目标项目中创建 `.project_cognition/`，并将历史对话作为证据导入。它不会创建项目级 `AGENTS.md`。

### 隐私

本仓库只包含空 raw/log 文件和脱敏样例。真实项目的 `raw/`、`logs/`、`distilled/`、`proposals/` 可能包含私有对话、工具输出、本地路径或用户偏好，发布前必须审查。

### 许可证

本项目使用 PolyForm Noncommercial License 1.0.0。

未经单独书面许可，不允许商业使用。这意味着本项目是面向非商业使用的 source-available 项目，不是 OSI 批准意义上的开源项目。

### 当前状态

MVP。仅依赖 Python 标准库。

---

## English

Project Cognition System is a lightweight, local-first cognition governance system for long-running AI coding agents.

This project is not a generic RAG pipeline, not a growing `memory.md`, and not a tool for stuffing all chat history into every prompt. Its goal is to keep an agent aligned to a stable project view after context truncation, session compaction, or lost conversation history, while keeping default context very small.

### Core Idea

Traditional memory systems ask: "Can the agent remember more?"

Project Cognition System asks different questions:

- Is this memory reliable?
- Is it user evidence, tool evidence, agent interpretation, or agent output?
- Should it enter the core project state at all?
- Is there a conflict with older high-confidence cognition?
- Can the agent recover the exact original source when needed?
- Can the default injected context stay tiny?

The system separates evidence, interpretation, strategy, user profile, and logs. It generates a short `WORLD_STATE.md` and an even shorter `WORLD_STATE_COMPACT.md` for hook injection.

### Principles

- User utterances have the highest evidence weight.
- Real tool results are first-class evidence, but they do not automatically override user evidence without review.
- Agent final answers are outputs, not facts.
- Agent reasoning and tool use are useful for audit, not automatic truth.
- Raw material may grow, but default context must stay small.
- Low-confidence cognition must not enter core project state.
- Conflicts are recorded, not silently overwritten.
- Core state is rebuilt by local rule-based scripts, not hidden LLM summarization.
- Project cognition is per project; user profile is global and agent-specific.

### Directory Layout

```text
.project_cognition/
  WORLD_STATE.md
  WORLD_STATE_COMPACT.md
  raw/
  distilled/
  proposals/
  logs/
  scripts/
  schemas/
examples/
docs/
integrations/
```

### Quick Start

Run the sample flow:

```bash
python .project_cognition/scripts/ingest_session.py \
  --input examples/sample_session.jsonl \
  --session-id sample_demo

python .project_cognition/scripts/extract_candidates.py
python .project_cognition/scripts/score_candidates.py
python .project_cognition/scripts/detect_conflicts.py
python .project_cognition/scripts/build_world_state.py
python .project_cognition/scripts/codex_pre_hook.py \
  --format markdown \
  --profile-mode ultra \
  --world-mode compact \
  --max-chars 1600
```

Or run the local post-hook wrapper:

```bash
python .project_cognition/scripts/codex_post_hook.py \
  --session-jsonl examples/sample_session.jsonl \
  --session-id sample_demo
```

Run the minimal eval:

```bash
python evals/run_minimal_eval.py
```

The eval runs in a temporary project copy and checks that user utterances enter raw evidence, assistant output stays in logs, tool output is normalized into `raw/tool_evidence.jsonl`, candidates carry structured fields, and tool-only candidates require review before entering `WORLD_STATE.md`.

The current eval also covers five governance scenarios: user evidence overriding agent inference, tool evidence overriding agent inference, same rule with different scope not conflicting, conflict resolution superseding the losing side, and accepted structured cognition rendering into `WORLD_STATE.md`.

The eval also reads `evals/golden/minimal_invariants.json`. Golden invariants lock down behavior without full-text markdown snapshots. They cover the compact character budget, required checks, conflict scenarios, compact structured summary, and dogfood self-test behavior.

Optionally, pass one explicit real Codex/Hermes transcript for dogfood. The eval does not scan history directories:

```bash
python evals/run_minimal_eval.py --dogfood-transcript path/to/session.jsonl
```

### Hook Model

At session start:

1. Read the agent-specific global `USER_PROFILE.md`.
2. Read the current project's `WORLD_STATE_COMPACT.md`.
3. Inject only the compact state, not raw history.

At session stop:

1. Ingest the current session if a transcript is available.
2. Store user messages as raw evidence.
3. Store assistant outputs as logs.
4. Extract candidates with local rules.
5. Score candidates.
6. Detect conflicts.
7. Rebuild `WORLD_STATE.md` and `WORLD_STATE_COMPACT.md`.

Tool calls are stored in two layers:

- `logs/tool_calls/`: full audit log.
- `raw/tool_evidence.jsonl`: normalized evidence, classified as test results, git results, filesystem results, web results, or generic command output.

Cognition candidates keep a readable `claim` and a minimal structured object: `subject / predicate / object / scope / modality / valid_from / valid_until / source_refs / confidence_reason / supersedes`.

`predicate` is normalized to a small enum by local rules, including `enter_core_memory / store_log / create / render / override / require_review / inject_context / call_llm / read_source / update_world_state / score_evidence / resolve_conflict / test_passed`. `states / requires / observed / infers` remain as compatibility and fallback predicates.

Structured objects also carry `object_key`, a local canonical key that can treat `assistant final answer`, `agent output`, and `最终输出` as the same conflict object. This remains rule-based and does not call a model.

The scoring layer indexes `tool_evidence` directly. Test results, git results, and filesystem results get stronger deterministic evidence weight than agent interpretation; web results and generic command output get lower weight. Tool-only candidates still require review before entering core world state.

Conflict detection first compares structured fields. Opposite `modality` for the same `subject / predicate / object / scope` is treated as a conflict; rules with different scopes do not conflict by default.

`WORLD_STATE_COMPACT.md` remains doctrine-heavy by default, but it can include a tiny high-priority structured cognition summary. Only `accepted`, `confidence >= 95`, `scope=project`, `modality=must/must_not` rows are eligible, with a hard cap of 3 rows.

Conflict detection blocks conflicted cognition by default. Human review can resolve or defer conflicts:

```bash
python .project_cognition/scripts/resolve_conflict.py --list-unresolved
python .project_cognition/scripts/resolve_conflict.py \
  --conflict-id conflict_xxx \
  --action choose-a \
  --reason "User evidence outranks the older inference"
```

### User Profile Boundary

Project state belongs in each project's `.project_cognition/`.

User profile is global and agent-specific:

- Codex: `~/.codex/USER_PROFILE.md`
- Hermes: `~/.hermes/USER_PROFILE.md`

Do not put user profile into project folders. Do not create project-level `AGENTS.md` as part of this system.

### Existing Project Bootstrap

```bash
python .project_cognition/scripts/bootstrap_existing_project.py \
  --target-root /path/to/existing/project \
  --history /path/to/history.jsonl
```

The bootstrap script creates `.project_cognition/` in the target project and imports history as evidence. It does not create project-level `AGENTS.md`.

### Privacy

This repository ships with empty raw/log files and sanitized examples. Real `raw/`, `logs/`, `distilled/`, and `proposals/` content may contain private conversation history, tool output, paths, or user preferences. Review before publishing.

### License

This project is released under the PolyForm Noncommercial License 1.0.0.

Commercial use is not permitted without separate written permission. This means the project is source-available for noncommercial use, but it is not OSI-approved open source.

### Status

MVP. Python standard library only.
