#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from common import (
    AGENT_INTERPRETATIONS,
    TOOL_EVIDENCE,
    USER_UTTERANCES,
    canonical_object,
    classify_user_utterance_intent,
    confidence_table_items,
    detect_topics,
    normalize_text,
    normalize_predicate,
    now_iso,
    read_jsonl,
    save_confidence_table,
    stable_id,
    trim_text,
)


KEYWORD_RE = re.compile(
    r"(用户原话|用户画像|AGENTS\.md|每个项目|项目文件夹|最高权重|不能|不得|不要|禁止|必须|需要|核心|目标|本质|原则|置信度|冲突|conflict|审查|跑偏|漂移|误解|污染|WORLD_STATE|memory\.md|RAG|数据库|Web UI|日志|tool evidence|structured|eval scenarios|scoring)"
)
META_EVALUATION_RE = re.compile(
    r"(评价|判断|分数|进度判断|短板|剩余问题|下一步|我看到|当前提交|这轮|这个改动很关键|"
    r"这类显性矛盾|正好解决|能覆盖|还不能|不够|不能长期只靠|说明它|意味着)"
)
ASSISTANT_OUTPUT_RE = re.compile(r"(assistant|agent|助手|最终|回答|输出|answer|output)", re.IGNORECASE)
CORE_MEMORY_RE = re.compile(r"(核心记忆|核心事实|core memory|核心认知)", re.IGNORECASE)
LOG_RE = re.compile(r"(日志|log)", re.IGNORECASE)
WORLD_STATE_RE = re.compile(r"(WORLD_STATE|世界状态|项目世界观|核心状态)", re.IGNORECASE)
REVIEW_RE = re.compile(r"(审查|review|proposal|proposed|人工)", re.IGNORECASE)
SOURCE_RE = re.compile(r"(原文|原话|证据|source|source_refs|回查|读取|定位)", re.IGNORECASE)
HISTORY_CONTEXT_RE = re.compile(r"(全部上下文|所有历史|历史上下文|raw|logs|history|塞给模型|注入)", re.IGNORECASE)


