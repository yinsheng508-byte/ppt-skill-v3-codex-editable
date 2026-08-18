from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from .json_io import write_json
from .time_utils import now_iso
from .validation import ValidationError


ALLOWED_TOP_LEVEL = {
    "SKILL.md",
    "AGENTS.md",
    "agents",
    "references",
    "assets",
    "scripts",
}

EXCLUDED_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    "dist",
    "outputs",
    "inputs",
    "tests",
}

EXCLUDED_FILE_NAMES = {".DS_Store"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".zip"}
FORBIDDEN_PARTS = {"docs", "src", "node_modules", "outputs", "inputs", "tests", "__pycache__"}
EXCLUDED_NAME_FRAGMENTS = {"任务卡", "验收记录", "改造规划", "改造需求", "dev_smoke"}
EXCLUDED_REL_PATHS: set[str] = set()


def package_skill(skill_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    root = Path(skill_dir).resolve()
    if not (root / "SKILL.md").exists():
        raise FileNotFoundError(f"SKILL.md not found in {root}")
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    files = _collect_files(root)
    if not files:
        raise ValidationError("no files collected for package")

    package_name = root.name
    zip_path = out / f"{package_name}.zip"
    manifest_path = out / f"{package_name}.manifest.json"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relpath in files:
            archive.write(root / relpath, relpath)

    manifest = {
        "schema_version": "2.0",
        "package_name": package_name,
        "zip_path": str(zip_path),
        "manifest_path": str(manifest_path),
        "files": files,
        "files_count": len(files),
        "created_at": now_iso(),
        "rules": {
            "allowed_top_level": sorted(ALLOWED_TOP_LEVEL),
            "excluded_dir_names": sorted(EXCLUDED_DIR_NAMES),
            "excluded_name_fragments": sorted(EXCLUDED_NAME_FRAGMENTS),
            "excluded_suffixes": sorted(EXCLUDED_SUFFIXES),
            "forbidden_parts": sorted(FORBIDDEN_PARTS),
        },
    }
    _validate_zip_matches_manifest(zip_path, files)
    write_json(manifest_path, manifest)
    return manifest


def _collect_files(root: Path) -> list[str]:
    collected: list[str] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if child.name not in ALLOWED_TOP_LEVEL:
            continue
        if child.is_file():
            if _include_file(child):
                collected.append(child.name)
            continue
        for file_path in sorted(child.rglob("*")):
            if file_path.is_file() and _include_file(file_path):
                relpath = file_path.relative_to(root).as_posix()
                if _is_allowed_relpath(relpath):
                    collected.append(relpath)
    return collected


def _include_file(path: Path) -> bool:
    if path.name in EXCLUDED_FILE_NAMES:
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    if any(fragment in path.name for fragment in EXCLUDED_NAME_FRAGMENTS):
        return False
    if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
        return False
    return True


def _is_allowed_relpath(relpath: str) -> bool:
    if relpath in EXCLUDED_REL_PATHS:
        return False
    parts = set(relpath.split("/"))
    return not bool(parts & FORBIDDEN_PARTS)


def _validate_zip_matches_manifest(zip_path: Path, files: list[str]) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        names = sorted(name for name in archive.namelist() if not name.endswith("/"))
    if names != sorted(files):
        raise ValidationError("zip content does not match manifest files")
