from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from . import __version__
from .time_utils import now_iso
from .validation import ValidationError
from .workspace_paths import (
    INPUT_DIRNAME,
    OUTPUT_DIRNAME,
    VALID_PROFILES,
    ensure_workspace_dirs,
    normalize_profile,
    resolve_skill_root,
    resolve_workspace_root,
)


STATUS_BEGIN = "<!-- PPT_SKILL_INSTALL_STATUS_BEGIN -->"
STATUS_END = "<!-- PPT_SKILL_INSTALL_STATUS_END -->"
EXCLUDE_BEGIN = "# BEGIN ppt-skill-v3 managed ignore"
EXCLUDE_END = "# END ppt-skill-v3 managed ignore"


def install_profile(target: str, workspace_root: str | Path | None = None) -> dict[str, Any]:
    profile = normalize_profile(target)
    if profile not in VALID_PROFILES:
        raise ValidationError("install profile target must be codex or workbuddy")

    root = Path(workspace_root).resolve() if workspace_root is not None else resolve_workspace_root()
    skill_root = resolve_skill_root(root)
    _require_layout(root, skill_root)
    dirs = ensure_workspace_dirs(root)

    active = root / _entry_name(profile)
    inactive = root / _entry_name("workbuddy" if profile == "codex" else "codex")
    backups: list[Path] = []

    if inactive.exists():
        backups.append(_backup_file(inactive, skill_root))
        inactive.unlink()

    rendered = _render_entry(skill_root, profile, active.name)
    if active.exists() and active.read_text(encoding="utf-8") != rendered:
        backups.append(_backup_file(active, skill_root))
    active.write_text(rendered, encoding="utf-8", newline="\n")

    exclude_path = _sync_git_exclude(root)
    maintenance_path = _update_maintenance_status(skill_root, profile, active.name)

    return {
        "status": "installed",
        "profile": profile,
        "entry_file": active.name,
        "workspace_root": str(root),
        "skill_root": str(skill_root),
        "input_root": str(dirs["input_root"]),
        "output_root": str(dirs["output_root"]),
        "git_exclude": str(exclude_path) if exclude_path else None,
        "maintenance_doc": str(maintenance_path),
        "backups": [str(path) for path in backups],
    }


