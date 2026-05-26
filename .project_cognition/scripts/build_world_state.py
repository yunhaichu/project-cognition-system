#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from common import CONFLICTS, DECISIONS, GOVERNANCE_GATE, WORLD_STATE, WORLD_STATE_COMPACT, confidence_table_items, normalize_text, now_iso, read_json, read_jsonl, write_text


SECTION_ORDER = [
    ("project_principle", "项目本质"),
    ("user_principle", "用户核心意图"),
    ("project_principle", "稳定架构原则"),
    ("constraint", "不可违背事项"),
    ("risk", "高风险误解"),
    ("strategy", "当前策略"),
]


def blocked_item_ids() -> set[str]:
    blocked: set[str] = set()
    for conflict in read_jsonl(CONFLICTS):
        if conflict.get("resolution") in {"unresolved", "deferred"} and int(conflict.get("severity", 0)) >= 60:
            blocked.add(str(conflict.get("item_a", "")))
            blocked.add(str(conflict.get("item_b", "")))
    return blocked


def gate_allowed_ids() -> set[str] | None:
    if not GOVERNANCE_GATE.exists():
        return None
    data = read_json(GOVERNANCE_GATE, {})
    return {str(item_id) for item_id in data.get("allowed_item_ids", [])}


def eligible_items() -> list[dict[str, Any]]:
    blocked = blocked_item_ids()
    allowed_by_gate = gate_allowed_ids()
    items = []
    for item in confidence_table_items():
        if item.get("status") in {"rejected", "superseded"}:
            continue
        if allowed_by_gate is not None and item.get("id") not in allowed_by_gate:
            continue
        if allowed_by_gate is None and item.get("status") != "accepted" and item.get("source_type") not in {"manual_initialization", "bootstrap_rule"}:
            continue
        if allowed_by_gate is None:
            if not item.get("include_in_world_state"):
                continue
        if item.get("id") in blocked:
            continue
        if int(item.get("confidence", 0)) < 90:
            continue
        items.append(item)
    def sort_key(item: dict[str, Any]) -> tuple[int, int, str, str]:
        status_rank = 0 if item.get("status") == "accepted" else 1
        return (status_rank, -int(item.get("confidence", 0)), str(item.get("last_verified", "")), str(item.get("id", "")))

    return sorted(items, key=sort_key)


def clean_claim(text: str) -> str:
    text = re.sub(r"^用户原话片段：", "", str(text)).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def has_claim(items: list[dict[str, Any]], *patterns: str) -> bool:
    haystack = "\n".join(clean_claim(str(item.get("claim", ""))) for item in items)
    return all(re.search(pattern, haystack, flags=re.I) for pattern in patterns)


def claims(items: list[dict[str, Any]], category: str, max_items: int = 4) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item.get("category") != category:
            continue
        claim = clean_claim(str(item["claim"]))
        key = normalize_text(claim)
        if key in seen:
            continue
        seen.add(key)
        selected.append(claim)
        if len(selected) >= max_items:
            break
    return selected


def sentence_join(rows: list[str], fallback: str) -> str:
    if not rows:
        return fallback
    cleaned = []
    for row in rows:
        text = str(row).strip()
        if not text.endswith(("。", ".", "！", "!", "？", "?", "；", ";")):
            text += "。"
        cleaned.append(text)
    return "".join(cleaned)


def bullet_join(rows: list[str], fallback: str, max_items: int = 4) -> str:
    selected = [clean_claim(row) for row in rows if clean_claim(row)][:max_items]
    if not selected:
        selected = [fallback]
    return "\n".join(f"- {row}" for row in selected)


def active_decisions() -> list[str]:
    rows = []
    for decision in read_jsonl(DECISIONS):
        if decision.get("status") == "active":
            rows.append(str(decision.get("decision", "")))
    return rows[:4]


