#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from common import COGNITION_ROOT, CONFIDENCE_TABLE, USER_PROFILE, read_json, write_json, write_text


USER_PROFILE_REPORT = COGNITION_ROOT / "proposals" / "user_profile_update_report.json"

DEFAULT_PRINCIPLES = [
    "用户明确要求忠实执行当前命令，不擅自扩大任务范围。",
    "用户认为用户原话权重最高，尤其是长段、反复强调、明确偏好和明确否定。",
    "用户不信任 AI 用自己的总结覆盖用户真实表达。",
    "用户认为 Agent 最终输出权重最低，应作为日志或运行产物，而不是核心记忆。",
    "用户希望通过证据、置信度、冲突检测和自动治理准入防止认知污染。",
    "用户希望默认上下文保持最小化，不把历史对话作为每轮默认上下文；需要历史原文时应定位指定原文读取，而不是批量注入全部历史。",
    "默认不做人工审查、人工裁决或人工 review 流程；项目认知应优先依赖本地规则、证据、置信度、冲突阻断和自动治理准入，人工介入只在用户明确要求时出现。",
]

PROFILE_KEYWORDS = re.compile(
    r"(当前命令|任务范围|用户原话|真实表达|不信任|AI 总结|AI总结|Agent 输出|最终输出|日志|证据|置信度|冲突|审查|治理|准入|人工|污染|上下文|历史原文|批量注入|直接|务实)"
)
PROJECT_ONLY_KEYWORDS = re.compile(
    r"(本项目|当前项目|MVP|Web UI|数据库|脚本|目录结构|WORLD_STATE|\.project_cognition|AGENTS\.md|hook|Hermes|Codex)"
)


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).strip("-。；;:： ").lower()


def semantic_key(text: str) -> str:
    normalized = normalize(text)
    if "当前命令" in text or "任务范围" in text or "擅自扩大" in text:
        return "scope_discipline"
    if "用户原话" in text and ("最高权重" in text or "权重最高" in text):
        return "user_utterance_priority"
    if (
        ("不信任" in text and ("总结" in text or "覆盖" in text))
        or ("AI" in text and ("覆盖用户原话" in text or "总结替代" in text or "总结替代" in normalized))
        or ("用户原话不能被AI总结替代" in normalized)
    ):
        return "no_ai_summary_override"
    if ("Agent 输出" in text or "最终输出" in text) and ("日志" in text or "核心记忆" in text):
        return "agent_output_log_only"
    if any(token in text for token in ["证据", "置信度", "冲突", "审查", "治理", "准入"]) and "污染" in text:
        return "evidence_governance_gate"
    if ("人工审查" in text or "人工裁决" in text or "人工 review" in text) and ("默认不" in text or "明确要求" in text):
        return "no_default_human_review"
    if any(token in text for token in ["上下文", "历史原文", "批量注入"]):
        return "context_minimalism"
    return normalized


def extract_section_bullets(content: str, heading: str) -> list[str]:
    match = re.search(rf"## {re.escape(heading)}\n(?P<body>.*?)(?:\n## |\Z)", content, flags=re.S)
    if not match:
        return []
    bullets: list[str] = []
    for line in match.group("body").splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            bullets.append(stripped[2:].strip())
    return [bullet for bullet in bullets if bullet]


def load_existing_principles() -> list[str]:
    if not USER_PROFILE.exists():
        return []
    content = USER_PROFILE.read_text(encoding="utf-8")
    return extract_section_bullets(content, "2. 稳定用户原则")


def clean_claim(claim: str) -> str:
    text = claim.strip()
    text = re.sub(r"^用户原话片段：", "", text)
    text = re.sub(r"^\d+[.、)]\s*", "", text)
    text = re.sub(r"^用户认为", "用户认为", text)
    text = text.strip(" -:：")
    if not text.endswith(("。", "！", "？")):
        text += "。"
    return text


def candidate_decision(item: dict[str, Any], min_confidence: int) -> tuple[bool, str, str]:
    claim = clean_claim(str(item.get("claim", "")))
    if item.get("category") != "user_principle":
        return False, "not_user_principle", claim
    if item.get("status") in {"rejected", "superseded"}:
        return False, f"status_{item.get('status')}", claim
    if int(item.get("confidence", 0)) < min_confidence:
        return False, "confidence_below_threshold", claim
    if item.get("conflicts"):
        return False, "has_conflicts", claim
    if PROJECT_ONLY_KEYWORDS.search(claim):
        return False, "project_only", claim
    stability = str(item.get("stability", ""))
    evidence_count = len(item.get("evidence", []))
    if stability != "stable" and evidence_count < 2:
        return False, "unstable_single_evidence", claim
    if re.search(r"(我看到|当前提交|这轮|README|GitHub|score_candidates|extract_candidates|evals/|\.py|仓库里)", claim):
        return False, "implementation_or_review_detail", claim
    if not PROFILE_KEYWORDS.search(claim):
        return False, "not_profile_keyword", claim
    return True, "accepted", claim


