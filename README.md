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
- 一个通过反馈、评分、冲突检测、规则变更模拟和自动治理准入来降低认知漂移的最小闭环

### 核心原则

- 用户原话是最高权重证据。
- 用户原话会保留原文，但会区分直接意图、带引用的请求和外部评价；用户粘贴的评价材料默认不进入核心状态。
- 真实工具结果是一等证据，但不能未经治理准入就覆盖用户原话。
- Agent 最终回答只进日志，不作为核心事实。
- Agent 理解过程可以用于审计，但不能直接成为真相。
- 默认上下文必须短，只注入 compact state 或任务相关的已准入 context。
- 冲突必须记录、阻断并按规则处理，不能静默覆盖。
- 规则可以演化，但必须经过 proposal、simulation、forbidden-transition check 和 explicit apply。
- 项目状态按项目隔离；用户画像按 Agent 全局隔离，且默认只生成 proposal/report，不写全局文件。
- 默认只使用本地规则脚本，不调用 LLM 总结历史。

### v0.5 治理闭环

v0.5 的核心闭环是：

```text
feedback event
  -> feedback report
  -> scoring shadow report
  -> rule change proposal
  -> baseline/proposed simulation
  -> forbidden-transition check
  -> explicit apply
  -> rule_change_log
```

关键副作用默认受控：

```text
scoring weights 默认 shadow-only
USER_PROFILE 默认 proposal-first
context selection 只写 manifest
conditional conflict 不强制二选一
governance policy 外置并带 hash
```

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

按任务选择已准入 context，并写入 context injection manifest：

```bash
python .project_cognition/scripts/select_context.py \
  --session-id sample_demo \
  --task "governance policy" \
  --max-chars 1600
```

### 反馈和规则演化

记录反馈事件：

```bash
python .project_cognition/scripts/record_feedback.py \
  --event-family correction \
  --event-name user_correction \
  --target-type cognition \
  --target-id cog_xxx \
  --outcome negative \
  --severity 90 \
  --source-type user_utterance \
  --source-ref utt_xxx
```

生成反馈报告：

```bash
python .project_cognition/scripts/feedback_report.py
```

评分权重默认只生成 shadow report，不改权重：

```bash
python .project_cognition/scripts/update_scoring_weights.py
```

显式应用评分权重变更：

```bash
python .project_cognition/scripts/update_scoring_weights.py --apply
```

通过规则变更生命周期应用 scoring weight 变更：

```bash
python .project_cognition/scripts/propose_rule_change.py \
  --reason "Use reviewed feedback to adjust scoring weights" \
  --evidence fb_xxx

python .project_cognition/scripts/simulate_rule_change.py --proposal-id rule_prop_xxx
python .project_cognition/scripts/apply_rule_change.py --proposal-id rule_prop_xxx
```

模拟会比较 baseline/proposed state，并阻断 assistant-only 进入核心状态、外部评价进入核心状态、stale item 复活、未解决冲突侧进入 `WORLD_STATE`、compact 超预算、validation error 增加和 drift hard failure。

### 治理策略和冲突

治理策略在本地 JSON 文件中：

```text
.project_cognition/rules/governance_policy.json
```

校验策略：

```bash
python .project_cognition/scripts/validate_governance_policy.py
```

`auto_governance_gate.py` 输出 `policy_version`、`policy_hash` 和 `policy_path`，用于追溯每次 gate decision 的策略来源。

条件化冲突适用于“默认规则 + 明确例外”场景：

```bash
python .project_cognition/scripts/resolve_conflict.py \
  --conflict-id conflict_xxx \
  --action coexist-by-condition \
  --condition only_when_user_explicitly_requests \
  --reason "Default prohibition and explicit override coexist by condition."
```

这会保留冲突双方，但在后续条件渲染机制完善前，双方都不会进入 `WORLD_STATE.md` 或 compact state。

### 用户画像

用户画像不放在项目目录内：

- Codex: `~/.codex/USER_PROFILE.md`
- Hermes: `~/.hermes/USER_PROFILE.md`

默认只生成用户画像更新报告，不写全局画像：

```bash
python .project_cognition/scripts/build_user_profile.py
```

显式写全局画像：

```bash
python .project_cognition/scripts/build_user_profile.py --apply-profile
```

### 校验和回归测试

```bash
python .project_cognition/scripts/upgrade_state.py --repair
python .project_cognition/scripts/validate_state.py
python .project_cognition/scripts/validate_governance_policy.py
python evals/run_minimal_eval.py
python evals/run_feedback_eval.py
python evals/run_scoring_weight_eval.py
python evals/run_rule_change_eval.py
python evals/run_forbidden_transition_eval.py
python evals/run_governance_policy_eval.py
python evals/run_conditional_conflict_eval.py
python evals/run_context_selection_eval.py
python evals/run_user_profile_eval.py
```

创建脱敏发布包：

```bash
python scripts/build_package.py --version v0.5.0
```

发布包默认排除真实 `raw/`、`logs/`、索引、生成态聚类、生成态报告和私有会话证据。

`upgrade_state.py --repair` 会把旧版本项目认知文件升级到当前格式，保留原始证据，只修正元数据并归档可重建索引。post hook 会自动执行这一步。

按需查找证据：

```bash
python .project_cognition/scripts/index_segments.py
python .project_cognition/scripts/lookup_evidence.py --query "WORLD_STATE" --limit 5
python .project_cognition/scripts/build_vector_index.py
python .project_cognition/scripts/vector_lookup.py --query "WORLD_STATE" --limit 5
```