def structured_cognition_rows(items: list[dict[str, Any]], max_items: int = 6) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for item in items:
        structured = item.get("structured") or {}
        obj = clean_claim(str(structured.get("object") or item.get("claim", "")))
        if not obj:
            continue
        scope = str(structured.get("scope") or "project")
        modality = str(structured.get("modality") or "unknown")
        subject = str(structured.get("subject") or item.get("category") or "cognition")
        key = normalize_text("|".join([subject, scope, modality, obj]))
        if key in seen:
            continue
        seen.add(key)
        rows.append(f"[{scope}/{modality}] {subject}: {obj}")
        if len(rows) >= max_items:
            break
    return rows


def compact_structured_rows(items: list[dict[str, Any]], max_items: int = 3) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for item in items:
        structured = item.get("structured") or {}
        if int(item.get("confidence", 0)) < 95:
            continue
        if str(structured.get("scope") or "project") != "project":
            continue
        modality = str(structured.get("modality") or "unknown")
        if modality not in {"must", "must_not"}:
            continue
        predicate = str(structured.get("predicate") or "states")
        obj = clean_claim(str(structured.get("object") or item.get("claim", "")))
        if not obj:
            continue
        obj = obj[:96] + "…" if len(obj) > 96 else obj
        key = normalize_text("|".join([modality, predicate, obj]))
        if key in seen:
            continue
        seen.add(key)
        rows.append(f"- {compact_structured_sentence(modality, predicate, obj)}")
        if len(rows) >= max_items:
            break
    return rows


def compact_structured_sentence(modality: str, predicate: str, obj: str) -> str:
    if predicate == "render" and re.search(r"(读|读取|先读|read).{0,20}(WORLD_STATE|世界状态|项目世界观)", obj, flags=re.I):
        predicate = "read_source"
    if modality == "must_not":
        labels = {
            "call_llm": "禁止调用模型",
            "enter_core_memory": "禁止进入核心记忆",
            "inject_context": "禁止注入上下文",
            "update_world_state": "禁止更新核心状态",
            "override": "禁止覆盖",
        }
        return f"{labels.get(predicate, '禁止')}：{obj}"
    labels = {
        "read_source": "必须读取",
        "require_review": "必须治理准入",
        "score_evidence": "必须评分",
        "resolve_conflict": "必须处理冲突",
        "store_log": "必须记录日志",
        "update_world_state": "必须更新核心状态",
        "render": "必须渲染",
    }
    return f"{labels.get(predicate, '必须')}：{obj}"


def render_world_state(items: list[dict[str, Any]]) -> str:
    constraints = claims(items, "constraint", 8)
    risks = claims(items, "risk", 4)
    strategies = claims(items, "strategy", 4)
    hermes_status = "Hermes hook 已改为低成本模式；Codex hook 使用 SessionStart 紧凑注入与 Stop 本地整理。"
    if not has_claim(items, "Hermes", "低上下文|低成本"):
        hermes_status = "Codex hook 使用 SessionStart 紧凑注入与 Stop 本地整理。"
    current_status = "本地文件版 MVP 已可运行；当前重点是防漂移同时压低默认上下文。"
    if strategies:
        current_status += hermes_status

    key_constraints = [
        "默认只注入紧凑用户画像与 compact 世界状态；不把当前线程历史、raw、logs 批量塞进模型。",
        "用户原话和真实工具结果权重最高；Agent 最终输出只进日志，不能直接成为核心事实。",
        "WORLD_STATE 只能由受控管线生成；低置信、无证据、未解决冲突不得进入核心状态。",
        "历史原文只在用户明确要求、证据不足或冲突处理时按具体来源定位读取。",
    ]
    if has_claim(items, "不能用模型反复读取历史|local_only|LLM"):
        key_constraints.append("post hook 默认 local-only，不调用 LLM 总结历史。")
    structured_rows = structured_cognition_rows(items)
    structured_layer = bullet_join(
        structured_rows,
        "暂无额外 accepted structured cognition；当前以 bootstrap doctrine 和高置信规则为准。",
        6,
    )

    return f"""# WORLD_STATE.md

## 1. 项目本质
本项目是低漂移、可追溯、可审计的项目认知系统。它不是普通 RAG、无限 memory.md、聊天摘要器或历史上下文堆叠器。

## 2. 用户核心意图
用户要在避免 Agent 认知漂移的同时大幅降低 token 开销。用户原话最高权重，Agent 输出最低权重；核心认知必须有证据、置信度、冲突检测和自动治理准入。默认不做人工审查；只有用户明确要求时才引入人工判断或人工裁决。

## 3. 当前项目状态
{current_status}

## 4. 稳定架构原则
每个项目维护独立 `.project_cognition/`。`AGENTS.md` 只保留用户级全局入口，不在项目目录或 bootstrap 中创建。跨项目用户画像是 Agent 级全局文件：Codex 使用 `~/.codex/USER_PROFILE.md`，Hermes 使用 `~/.hermes/USER_PROFILE.md`。认知分层为 raw 事实、Agent 理解、策略、用户画像和日志；不同层级不能混用权重。

结构化认知层：
{structured_layer}

## 5. 不可违背事项
{bullet_join(key_constraints, "不得把所有历史上下文直接塞给模型。", 5)}

## 6. 高风险误解
{bullet_join(risks, "不要把本项目理解成普通 RAG、聊天摘要器、无限记忆文件或大型 Agent 平台。不要把 AI 总结当成用户原话。", 3)}

## 7. 当前策略
先维护本地文件版 MVP，不做数据库、Web UI 或大型平台。优先优化 compact hook 注入、自动治理准入、冲突阻断和按需证据定位。

## 8. 偏航检查
执行前自查：是否违背用户原话；是否把 AI 总结当事实；是否扩大范围；是否忽略真实代码/工具结果；是否需要按源回查原文；是否把低置信推断写成高置信结论。

## 9. 更新规则
完整状态写入本文件；hook 只注入 `WORLD_STATE_COMPACT.md`。新认知先进入候选层，经本地规则、评分、冲突检测、候选降噪和自动治理准入后，再由 `build_world_state.py` 生成。显式人工判断只在用户主动要求时使用。
"""