def inspect_installation(workspace_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(workspace_root).resolve() if workspace_root is not None else resolve_workspace_root()
    skill_root = resolve_skill_root(root)
    agents = root / "AGENTS.md"
    codebuddy = root / "CODEBUDDY.md"
    profile = _detect_profile(agents.exists(), codebuddy.exists())
    expected_entry = _entry_name(profile) if profile in VALID_PROFILES else None

    issues: list[str] = []
    warnings: list[str] = []
    if profile == "conflict":
        issues.append("根目录同时存在 AGENTS.md 和 CODEBUDDY.md；必须只保留当前主体入口。")
    if profile == "missing":
        issues.append("根目录缺少 AGENTS.md 或 CODEBUDDY.md；必须先安装 profile。")
    if not (skill_root / "SKILL.md").exists():
        issues.append(".skill/SKILL.md 不存在。")
    if not (skill_root / "docs" / "维护说明.md").exists():
        issues.append(".skill/docs/维护说明.md 不存在。")
    for dirname in (INPUT_DIRNAME, OUTPUT_DIRNAME):
        if not (root / dirname).is_dir():
            issues.append(f"根目录缺少 {dirname}/。")

    allowed = {".git", ".skill", INPUT_DIRNAME, OUTPUT_DIRNAME}
    if expected_entry:
        allowed.add(expected_entry)
    root_items = sorted(path.name for path in root.iterdir())
    extra_items = [name for name in root_items if name not in allowed]
    if extra_items:
        issues.append(f"根目录存在规范外项目：{', '.join(extra_items)}")

    exclude_path = root / ".git" / "info" / "exclude"
    exclude_synced = _exclude_block_synced(exclude_path)
    if not exclude_synced:
        warnings.append(".git/info/exclude 未同步 PPT Skill 根级忽略规则；运行 install-profile 可修复。")

    encoding_ok = True
    for path in [p for p in (agents, codebuddy, skill_root / "docs" / "维护说明.md") if p.exists()]:
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            encoding_ok = False
            issues.append(f"文件不是有效 UTF-8：{path}")

    return {
        "schema_version": "1.0",
        "ok": not issues,
        "version": __version__,
        "profile": profile,
        "entry_file": expected_entry,
        "workspace_root": str(root),
        "skill_root": str(skill_root),
        "input_root": str(root / INPUT_DIRNAME),
        "output_root": str(root / OUTPUT_DIRNAME),
        "root_items": root_items,
        "extra_root_items": extra_items,
        "git_exclude": str(exclude_path),
        "git_exclude_synced": exclude_synced,
        "utf8_readable": encoding_ok,
        "issues": issues,
        "warnings": warnings,
        "created_at": now_iso(),
    }


def _entry_name(profile: str) -> str:
    return "CODEBUDDY.md" if profile == "workbuddy" else "AGENTS.md"


def _detect_profile(has_agents: bool, has_codebuddy: bool) -> str:
    if has_agents and has_codebuddy:
        return "conflict"
    if has_codebuddy:
        return "workbuddy"
    if has_agents:
        return "codex"
    return "missing"


def _require_layout(root: Path, skill_root: Path) -> None:
    if skill_root != root / ".skill":
        raise ValidationError(f"skill root must be {root / '.skill'}")
    required = [
        skill_root / "SKILL.md",
        skill_root / "docs" / "维护说明.md",
        skill_root / "assets" / "templates" / "入口文档模板.md",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("missing required install files: " + ", ".join(missing))


def _render_entry(skill_root: Path, profile: str, entry_file: str) -> str:
    template = (skill_root / "assets" / "templates" / "入口文档模板.md").read_text(encoding="utf-8")
    values = {
        "{{ENTRY_FILE}}": entry_file,
        "{{PROFILE}}": profile,
        "{{VERSION}}": __version__,
        "{{GENERATED_AT}}": now_iso(),
    }
    for key, value in values.items():
        template = template.replace(key, value)
    return template


def _backup_file(path: Path, skill_root: Path) -> Path:
    backup_dir = skill_root / "docs" / "archive" / "install-profile-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{now_iso().replace(':', '').replace('+', '_')}-{path.name}"
    shutil.copy2(path, backup_path)
    return backup_path


def _managed_exclude_block() -> str:
    return "\n".join(
        [
            EXCLUDE_BEGIN,
            "/输入资料/*",
            "/PPT输出/*",
            "!/输入资料/.gitkeep",
            "!/PPT输出/.gitkeep",
            ".DS_Store",
            "**/.DS_Store",
            "__pycache__/",
            "*.py[cod]",
            ".pytest_cache/",
            ".mypy_cache/",
            ".ruff_cache/",
            "node_modules/",
            "dist/",
            "build/",
            "*.log",
            "*.tmp",
            "*.zip",
            ".env",
            ".env.*",
            "!.env.example",
            EXCLUDE_END,
            "",
        ]
    )


def _sync_git_exclude(root: Path) -> Path | None:
    exclude_path = root / ".git" / "info" / "exclude"
    if not exclude_path.parent.exists():
        return None
    current = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
    block = _managed_exclude_block()
    if EXCLUDE_BEGIN in current and EXCLUDE_END in current:
        before, remainder = current.split(EXCLUDE_BEGIN, 1)
        _old, after = remainder.split(EXCLUDE_END, 1)
        new_text = before.rstrip() + "\n\n" + block + after.lstrip("\n")
    else:
        new_text = current.rstrip() + "\n\n" + block if current.strip() else block
    exclude_path.write_text(new_text, encoding="utf-8", newline="\n")
    return exclude_path


def _exclude_block_synced(exclude_path: Path) -> bool:
    if not exclude_path.exists():
        return False
    text = exclude_path.read_text(encoding="utf-8")
    return EXCLUDE_BEGIN in text and "/PPT输出/*" in text and "/输入资料/*" in text


def _update_maintenance_status(skill_root: Path, profile: str, entry_file: str) -> Path:
    path = skill_root / "docs" / "维护说明.md"
    text = path.read_text(encoding="utf-8")
    block = "\n".join(
        [
            STATUS_BEGIN,
            f"- 当前主体：`{profile}`",
            f"- 当前根入口：`{entry_file}`",
            f"- 当前版本：`{__version__}`",
            f"- 最近安装检查：`{now_iso()}`",
            STATUS_END,
        ]
    )
    if STATUS_BEGIN in text and STATUS_END in text:
        before, remainder = text.split(STATUS_BEGIN, 1)
        _old, after = remainder.split(STATUS_END, 1)
        text = before.rstrip() + "\n\n" + block + "\n\n" + after.lstrip("\n")
    else:
        text = text.rstrip() + "\n\n" + block + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path
