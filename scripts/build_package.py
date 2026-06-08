#!/usr/bin/env python3
"""Build sanitized release archives for Project Cognition System."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT_FILES = {
    ".gitignore",
    "LICENSE",
    "README.md",
}

ROOT_DIRS = {
    ".github/workflows",
    "docs",
    "evals",
    "examples",
    "integrations",
    "scripts",
}

PROJECT_COGNITION_FILES = {
    ".project_cognition/README.md",
    ".project_cognition/WORLD_STATE.md",
    ".project_cognition/WORLD_STATE_COMPACT.md",
}

PROJECT_COGNITION_DIRS = {
    ".project_cognition/rules",
    ".project_cognition/scripts",
    ".project_cognition/schemas",
}

RAW_PLACEHOLDERS = {
    ".project_cognition/raw/agent_interpretations.jsonl",
    ".project_cognition/raw/conflicts.jsonl",
    ".project_cognition/raw/decisions.jsonl",
    ".project_cognition/raw/feedback_events.jsonl",
    ".project_cognition/raw/rule_change_log.jsonl",
    ".project_cognition/raw/tool_evidence.jsonl",
    ".project_cognition/raw/user_utterances.jsonl",
    ".project_cognition/raw/sessions/.gitkeep",
}

PROPOSAL_PLACEHOLDERS = {
    ".project_cognition/proposals/proposed_updates.jsonl",
    ".project_cognition/proposals/proposed_updates.md",
    ".project_cognition/proposals/rule_change_proposals.jsonl",
}

DISTILLED_RELEASE_FILES = {
    ".project_cognition/distilled/confidence_table.json",
    ".project_cognition/distilled/recurring_constraints.md",
    ".project_cognition/distilled/rejected_misunderstandings.md",
    ".project_cognition/distilled/scoring_weights.json",
    ".project_cognition/distilled/stable_project_principles.md",
    ".project_cognition/distilled/stable_user_principles.md",
}

LOG_PLACEHOLDERS = {
    ".project_cognition/logs/file_changes/.gitkeep",
    ".project_cognition/logs/outputs/.gitkeep",
    ".project_cognition/logs/sessions/.gitkeep",
    ".project_cognition/logs/tool_calls/.gitkeep",
}

EXCLUDED_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "venv",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
}

GENERATED_COGNITION_PREFIXES = {
    ".project_cognition/index/",
    ".project_cognition/distilled/rule_change_simulation_",
}

GENERATED_COGNITION_FILES = {
    ".project_cognition/distilled/candidate_clusters.json",
    ".project_cognition/distilled/conflict_clusters.json",
    ".project_cognition/distilled/governance_gate.json",
    ".project_cognition/distilled/scoring_feedback.jsonl",
    ".project_cognition/distilled/scoring_weight_shadow_report.json",
}


def normalize_rel(path: Path) -> str:
    return path.as_posix()


def under(rel: str, prefix: str) -> bool:
    return rel == prefix or rel.startswith(f"{prefix}/")


def should_include(rel: str) -> bool:
    name = Path(rel).name
    if name == ".DS_Store":
        return False
    if any(rel.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        return False
    if rel in GENERATED_COGNITION_FILES:
        return False
    if any(rel.startswith(prefix) for prefix in GENERATED_COGNITION_PREFIXES):
        return False
    if rel in ROOT_FILES:
        return True
    if rel in PROJECT_COGNITION_FILES:
        return True
    if rel in RAW_PLACEHOLDERS:
        return True
    if rel in PROPOSAL_PLACEHOLDERS:
        return True
    if rel in DISTILLED_RELEASE_FILES:
        return True
    if rel in LOG_PLACEHOLDERS:
        return True
    if rel.startswith(".project_cognition/raw/"):
        return False
    if rel.startswith(".project_cognition/proposals/"):
        return False
    if rel.startswith(".project_cognition/logs/"):
        return False
    if rel.startswith(".project_cognition/distilled/"):
        return False
    if any(under(rel, directory) for directory in ROOT_DIRS):
        return True
    if any(under(rel, directory) for directory in PROJECT_COGNITION_DIRS):
        return True
    return False


def iter_release_files(root: Path) -> list[str]:
    files: list[str] = []
    for current_root, dir_names, file_names in os.walk(root):
        current = Path(current_root)
        dir_names[:] = [
            name
            for name in dir_names
            if name not in EXCLUDED_DIR_NAMES
            and not normalize_rel((current / name).relative_to(root)).startswith(".project_cognition/index")
        ]
        for file_name in file_names:
            rel = normalize_rel((current / file_name).relative_to(root))
            if should_include(rel):
                files.append(rel)
    return sorted(files)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b=""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def archive_manifest(root: Path, version: str, files: list[str]) -> dict[str, object]:
    entries = []
    for rel in files:
        path = root / rel
        entries.append(
            {
                "path": rel,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "name": "project-cognition-system",
        "version": version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": git_commit(root),
        "local_only": True,
        "llm_used": False,
        "license": "PolyForm Noncommercial License 1.0.0",
        "privacy": "sanitized release package; private raw evidence, logs, generated indexes, generated reports, and generated clusters are excluded",
        "file_count": len(entries),
        "files": entries,
    }


def add_manifest_to_tar(tar: tarfile.TarFile, package_root: str, manifest_bytes: bytes) -> None:
    info = tarfile.TarInfo(f"{package_root}/PACKAGE_MANIFEST.json")
    info.size = len(manifest_bytes)
    info.mtime = int(datetime.now(timezone.utc).timestamp())
    tar.addfile(info, io.BytesIO(manifest_bytes))


def build_tar(root: Path, output_path: Path, package_root: str, files: list[str], manifest_bytes: bytes) -> None:
    with tarfile.open(output_path, "w:gz") as tar:
        for rel in files:
            tar.add(root / rel, arcname=f"{package_root}/{rel}", recursive=False)
        add_manifest_to_tar(tar, package_root, manifest_bytes)


def build_zip(root: Path, output_path: Path, package_root: str, files: list[str], manifest_bytes: bytes) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel in files:
            archive.write(root / rel, arcname=f"{package_root}/{rel}")
        archive.writestr(f"{package_root}/PACKAGE_MANIFEST.json", manifest_bytes)


def write_external_manifest(
    output_path: Path,
    archive_manifest_data: dict[str, object],
    artifacts: list[Path],
) -> None:
    data = dict(archive_manifest_data)
    data["artifacts"] = [
        {
            "path": artifact.name,
            "size": artifact.stat().st_size,
            "sha256": sha256_file(artifact),
        }
        for artifact in artifacts
    ]
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build sanitized Project Cognition System release archives.")
    parser.add_argument("--root", default=".", help="Repository root to package. Defaults to current directory.")
    parser.add_argument("--output-dir", default="dist", help="Directory for generated artifacts. Defaults to dist/.")
    parser.add_argument("--version", default="dev", help="Release version label, for example v0.4.17.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = (root / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    version = args.version.strip() or "dev"
    package_root = f"project-cognition-system-{version}"
    files = iter_release_files(root)
    if not files:
        raise SystemExit("No release files found. Run this from the repository root or pass --root.")

    manifest = archive_manifest(root, version, files)
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"

    tar_path = output_dir / f"project-cognition-system-{version}.tar.gz"
    zip_path = output_dir / f"project-cognition-system-{version}.zip"
    manifest_path = output_dir / f"project-cognition-system-{version}.manifest.json"

    build_tar(root, tar_path, package_root, files, manifest_bytes)
    build_zip(root, zip_path, package_root, files, manifest_bytes)
    write_external_manifest(manifest_path, manifest, [tar_path, zip_path])

    print(json.dumps(
        {
            "version": version,
            "file_count": len(files),
            "artifacts": [str(tar_path), str(zip_path), str(manifest_path)],
            "tar_sha256": sha256_file(tar_path),
            "zip_sha256": sha256_file(zip_path),
            "manifest_sha256": sha256_file(manifest_path),
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