def split_fragments(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
    fragments: list[str] = []
    for part in parts:
        cleaned = part.strip(" \t-:：")
        if not cleaned:
            continue
        if KEYWORD_RE.search(cleaned):
            fragments.append(trim_fragment(cleaned))
    if not fragments and len(text) >= 120:
        fragments.append(trim_fragment(text))
    return fragments[:20]


def trim_fragment(text: str, max_len: int = 180) -> str:
    if len(text) <= max_len:
        return text
    match = KEYWORD_RE.search(text)
    if not match:
        return text[: max_len - 1] + "…"
    start = max(0, match.start() - max_len // 3)
    end = min(len(text), start + max_len - 1)
    if end - start < max_len - 1:
        start = max(0, end - max_len + 1)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end] + suffix


def classify_claim(fragment: str) -> str:
    if re.search(r"(跑偏|漂移|误解|污染|高风险)", fragment):
        return "risk"
    if re.search(r"(用户原话|用户认为|不信任|Agent 输出|最终输出)", fragment):
        return "user_principle"
    if re.search(r"(Codex|hook|每次对话|对话前|对话结束|用户画像|AGENTS\.md|每个项目|项目文件夹)", fragment):
        return "project_principle"
    if re.search(r"(不得|不要|不能|禁止|不可|不应该|不引入|不要先|每次任务前|必须先读|只提出|不得进入)", fragment):
        return "constraint"
    if re.search(r"(当前策略|MVP|下一步|先做|当前阶段)", fragment):
        return "strategy"
    return "project_principle"


def modality_for(fragment: str) -> str:
    if META_EVALUATION_RE.search(fragment):
        return "unknown"
    if re.search(r"(不得|不要|不能|禁止|不可|不应该|不引入|不能进入|不是)", fragment):
        return "must_not"
    if re.search(r"(必须|需要|要求|只能|每次|应当|应该)", fragment):
        return "must"
    if re.search(r"(可以|支持|允许)", fragment):
        return "may"
    if re.search(r"(不是|不属于)", fragment):
        return "is_not"
    return "unknown"


def action_modality(fragment: str, default: str = "must") -> str:
    if re.search(r"(不得|不要|不能|禁止|不可|不应该|不能进入|不得进入|不注入|不塞)", fragment):
        return "must_not"
    if re.search(r"(可以|允许|支持)", fragment):
        return "may"
    if re.search(r"(必须|需要|要求|只能|应当|应该)", fragment):
        return "must"
    return default


def structured_claim(
    *,
    category: str,
    claim: str,
    evidence: list[str],
    source_type: str,
    subject: str | None = None,
    predicate: str | None = None,
    object_value: str | None = None,
    scope: str = "project",
) -> dict[str, Any]:
    inferred_predicate = normalize_predicate(predicate, claim)
    obj = object_value or trim_text(re.sub(r"^(用户原话片段：|Agent 理解：|Agent 推断目标：|Agent 推断约束：|Agent 标记风险：|工具证据：)", "", claim), 260)
    return {
        "subject": subject or category,
        "predicate": inferred_predicate,
        "object": obj,
        "object_key": canonical_object(obj),
        "scope": scope,
        "modality": modality_for(claim),
        "valid_from": now_iso(),
        "valid_until": None,
        "source_refs": evidence,
        "confidence_reason": f"Extracted by local rule from {source_type}.",
        "supersedes": [],
    }


def stability_for(category: str, source: dict[str, Any]) -> str:
    if category == "strategy":
        return "temporary"
    signals = source.get("signals", {})
    if signals.get("long_form") or signals.get("repeated") or signals.get("strong_emphasis"):
        return "stable"
    return "evolving"


def utterance_intent(utterance: dict[str, Any]) -> str:
    return str(utterance.get("utterance_intent") or classify_user_utterance_intent(str(utterance.get("text", ""))))


def can_extract_core_candidates(utterance: dict[str, Any]) -> bool:
    return utterance_intent(utterance) == "direct_user_intent"


def candidate_from_utterance(utterance: dict[str, Any], fragment: str) -> dict[str, Any]:
    category = classify_claim(fragment)
    claim = f"用户原话片段：{fragment}"
    evidence = [utterance["id"]]
    return {
        "id": stable_id("cog", category, claim, utterance["id"]),
        "claim": claim,
        "category": category,
        "confidence": 0,
        "evidence": evidence,
        "conflicts": [],
        "last_verified": now_iso(),
        "stability": stability_for(category, utterance),
        "include_in_world_state": False,
        "source_type": "user_utterance",
        "utterance_intent": utterance_intent(utterance),
        "status": "candidate",
        "topics": detect_topics(fragment),
        "structured": structured_claim(
            category=category,
            claim=claim,
            evidence=evidence,
            source_type="user_utterance",
            subject="user_intent" if category == "user_principle" else ("risk" if category == "risk" else "project_cognition_system"),
            predicate=None,
        ),
    }


def action_candidate_from_utterance(
    utterance: dict[str, Any],
    fragment: str,
    *,
    predicate: str,
    subject: str,
    object_value: str,
    modality: str,
    category: str = "constraint",
) -> dict[str, Any]:
    claim = f"用户原话动作：{predicate} / {fragment}"
    evidence = [utterance["id"]]
    structured = structured_claim(
        category=category,
        claim=claim,
        evidence=evidence,
        source_type="user_utterance",
        subject=subject,
        predicate=predicate,
        object_value=object_value,
        scope="project",
    )
    structured["modality"] = modality
    return {
        "id": stable_id("cog", category, predicate, object_value, claim, utterance["id"]),
        "claim": claim,
        "category": category,
        "confidence": 0,
        "evidence": evidence,
        "conflicts": [],
        "last_verified": now_iso(),
        "stability": stability_for(category, utterance),
        "include_in_world_state": False,
        "source_type": "user_utterance",
        "utterance_intent": utterance_intent(utterance),
        "status": "candidate",
        "topics": detect_topics(fragment),
        "structured": structured,
    }


def action_candidates_from_utterance(utterance: dict[str, Any], fragment: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if ASSISTANT_OUTPUT_RE.search(fragment) and LOG_RE.search(fragment):
        candidates.append(
            action_candidate_from_utterance(
                utterance,
                fragment,
                predicate="store_log",
                subject="assistant_output",
                object_value="assistant final output",
                modality="must" if re.search(r"(只能|必须|应当|应该)", fragment) else "may",
            )
        )
    if (
        ASSISTANT_OUTPUT_RE.search(fragment)
        and CORE_MEMORY_RE.search(fragment)
        and re.search(r"(进入|进|写入|作为|当作|保存到|enter|become)", fragment, re.IGNORECASE)
    ):
        candidates.append(
            action_candidate_from_utterance(
                utterance,
                fragment,
                predicate="enter_core_memory",
                subject="assistant_output",
                object_value="assistant final output",
                modality=action_modality(fragment, "must_not" if re.search(r"(不|禁|only|只)", fragment, re.IGNORECASE) else "may"),
            )
        )
    if REVIEW_RE.search(fragment) and (WORLD_STATE_RE.search(fragment) or CORE_MEMORY_RE.search(fragment) or re.search(r"(进入|写入|更新)", fragment)):
        candidates.append(
            action_candidate_from_utterance(
                utterance,
                fragment,
                predicate="require_review",
                subject="world_state",
                object_value="world_state",
                modality="must",
            )
        )
    if WORLD_STATE_RE.search(fragment) and re.search(r"(自动|直接|随意|默认).{0,12}(更新|修改|改写|写入|重建)|更新|修改|改写|重建", fragment):
        candidates.append(
            action_candidate_from_utterance(
                utterance,
                fragment,
                predicate="update_world_state",
                subject="world_state",
                object_value="world_state",
                modality=action_modality(fragment, "must"),
            )
        )
    if SOURCE_RE.search(fragment) and re.search(r"(指定|具体|按|需要|必须|只能|回查|读取|定位)", fragment):
        candidates.append(
            action_candidate_from_utterance(
                utterance,
                fragment,
                predicate="read_source",
                subject="evidence_lookup",
                object_value="source evidence",
                modality="must",
            )
        )
    if HISTORY_CONTEXT_RE.search(fragment) and re.search(r"(上下文|历史|raw|logs|塞给模型|注入|批量|全部|所有)", fragment):
        candidates.append(
            action_candidate_from_utterance(
                utterance,
                fragment,
                predicate="inject_context",
                subject="history_context",
                object_value="history context",
                modality=action_modality(fragment, "must_not"),
            )
        )
    return candidates


def candidates_from_interpretation(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[tuple[str, str]] = []
    if record.get("agent_understanding"):
        rows.append(("project_principle", f"Agent 理解：{trim_fragment(str(record['agent_understanding']))}"))
    rows.extend(("strategy", f"Agent 推断目标：{trim_fragment(str(item))}") for item in record.get("inferred_goals", []))
    rows.extend(("constraint", f"Agent 推断约束：{trim_fragment(str(item))}") for item in record.get("inferred_constraints", []))
    rows.extend(("risk", f"Agent 标记风险：{trim_fragment(str(item))}") for item in record.get("risks", []))

    candidates: list[dict[str, Any]] = []
    for category, claim in rows:
        evidence = [record["id"]]
        candidates.append(
            {
                "id": stable_id("cog", category, claim, record["id"]),
                "claim": claim,
                "category": category,
                "confidence": min(int(record.get("confidence", 50)), 74),
                "evidence": evidence,
                "conflicts": [],
                "last_verified": now_iso(),
                "stability": "evolving",
                "include_in_world_state": False,
                "source_type": "agent_interpretation",
                "status": "candidate",
                "topics": detect_topics(claim),
                "structured": structured_claim(
                    category=category,
                    claim=claim,
                    evidence=evidence,
                    source_type="agent_interpretation",
                    subject="agent_interpretation",
                    predicate="infers",
                    scope="project",
                ),
            }
        )
    return candidates


def candidates_from_tool_evidence(record: dict[str, Any]) -> list[dict[str, Any]]:
    kind = str(record.get("evidence_kind", "command_output"))
    if kind not in {"test_result", "git_result", "filesystem_result"}:
        return []
    summary = trim_text(str(record.get("content_summary", "")), 180)
    if not summary:
        return []
    outcome = str(record.get("outcome", "observed"))
    claim = f"工具证据：{kind} / {outcome} / {summary}"
    evidence = [record["id"]]
    return [
        {
            "id": stable_id("cog", "strategy", claim, record["id"]),
            "claim": claim,
            "category": "strategy",
            "confidence": 0,
            "evidence": evidence,
            "conflicts": [],
            "last_verified": now_iso(),
            "stability": "temporary",
            "include_in_world_state": False,
            "source_type": "tool_evidence",
            "status": "candidate",
            "topics": list(dict.fromkeys([*record.get("linked_topics", []), kind])),
            "structured": structured_claim(
                category="strategy",
                claim=claim,
                evidence=evidence,
                source_type="tool_evidence",
                subject="tool_result",
                predicate="observed" if kind != "test_result" else "test_passed",
                object_value=summary,
                scope=kind,
            ),
        }
    ]


def merge_key(item: dict[str, Any]) -> tuple[str, str]:
    claim = re.sub(r"^用户原话片段：", "", str(item.get("claim", "")))
    return str(item.get("category", "")), normalize_text(claim)


def merge_candidates(existing: list[dict[str, Any]], new_candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    by_id = {item["id"]: item for item in existing}
    by_key = {merge_key(item): item["id"] for item in existing}
    added = 0
    for candidate in new_candidates:
        key = merge_key(candidate)
        existing_id = by_key.get(key)
        if existing_id and existing_id in by_id:
            current = by_id[existing_id]
            current.setdefault("evidence", [])
            for evidence_id in candidate.get("evidence", []):
                if evidence_id not in current["evidence"]:
                    current["evidence"].append(evidence_id)
            if candidate.get("structured"):
                current["structured"] = candidate["structured"]
        elif candidate["id"] not in by_id:
            by_id[candidate["id"]] = candidate
            by_key[key] = candidate["id"]
            added += 1
    return list(by_id.values()), added


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract rule-based cognition candidates from raw user utterances and agent interpretations.")
    parser.add_argument("--max-new", type=int, default=200, help="Maximum new candidates to add in one run.")
    args = parser.parse_args()

    candidates: list[dict[str, Any]] = []
    for utterance in read_jsonl(USER_UTTERANCES):
        if not can_extract_core_candidates(utterance):
            continue
        for fragment in split_fragments(str(utterance.get("text", ""))):
            candidates.append(candidate_from_utterance(utterance, fragment))
            candidates.extend(action_candidates_from_utterance(utterance, fragment))
            if len(candidates) >= args.max_new:
                break
        if len(candidates) >= args.max_new:
            break

    for interpretation in read_jsonl(AGENT_INTERPRETATIONS):
        candidates.extend(candidates_from_interpretation(interpretation))

    for tool_record in read_jsonl(TOOL_EVIDENCE):
        candidates.extend(candidates_from_tool_evidence(tool_record))

    merged, added = merge_candidates(confidence_table_items(), candidates[: args.max_new])
    save_confidence_table(merged)
    print(json.dumps({"candidate_count": len(candidates), "added": added, "total": len(merged)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