lookup 和 vector lookup 只返回 `source_id`、路径和非权威预览。使用证据前，应按 `source_id` 回读完整原始记录。

### 已有项目初始化

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
  -> versioned state upgrade
  -> cognition candidates
  -> scoring
  -> conflict detection
  -> candidate/conflict clustering
  -> automated governance gate
  -> WORLD_STATE.md / WORLD_STATE_COMPACT.md
```

每轮任务开始时，hook 读取 compact state。每轮任务结束时，post hook 可以导入本轮 transcript，运行本地治理管线，生成 shadow/report，并重建项目状态。治理准入带有预算控制，会优先保留高权重证据和代表性认知，重复或低优先级条目留在 distilled 层而不进入核心状态。

### 目录结构

```text
.project_cognition/
  WORLD_STATE.md
  WORLD_STATE_COMPACT.md
  raw/          # 用户原话、工具证据、反馈、冲突、规则变更日志
  distilled/    # 候选认知、置信度表、自动聚类结果、shadow reports
  proposals/    # 显式更新建议、规则变更建议、用户画像更新报告
  rules/        # governance policy 等本地规则文件
  logs/         # assistant 输出、工具调用、context injection manifest
  scripts/      # 本地管线脚本
  schemas/      # JSON/JSONL schema
docs/           # 架构、hook、集成说明
examples/       # 最小样例
evals/          # 回归测试 fixture
integrations/   # Codex / Hermes 集成
```

### 文档

- [Architecture](docs/architecture.md)
- [Hooks](docs/hooks.md)
- [Feedback layer](docs/feedback_layer.md)
- [Scoring weight shadow updates](docs/scoring_weight_shadow.md)
- [Rule change lifecycle](docs/rule_change_lifecycle.md)
- [Governance policy](docs/governance_policy.md)
- [Conditional conflicts](docs/conditional_conflicts.md)
- [Context selection](docs/context_selection.md)
- [USER_PROFILE updates](docs/user_profile_updates.md)
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

It is not generic RAG, a growing `memory.md`, full-history prompt stuffing, or model-generated memory that overwrites user wording.

It is a local-file cognition governance runtime with layered evidence, governed world-state rendering, feedback metrics, rule-change simulation, explicit apply, and audit logs.

### v0.5 Governance Loop

```text
feedback event
  -> feedback report
  -> scoring shadow report
  -> rule change proposal
  -> baseline/proposed simulation
  -> forbidden-transition check
  -> explicit apply
  -> rule_change_log
```

By default:

```text
scoring weights are shadow-only
USER_PROFILE updates are proposal-first
context selection only writes manifests
conditional conflicts do not force a winner
governance policy is externalized and hash-tracked
```

### Quick Start

Requirement: Python 3, standard library only.

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

Inspect state:

```bash
cat .project_cognition/WORLD_STATE.md
cat .project_cognition/WORLD_STATE_COMPACT.md
```

Run post hook:

```bash
python .project_cognition/scripts/codex_post_hook.py \
  --session-jsonl examples/sample_session.jsonl \
  --session-id sample_demo
```

Run compact pre-hook output:

```bash
python .project_cognition/scripts/codex_pre_hook.py \
  --format markdown \
  --profile-mode ultra \
  --world-mode compact \
  --max-chars 1600
```

Select task-specific admitted context:

```bash
python .project_cognition/scripts/select_context.py \
  --session-id sample_demo \
  --task "governance policy" \
  --max-chars 1600
```

### Feedback And Rule Changes

```bash
python .project_cognition/scripts/feedback_report.py
python .project_cognition/scripts/update_scoring_weights.py
python .project_cognition/scripts/propose_rule_change.py --reason "Use reviewed feedback" --evidence fb_xxx
python .project_cognition/scripts/simulate_rule_change.py --proposal-id rule_prop_xxx
python .project_cognition/scripts/apply_rule_change.py --proposal-id rule_prop_xxx
```

`update_scoring_weights.py` is shadow-only unless `--apply` is used. Rule-change apply refuses unsimulated proposals and proposals with hard failures.

### User Profile

Global user profile updates are proposal-first:

```bash
python .project_cognition/scripts/build_user_profile.py
python .project_cognition/scripts/build_user_profile.py --apply-profile
```

### Validation And Evals

```bash
python .project_cognition/scripts/validate_state.py
python .project_cognition/scripts/validate_governance_policy.py
python evals/run_minimal_eval.py
python evals/run_feedback_eval.py
python evals/run_scoring_weight_eval.py
python evals/run_rule_change_eval.py
python evals/run_forbidden_transition_eval.py
python evals/run_governance_policy_eval.py
python evals/run_conditional_conflict_eval.py
python evals/run_context_selection_eval.py
python evals/run_user_profile_eval.py
```

Build a sanitized release package:

```bash
python scripts/build_package.py --version v0.5.0
```

### Documentation

- [Architecture](docs/architecture.md)
- [Hooks](docs/hooks.md)
- [Feedback layer](docs/feedback_layer.md)
- [Rule change lifecycle](docs/rule_change_lifecycle.md)
- [Governance policy](docs/governance_policy.md)
- [Context selection](docs/context_selection.md)
- [USER_PROFILE updates](docs/user_profile_updates.md)

### License

This project uses the PolyForm Noncommercial License 1.0.0. Commercial use is not permitted without separate written permission.
