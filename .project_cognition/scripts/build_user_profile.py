#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from common import CONFIDENCE_TABLE, USER_PROFILE, read_json, write_text


DEFAULT_PRINCIPLES = [
    "用户明确要求忠实执行当前命令，不擅自扩大任务范围。",
    "用户认为用户原话权重最高，尤其是长段、反复强调、明确偏好和明确否定。",
    "用户不信任 AI 用自己的总结覆盖用户真实表达。",
    "用户认为 Agent 最终输出权重最低，应作为日志或运行产物，而不是核心记忆。",
    "用户希望通过证据、置信度、冲突检测和审查流程防止认知污染。",
    "用户希望默认上下文保持最小化，不把历史对话作为每轮默认上下文；需要历史原文时应定位指定原文读取，而不是批量注入全部历史。",
]

PROFILE_KEYWORDS = re.compile(
    r"(当前命令|任务范围|用户原话|真实表达|不信任|AI 总结|AI总结|Agent 输出|最终输出|日志|证据|置信度|冲突|审查|污染|上下文|历史原文|批量注入|直接|务实)"
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
    if any(token in text for token in ["证据", "置信度", "冲突", "审查"]) and "污染" in text:
        return "evidence_review_flow"
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


def is_profile_candidate(item: dict[str, Any], min_confidence: int) -> bool:
    if item.get("category") != "user_principle":
        return False
    if item.get("status") in {"rejected", "superseded"}:
        return False
    if int(item.get("confidence", 0)) < min_confidence:
        return False
    if item.get("conflicts"):
        return False
    stability = str(item.get("stability", ""))
    evidence_count = len(item.get("evidence", []))
    if stability != "stable" and evidence_count < 2:
        return False
    claim = clean_claim(str(item.get("claim", "")))
    if not PROFILE_KEYWORDS.search(claim):
        return False
    if PROJECT_ONLY_KEYWORDS.search(claim):
        return False
    return True


def candidate_principles(min_confidence: int) -> list[str]:
    table = read_json(CONFIDENCE_TABLE, {"items": []})
    candidates: list[tuple[int, int, str]] = []
    for item in table.get("items", []):
        if not is_profile_candidate(item, min_confidence):
            continue
        candidates.append((int(item.get("confidence", 0)), len(item.get("evidence", [])), clean_claim(str(item.get("claim", "")))))
    candidates.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return [claim for _, _, claim in candidates]


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or update USER_PROFILE.md from high-confidence cross-project user principles.")
    parser.add_argument("--min-confidence", type=int, default=95, help="Minimum candidate confidence. Default: 95.")
    parser.add_argument("--max-principles", type=int, default=8, help="Maximum stable user principles to keep. Default: 8.")
    args = parser.parse_args()

    existing = load_existing_principles()
    generated = candidate_principles(args.min_confidence)
    principles = merge_principles(existing, generated, args.max_principles)
    before = USER_PROFILE.read_text(encoding="utf-8") if USER_PROFILE.exists() else ""
    after = render_profile(principles)
    changed = before != after
    if changed:
        write_text(USER_PROFILE, after)
    print(
        json.dumps(
            {
                "user_profile": str(USER_PROFILE),
                "changed": changed,
                "principles": len(principles),
                "generated_candidates": len(generated),
                "min_confidence": args.min_confidence,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
