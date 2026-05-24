#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from common import (
    AGENT_INTERPRETATIONS,
    USER_UTTERANCES,
    confidence_table_items,
    detect_topics,
    normalize_text,
    now_iso,
    read_jsonl,
    save_confidence_table,
    stable_id,
)


KEYWORD_RE = re.compile(
    r"(用户原话|用户画像|AGENTS\.md|每个项目|项目文件夹|最高权重|不能|不得|不要|禁止|必须|需要|核心|目标|本质|原则|置信度|冲突|审查|跑偏|漂移|误解|污染|WORLD_STATE|memory\.md|RAG|数据库|Web UI|日志)"
)


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


def stability_for(category: str, source: dict[str, Any]) -> str:
    if category == "strategy":
        return "temporary"
    signals = source.get("signals", {})
    if signals.get("long_form") or signals.get("repeated") or signals.get("strong_emphasis"):
        return "stable"
    return "evolving"


def candidate_from_utterance(utterance: dict[str, Any], fragment: str) -> dict[str, Any]:
    category = classify_claim(fragment)
    claim = f"用户原话片段：{fragment}"
    return {
        "id": stable_id("cog", category, claim, utterance["id"]),
        "claim": claim,
        "category": category,
        "confidence": 0,
        "evidence": [utterance["id"]],
        "conflicts": [],
        "last_verified": now_iso(),
        "stability": stability_for(category, utterance),
        "include_in_world_state": False,
        "source_type": "user_utterance",
        "status": "candidate",
        "topics": detect_topics(fragment),
    }


def candidates_from_interpretation(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[tuple[str, str]] = []
    if record.get("agent_understanding"):
        rows.append(("project_principle", f"Agent 理解：{trim_fragment(str(record['agent_understanding']))}"))
    rows.extend(("strategy", f"Agent 推断目标：{trim_fragment(str(item))}") for item in record.get("inferred_goals", []))
    rows.extend(("constraint", f"Agent 推断约束：{trim_fragment(str(item))}") for item in record.get("inferred_constraints", []))
    rows.extend(("risk", f"Agent 标记风险：{trim_fragment(str(item))}") for item in record.get("risks", []))

    candidates: list[dict[str, Any]] = []
    for category, claim in rows:
        candidates.append(
            {
                "id": stable_id("cog", category, claim, record["id"]),
                "claim": claim,
                "category": category,
                "confidence": min(int(record.get("confidence", 50)), 74),
                "evidence": [record["id"]],
                "conflicts": [],
                "last_verified": now_iso(),
                "stability": "evolving",
                "include_in_world_state": False,
                "source_type": "agent_interpretation",
                "status": "candidate",
                "topics": detect_topics(claim),
            }
        )
    return candidates


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
        for fragment in split_fragments(str(utterance.get("text", ""))):
            candidates.append(candidate_from_utterance(utterance, fragment))
            if len(candidates) >= args.max_new:
                break
        if len(candidates) >= args.max_new:
            break

    for interpretation in read_jsonl(AGENT_INTERPRETATIONS):
        candidates.extend(candidates_from_interpretation(interpretation))

    merged, added = merge_candidates(confidence_table_items(), candidates[: args.max_new])
    save_confidence_table(merged)
    print(json.dumps({"candidate_count": len(candidates), "added": added, "total": len(merged)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
