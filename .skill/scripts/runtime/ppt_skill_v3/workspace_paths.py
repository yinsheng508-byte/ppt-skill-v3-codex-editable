from __future__ import annotations

import os
from pathlib import Path


SKILL_DIRNAME = ".skill"
INPUT_DIRNAME = "输入资料"
OUTPUT_DIRNAME = "PPT输出"
VALID_PROFILES = {"codex", "workbuddy"}


def resolve_skill_root(start: str | Path | None = None) -> Path:
    env_workspace = os.environ.get("PPT_SKILL_WORKSPACE_ROOT")
    if env_workspace:
        skill_root = Path(env_workspace).expanduser().resolve() / SKILL_DIRNAME
        if (skill_root / "SKILL.md").exists():
            return skill_root

    candidates: list[Path] = []
    if start is not None:
        candidates.append(Path(start).expanduser())
    candidates.append(Path.cwd())
    candidates.append(Path(__file__).resolve())

    for candidate in candidates:
        path = candidate.resolve()
        if path.is_file():
            path = path.parent
        for current in [path, *path.parents]:
            if current.name == SKILL_DIRNAME and (current / "SKILL.md").exists():
                return current
            nested = current / SKILL_DIRNAME
            if (nested / "SKILL.md").exists():
                return nested

    return Path(__file__).resolve().parents[3]


def resolve_workspace_root(skill_root: str | Path | None = None) -> Path:
    env_workspace = os.environ.get("PPT_SKILL_WORKSPACE_ROOT")
    if env_workspace:
        return Path(env_workspace).expanduser().resolve()
    resolved_skill_root = Path(skill_root).resolve() if skill_root is not None else resolve_skill_root()
    return resolved_skill_root.parent


def default_input_root(workspace_root: str | Path | None = None) -> Path:
    env_input = os.environ.get("PPT_SKILL_INPUT_ROOT")
    if env_input:
        return Path(env_input).expanduser().resolve()
    root = Path(workspace_root).resolve() if workspace_root is not None else resolve_workspace_root()
    return root / INPUT_DIRNAME


def default_output_root(workspace_root: str | Path | None = None) -> Path:
    env_output = os.environ.get("PPT_SKILL_OUTPUT_ROOT")
    if env_output:
        return Path(env_output).expanduser().resolve()
    root = Path(workspace_root).resolve() if workspace_root is not None else resolve_workspace_root()
    return root / OUTPUT_DIRNAME


def ensure_workspace_dirs(workspace_root: str | Path | None = None) -> dict[str, Path]:
    root = Path(workspace_root).resolve() if workspace_root is not None else resolve_workspace_root()
    input_root = default_input_root(root)
    output_root = default_output_root(root)
    input_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    return {
        "workspace_root": root,
        "skill_root": root / SKILL_DIRNAME,
        "input_root": input_root,
        "output_root": output_root,
    }


def normalize_profile(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in VALID_PROFILES:
        return None
    return normalized
