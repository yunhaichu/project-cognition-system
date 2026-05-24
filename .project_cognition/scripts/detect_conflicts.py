#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from common import CONFLICTS, confidence_table_items, normalize_text, now_iso, read_jsonl, save_confidence_table, stable_id, write_jsonl


TOPIC_RULES = {
    "database": ["数据库", "database"],
    "web_ui": ["Web UI", "web ui", "UI", "界面"],
    "context_dump": ["所有历史", "全部上下文", "塞给模型"],
    "world_state_update": ["直接改核心", "直接修改 WORLD_STATE", "改核心世界状态", "自动改写核心", "随意改写", "Agent 直接改"],
    "agent_output_memory": ["Agent 输出", "最终输出", "核心记忆", "日志"],
    "rag_identity": ["普通 RAG", "RAG"],
    "memory_md": ["memory.md", "memory"],
}

NEGATIVE_RE = re.compile(r"(不得|不要|不能|禁止|不可|不应|不应该|不是|不信任|不引入|不要先|不能进入|只能进入日志|高风险误解|误解包括)")
POSITIVE_RE = re.compile(r"(必须|需要|可以|应当|应该|支持|实现|引入|做|进入核心|作为核心)")
DIRECT_POSITIVE_RE = re.compile(r"(可以|应当|应该|必须|需要).{0,12}(直接|自动|随意).{0,12}(改|修改|改写|进入核心|作为核心)")
GENERIC_PREDICATES = {"", "states", "requires", "infers", "observed"}
GENERIC_SUBJECTS = {"", "project", "project_cognition_system", "user_intent", "agent_interpretation", "tool_result"}


def topics_for(claim: str) -> set[str]:
    lowered = claim.lower()
    topics: set[str] = set()
    for topic, keywords in TOPIC_RULES.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            topics.add(topic)
    return topics


def structured_polarity(item: dict[str, Any]) -> str:
    modality = str(item.get("structured", {}).get("modality", ""))
    if modality in {"must_not", "is_not"}:
        return "negative"
    if modality in {"must", "should", "may", "is"}:
        return "positive"
    return "neutral"


def structured_scope(item: dict[str, Any]) -> str:
    return str(item.get("structured", {}).get("scope") or "project").strip().lower()


def compatible_scope(item_a: dict[str, Any], item_b: dict[str, Any]) -> bool:
    scope_a = structured_scope(item_a)
    scope_b = structured_scope(item_b)
    return not scope_a or not scope_b or scope_a == scope_b


def compatible_subject(item_a: dict[str, Any], item_b: dict[str, Any]) -> bool:
    subject_a = normalize_text(str(item_a.get("structured", {}).get("subject", "")))
    subject_b = normalize_text(str(item_b.get("structured", {}).get("subject", "")))
    if subject_a == subject_b:
        return True
    return subject_a in GENERIC_SUBJECTS or subject_b in GENERIC_SUBJECTS


def compatible_predicate(item_a: dict[str, Any], item_b: dict[str, Any]) -> bool:
    predicate_a = normalize_text(str(item_a.get("structured", {}).get("predicate", "")))
    predicate_b = normalize_text(str(item_b.get("structured", {}).get("predicate", "")))
    if predicate_a == predicate_b:
        return True
    return predicate_a in GENERIC_PREDICATES or predicate_b in GENERIC_PREDICATES


def object_terms(item: dict[str, Any]) -> set[str]:
    structured = item.get("structured", {})
    text = " ".join([str(structured.get("object", "")), str(item.get("claim", ""))])
    terms = set(topics_for(text))
    terms.update(token.lower() for token in re.findall(r"[A-Za-z0-9_.-]{3,}", text))
    for chinese in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if len(chinese) <= 12:
            terms.add(chinese)
    return {term for term in terms if term}


def compatible_object(item_a: dict[str, Any], item_b: dict[str, Any]) -> bool:
    object_a = normalize_text(str(item_a.get("structured", {}).get("object", "")))
    object_b = normalize_text(str(item_b.get("structured", {}).get("object", "")))
    if object_a and object_b and (object_a in object_b or object_b in object_a):
        return True
    return bool(object_terms(item_a) & object_terms(item_b))


def structured_conflict_topics(item_a: dict[str, Any], item_b: dict[str, Any]) -> list[str]:
    if not item_a.get("structured") or not item_b.get("structured"):
        return []
    polarity_a = structured_polarity(item_a)
    polarity_b = structured_polarity(item_b)
    if polarity_a not in {"positive", "negative"} or polarity_b not in {"positive", "negative"} or polarity_a == polarity_b:
        return []
    if not compatible_scope(item_a, item_b):
        return []
    if not compatible_subject(item_a, item_b):
        return []
    if not compatible_predicate(item_a, item_b):
        return []
    if not compatible_object(item_a, item_b):
        return []
    subject = str(item_a.get("structured", {}).get("subject") or item_b.get("structured", {}).get("subject") or "structured")
    predicate = str(item_a.get("structured", {}).get("predicate") or item_b.get("structured", {}).get("predicate") or "states")
    scope = structured_scope(item_a)
    return [f"structured:{subject}:{predicate}:{scope}"]