def render_compact_world_state(items: list[dict[str, Any]]) -> str:
    hermes = "Hermes hook 每 session/project 最多一次 compact 注入；post 采集本轮证据并按本地规则增量整理，不调用 LLM。" if has_claim(items, "Hermes", "低上下文|低成本") else ""
    compact_structured = compact_structured_rows(items)
    lines = [
        "# WORLD_STATE_COMPACT.md",
        "",
        "项目：低漂移、可追溯、可审计的项目认知系统；不是 RAG、memory.md、聊天摘要或历史堆叠。",
        "目标：避免认知漂移，同时极致降低 token。默认只用当前命令、全局协议、紧凑用户画像和本 compact 状态。",
        "硬约束：用户原话/真实工具结果最高权重；Agent 输出只进日志；低置信、无证据、未解决冲突不得进核心状态。",
        "上下文：不默认使用线程历史、raw、logs；需要证据时按 ID/关键词定位具体原文读取。",
        "流程：Codex 在 SessionStart 注入、Stop 整理；Hermes 在 pre/post hook 低成本运行；默认不调用 LLM。",
    ]
    if compact_structured:
        lines.append("高优先级结构化认知：")
        lines.extend(compact_structured)
    if hermes:
        lines.append(f"状态：{hermes}")
    lines.append("偏航检查：是否违背用户原话、扩大范围、把总结当事实、忽略真实代码/工具结果，或需要回查原文。")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the compact WORLD_STATE.md from high-confidence cognition and active decisions.")
    parser.add_argument("--dry-run", action="store_true", help="Print generated WORLD_STATE.md without writing it.")
    args = parser.parse_args()

    items = eligible_items()
    content = render_world_state(items)
    compact_content = render_compact_world_state(items)
    metadata = {
        "generated_at": now_iso(),
        "included_cognition_ids": [item["id"] for item in items],
        "included_count": len(items),
        "structured_count": len(structured_cognition_rows(items)),
        "compact_structured_count": len(compact_structured_rows(items)),
        "characters": len(content),
        "compact_characters": len(compact_content),
    }
    if args.dry_run:
        print(content)
        print("\n--- COMPACT ---\n")
        print(compact_content)
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return
    write_text(WORLD_STATE, content)
    write_text(WORLD_STATE_COMPACT, compact_content)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