def evaluated_candidates(min_confidence: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    table = read_json(CONFIDENCE_TABLE, {"items": []})
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    rejected_reason_counts: dict[str, int] = {}
    for item in table.get("items", []):
        if item.get("category") != "user_principle":
            continue
        ok, reason, claim = candidate_decision(item, min_confidence)
        entry = {
            "item_id": str(item.get("id", "")),
            "claim": claim,
            "confidence": int(item.get("confidence", 0)),
            "stability": str(item.get("stability", "")),
            "evidence": list(item.get("evidence", [])),
            "reason": reason,
        }
        if ok:
            accepted.append(entry)
        else:
            rejected.append(entry)
            rejected_reason_counts[reason] = rejected_reason_counts.get(reason, 0) + 1
    accepted.sort(key=lambda row: (-int(row.get("confidence", 0)), -len(row.get("evidence", [])), str(row.get("claim", ""))))
    rejected.sort(key=lambda row: (str(row.get("reason", "")), str(row.get("item_id", ""))))
    return accepted, rejected, dict(sorted(rejected_reason_counts.items()))


def merge_principles(existing: list[str], generated: list[str], max_principles: int) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for principle in [*existing, *DEFAULT_PRINCIPLES, *generated]:
        cleaned = principle.strip()
        if not cleaned:
            continue
        key = semantic_key(cleaned)
        if key in seen:
            continue
        seen.add(key)
        merged.append(cleaned)
    return merged[:max_principles]


def render_profile(principles: list[str]) -> str:
    lines = [
        "# USER_PROFILE.md",
        "",
        "## 1. 文件职责",
        "这是当前 Agent 的全局用户画像文件，用于记录跨项目稳定、低变化、需要所有项目共同遵守的用户偏好和工作原则。",
        "",
        "默认路径按 Agent 隔离：Codex 使用 `~/.codex/USER_PROFILE.md`，Hermes 使用 `~/.hermes/USER_PROFILE.md`。项目文件夹不应保存自己的 `USER_PROFILE.md`，只维护该项目的 `.project_cognition/WORLD_STATE.md` 和相关 Markdown/JSONL 文件。",
        "",
        "它不是项目状态、不是任务日志、不是聊天摘要；用户画像只保存跨项目稳定认知。",
        "",
        "## 2. 稳定用户原则",
    ]
    lines.extend(f"- {principle}" for principle in principles)
    lines.extend(
        [
            "",
            "## 3. 更新规则",
            "- 不因单次弱表达更新用户画像。",
            "- 新增画像必须来自用户原话或多次一致表达，并带有高置信证据。",
            "- 与项目有关的临时策略、当前阶段、文件结构和任务进度不得写入本文件，应写入对应项目的 `.project_cognition/WORLD_STATE.md` 或 proposal。",
            "- 如用户画像与项目状态冲突，先按当前用户明确命令执行，并记录冲突来源。",
            "",
        ]
    )
    return "\n".join(lines)


def build_user_profile_report(min_confidence: int, max_principles: int, *, apply_profile: bool) -> dict[str, Any]:
    existing = load_existing_principles()
    accepted, rejected, rejected_reason_counts = evaluated_candidates(min_confidence)
    generated = [str(row.get("claim", "")) for row in accepted]
    principles = merge_principles(existing, generated, max_principles)
    before = USER_PROFILE.read_text(encoding="utf-8") if USER_PROFILE.exists() else ""
    after = render_profile(principles)
    would_change = before != after
    applied = bool(apply_profile and would_change)
    if applied:
        write_text(USER_PROFILE, after)
    report = {
        "user_profile": str(USER_PROFILE),
        "report_path": str(USER_PROFILE_REPORT),
        "applied": applied,
        "would_change": would_change,
        "changed": applied,
        "principles": len(principles),
        "generated_candidates": accepted,
        "generated_candidate_count": len(accepted),
        "rejected_candidates": rejected,
        "rejected_reason_counts": rejected_reason_counts,
        "min_confidence": min_confidence,
        "max_principles": max_principles,
        "mutates_global_profile": applied,
        "profile_preview": after,
    }
    write_json(USER_PROFILE_REPORT, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a USER_PROFILE.md proposal from high-confidence cross-project user principles.")
    parser.add_argument("--min-confidence", type=int, default=95, help="Minimum candidate confidence. Default: 95.")
    parser.add_argument("--max-principles", type=int, default=8, help="Maximum stable user principles to keep. Default: 8.")
    parser.add_argument("--apply-profile", action="store_true", help="Actually write the global USER_PROFILE.md. Default only writes a local proposal/report.")
    args = parser.parse_args()
    report = build_user_profile_report(args.min_confidence, args.max_principles, apply_profile=args.apply_profile)
    summary = {key: value for key, value in report.items() if key != "profile_preview"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
