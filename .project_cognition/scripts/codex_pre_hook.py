#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re

from common import USER_PROFILE, WORLD_STATE, WORLD_STATE_COMPACT, now_iso


def read_text_file(path, label: str, max_chars: int | None = None) -> str:
    if not path.exists():
        return f"[{label} not found: {path}]\n"
    content = path.read_text(encoding="utf-8")
    if max_chars and len(content) > max_chars:
        return content[:max_chars] + f"\n\n[TRUNCATED: {label} exceeded hook max chars]\n"
    return content


def compact_user_profile(content: str) -> str:
    match = re.search(r"## 2\. 稳定用户原则\n(?P<body>.*?)(?:\n## |\Z)", content, flags=re.S)
    if not match:
        return content
    body = match.group("body").strip()
    return "# USER_PROFILE.md (compact)\n\n## 稳定用户原则\n" + body + "\n"


def ultra_compact_user_profile(content: str) -> str:
    principles = [line.strip()[2:].strip() for line in content.splitlines() if line.strip().startswith("- ")]
    priority_patterns = [
        r"(当前命令|任务范围|擅自)",
        r"(用户原话|真实工具结果|最高权重)",
        r"(Agent 输出|日志)",
        r"(证据|置信度|冲突|审查)",
        r"(上下文|历史原文|批量注入)",
    ]
    selected: list[str] = []
    for pattern in priority_patterns:
        for principle in principles:
            if principle in selected:
                continue
            if re.search(pattern, principle):
                selected.append(principle)
                break
        if len(selected) >= 5:
            break
    for principle in principles:
        if len(selected) >= 5:
            break
        if principle not in selected:
            selected.append(principle)
    if selected:
        return "# USER_PROFILE_COMPACT\n" + "".join(f"- {principle}\n" for principle in selected[:5])
    return (
        "# USER_PROFILE_COMPACT\n"
        "- 忠实执行当前命令，不擅自扩大范围。\n"
        "- 用户原话和真实工具结果最高权重；Agent 输出只作日志。\n"
        "- 防认知污染：核心状态必须有证据、置信度、冲突检查和审查。\n"
        "- 默认最小上下文；历史原文只按需定位读取。\n"
    )


def cap_output(content: str, max_chars: int) -> str:
    if max_chars > 0 and len(content) > max_chars:
        return content[:max_chars] + "\n\n[TRUNCATED: pre-hook output exceeded max chars]\n"
    return content


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex pre-conversation hook: read and emit the project WORLD_STATE.md.")
    parser.add_argument("--format", choices=["markdown", "plain", "json"], default="markdown", help="Output format. Default: markdown.")
    parser.add_argument("--max-chars", type=int, default=6000, help="Maximum total characters to emit. Default: 6000.")
    parser.add_argument(
        "--profile-mode",
        choices=["ultra", "compact", "full", "none"],
        default="full",
        help="How much USER_PROFILE.md to emit. Default: full.",
    )
    parser.add_argument(
        "--world-mode",
        choices=["compact", "full"],
        default="full",
        help="Which world state artifact to emit. Default: full.",
    )
    args = parser.parse_args()

    user_profile = read_text_file(USER_PROFILE, "USER_PROFILE.md")
    if args.profile_mode == "ultra":
        user_profile = ultra_compact_user_profile(user_profile)
    elif args.profile_mode == "compact":
        user_profile = compact_user_profile(user_profile)
    elif args.profile_mode == "none":
        user_profile = ""
    world_path = WORLD_STATE_COMPACT if args.world_mode == "compact" and WORLD_STATE_COMPACT.exists() else WORLD_STATE
    world_state = read_text_file(world_path, world_path.name)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "hook": "codex_pre",
                    "timestamp": now_iso(),
                    "profile_mode": args.profile_mode,
                    "world_mode": args.world_mode,
                    "user_profile": user_profile,
                    "world_state": world_state,
                    "max_chars": args.max_chars,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.format == "plain":
        parts = [part.rstrip() for part in [user_profile, world_state] if part.strip()]
        print(cap_output("\n\n".join(parts), args.max_chars))
        return

    blocks: list[str] = []
    if user_profile.strip():
        blocks.extend(
            [
                "<!-- PROJECT_COGNITION_USER_PROFILE_BEGIN -->",
                user_profile.rstrip(),
                "<!-- PROJECT_COGNITION_USER_PROFILE_END -->",
            ]
        )
    blocks.extend(
        [
            "<!-- PROJECT_COGNITION_WORLD_STATE_BEGIN -->",
            world_state.rstrip(),
            "<!-- PROJECT_COGNITION_WORLD_STATE_END -->",
        ]
    )
    print(cap_output("\n".join(blocks), args.max_chars))


if __name__ == "__main__":
    main()