def polarity_for(claim: str) -> str:
    has_negative = bool(NEGATIVE_RE.search(claim))
    has_positive = bool(POSITIVE_RE.search(claim))
    if re.search(r"(高风险误解|误解包括|不要把|而不是|不应由|不能让)", claim):
        return "negative"
    if DIRECT_POSITIVE_RE.search(claim):
        return "positive"
    if has_negative and not has_positive:
        return "negative"
    if has_positive and not has_negative:
        return "positive"
    if has_negative and has_positive:
        if re.search(r"(只能进入日志|不能进入核心|不是普通|不要先|不引入|必须经过|只提出)", claim):
            return "negative"
        return "mixed"
    return "neutral"


def evidence_rank(item: dict[str, Any]) -> int:
    source = item.get("source_type", "")
    confidence = int(item.get("confidence", 0))
    rank = confidence
    if source in {"user_utterance", "manual_initialization"}:
        rank += 30
    elif source == "tool_evidence":
        rank += 25
    elif source == "agent_interpretation":
        rank += 10
    elif source == "assistant_output":
        rank -= 10
    return rank


def conflict_type(item_a: dict[str, Any], item_b: dict[str, Any]) -> str:
    sources = {item_a.get("source_type"), item_b.get("source_type")}
    if sources <= {"user_utterance", "manual_initialization"}:
        return "user_vs_user"
    if "tool_evidence" in sources:
        return "old_vs_new"
    if "agent_interpretation" in sources or "assistant_output" in sources:
        return "user_vs_agent"
    return "old_vs_new"


def severity_for(item_a: dict[str, Any], item_b: dict[str, Any]) -> int:
    base = 60
    if item_a.get("include_in_world_state") or item_b.get("include_in_world_state"):
        base += 15
    if max(int(item_a.get("confidence", 0)), int(item_b.get("confidence", 0))) >= 90:
        base += 10
    return min(100, base)


def make_conflict(item_a: dict[str, Any], item_b: dict[str, Any], topic: str) -> dict[str, Any]:
    rank_a = evidence_rank(item_a)
    rank_b = evidence_rank(item_b)
    chosen_side = ""
    reason = ""
    if abs(rank_a - rank_b) >= 20:
        chosen_side = item_a["id"] if rank_a > rank_b else item_b["id"]
        reason = "Evidence strength differs clearly; keep the stronger side unless reviewed."
    return {
        "id": stable_id("conflict", item_a["id"], item_b["id"], topic),
        "timestamp": now_iso(),
        "type": conflict_type(item_a, item_b),
        "item_a": item_a["id"],
        "item_b": item_b["id"],
        "description": f"Potential contradiction on topic '{topic}': {item_a['claim']} <-> {item_b['claim']}",
        "severity": severity_for(item_a, item_b),
        "resolution": "unresolved",
        "chosen_side": chosen_side,
        "reason": reason,
    }


def detect(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    active = [item for item in items if item.get("status") not in {"rejected", "superseded"} and int(item.get("confidence", 0)) >= 50]
    for index, item_a in enumerate(active):
        topics_a = topics_for(str(item_a.get("claim", "")))
        polarity_a = structured_polarity(item_a)
        if polarity_a == "neutral":
            polarity_a = polarity_for(str(item_a.get("claim", "")))
        if polarity_a not in {"positive", "negative"}:
            continue
        for item_b in active[index + 1 :]:
            polarity_b = structured_polarity(item_b)
            if polarity_b == "neutral":
                polarity_b = polarity_for(str(item_b.get("claim", "")))
            if polarity_b not in {"positive", "negative"} or polarity_a == polarity_b:
                continue
            shared_topics = set(structured_conflict_topics(item_a, item_b))
            if not shared_topics and compatible_scope(item_a, item_b):
                shared_topics = topics_a & topics_for(str(item_b.get("claim", "")))
            for topic in sorted(shared_topics):
                conflicts.append(make_conflict(item_a, item_b, topic))
    return conflicts


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect simple contradictions between cognition candidates and high-confidence state.")
    parser.add_argument("--min-severity", type=int, default=0, help="Only write conflicts at or above this severity.")
    args = parser.parse_args()

    items = confidence_table_items()
    existing = read_jsonl(CONFLICTS)
    existing_ids = {record["id"] for record in existing}
    new_conflicts = [record for record in detect(items) if record["id"] not in existing_ids and int(record["severity"]) >= args.min_severity]

    if new_conflicts:
        all_conflicts = existing + new_conflicts
        write_jsonl(CONFLICTS, all_conflicts)
        item_by_id = {item["id"]: item for item in items}
        for conflict in new_conflicts:
            for item_id in [conflict["item_a"], conflict["item_b"]]:
                if item_id in item_by_id:
                    item_by_id[item_id].setdefault("conflicts", [])
                    if conflict["id"] not in item_by_id[item_id]["conflicts"]:
                        item_by_id[item_id]["conflicts"].append(conflict["id"])
                    item_by_id[item_id]["include_in_world_state"] = False
        save_confidence_table(list(item_by_id.values()))

    print(json.dumps({"new_conflicts": len(new_conflicts), "total_conflicts": len(existing) + len(new_conflicts)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
