#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


COGNITION_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = COGNITION_ROOT.parent


def agent_name() -> str:
    value = os.environ.get("PROJECT_COGNITION_AGENT", "codex").strip().lower()
    if value in {"hermes", "codex"}:
        return value
    return "codex"


def agent_home() -> Path:
    if agent_name() == "hermes":
        return Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


def user_profile_path() -> Path:
    override = os.environ.get("PROJECT_COGNITION_USER_PROFILE")
    if override:
        return Path(override).expanduser()
    return agent_home() / "USER_PROFILE.md"


USER_PROFILE = user_profile_path()

USER_UTTERANCES = COGNITION_ROOT / "raw" / "user_utterances.jsonl"
AGENT_INTERPRETATIONS = COGNITION_ROOT / "raw" / "agent_interpretations.jsonl"
DECISIONS = COGNITION_ROOT / "raw" / "decisions.jsonl"
CONFLICTS = COGNITION_ROOT / "raw" / "conflicts.jsonl"
CONFIDENCE_TABLE = COGNITION_ROOT / "distilled" / "confidence_table.json"
SCORING_WEIGHTS = COGNITION_ROOT / "distilled" / "scoring_weights.json"
SCORING_FEEDBACK = COGNITION_ROOT / "distilled" / "scoring_feedback.jsonl"
WORLD_STATE = COGNITION_ROOT / "WORLD_STATE.md"
WORLD_STATE_COMPACT = COGNITION_ROOT / "WORLD_STATE_COMPACT.md"
PROPOSALS_JSONL = COGNITION_ROOT / "proposals" / "proposed_updates.jsonl"
PROPOSALS_MD = COGNITION_ROOT / "proposals" / "proposed_updates.md"


PREFERENCE_RE = re.compile(r"(希望|偏好|倾向|优先|权重最高|核心|目标|应当|应该|必须|需要|要求)")
REJECTION_RE = re.compile(r"(不要|不得|不能|禁止|不应该|不可|不是|不信任|不引入|不要先)")
EMPHASIS_RE = re.compile(r"(必须|绝不|最高|最低|核心|最重要|强烈|永远|只能|不得)")
LONG_TERM_RE = re.compile(r"(长期|以后|每次|永远|必须遵守|不可违背|稳定|反复)")

TOPIC_KEYWORDS = {
    "memory": ["memory", "记忆", "核心记忆"],
    "world_state": ["WORLD_STATE", "世界状态", "核心状态", "项目世界观"],
    "agent_drift": ["跑偏", "漂移", "误解", "污染", "低漂移"],
    "user_utterance": ["用户原话", "原话", "用户真实表达"],
    "review_flow": ["审查", "proposed", "proposal", "置信度", "冲突"],
    "rag": ["RAG", "检索"],
    "database": ["数据库", "database"],
    "web_ui": ["Web UI", "UI", "界面"],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def short_hash(text: str, length: int = 10) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def compact_timestamp(timestamp: str | None = None) -> str:
    value = timestamp or now_iso()
    compact = re.sub(r"[^0-9A-Za-z]", "", value)
    return compact[:15] if compact else datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def make_id(prefix: str, text: str, timestamp: str | None = None) -> str:
    return f"{prefix}_{compact_timestamp(timestamp)}_{short_hash(text, 8)}"


def stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}_{short_hash('|'.join(parts), 12)}"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} at line {line_no}: {exc}") from exc
    return records


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(path)


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return default or {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: dict[str, Any]) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def detect_signals(text: str, existing_user_texts: list[str] | None = None) -> dict[str, bool]:
    normalized = normalize_text(text)
    existing = [normalize_text(item) for item in existing_user_texts or []]
    return {
        "long_form": len(text) >= 120,
        "repeated": normalized in existing,
        "explicit_preference": bool(PREFERENCE_RE.search(text)),
        "explicit_rejection": bool(REJECTION_RE.search(text)),
        "strong_emphasis": bool(EMPHASIS_RE.search(text)),
    }


def importance_from_signals(text: str, signals: dict[str, bool]) -> int:
    score = 20
    if signals.get("long_form"):
        score += 20
    if len(text) >= 500:
        score += 15
    if signals.get("repeated"):
        score += 10
    if signals.get("explicit_preference"):
        score += 15
    if signals.get("explicit_rejection"):
        score += 15
    if signals.get("strong_emphasis"):
        score += 15
    if LONG_TERM_RE.search(text):
        score += 10
    return max(0, min(100, score))


def detect_topics(text: str) -> list[str]:
    topics: list[str] = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword.lower() in text.lower() for keyword in keywords):
            topics.append(topic)
    return topics


def confidence_table_items() -> list[dict[str, Any]]:
    table = read_json(CONFIDENCE_TABLE, {"items": []})
    return list(table.get("items", []))


def save_confidence_table(items: list[dict[str, Any]]) -> None:
    write_json(CONFIDENCE_TABLE, {"items": items})


def category_choices() -> list[str]:
    return ["user_principle", "project_principle", "constraint", "risk", "strategy", "decision"]


def parse_csv_values(values: list[str] | None) -> list[str]:
    if not values:
        return []
    parsed: list[str] = []
    for value in values:
        parsed.extend([part.strip() for part in value.split(",") if part.strip()])
    return parsed


def bool_from_yes_no(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"yes", "y", "true", "1"}:
        return True
    if lowered in {"no", "n", "false", "0"}:
        return False
    raise ValueError(f"Expected yes/no value, got: {value}")
