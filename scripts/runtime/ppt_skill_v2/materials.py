from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .json_io import read_json, write_json
from .paths import state_dir
from .time_utils import now_iso


CONTROLLER_SUMMARY_BEGIN = "<!-- controller-summary:start -->"
CONTROLLER_SUMMARY_END = "<!-- controller-summary:end -->"
DEFAULT_CONTROLLER_SUMMARY = "（主控大模型在这里维护跨 PPT、Word、PDF、文本和用户口述资料的深度摘要与缺口判断。）"


def materials_index_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / "阶段0" / "materials_index.json"


def load_materials(run_dir: str | Path) -> dict[str, Any]:
    path = materials_index_path(run_dir)
    if not path.exists():
        return {"schema_version": "2.0", "materials": []}
    return read_json(path)


def add_material(
    run_dir: str | Path,
    *,
    material_type: str,
    source: str,
    label: str | None = None,
    material_kind: str | None = None,
    mime_hint: str | None = None,
    role_hint: str | None = None,
    source_priority: str | None = None,
    locator_hint: str | None = None,
) -> dict[str, Any]:
    root = Path(run_dir)
    index = load_materials(root)
    materials = index.setdefault("materials", [])
    material_id = f"mat_{len(materials) + 1:04d}"
    record: dict[str, Any] = {
        "id": material_id,
        "type": material_type,
        "label": _initial_label(material_type, source, label, material_id),
        "source": source,
        "material_kind": material_kind,
        "original_name": _initial_original_name(material_type, source, label),
        "extension": None,
        "mime_hint": mime_hint,
        "role_hint": role_hint,
        "source_priority": source_priority,
        "locator_hint": locator_hint,
        "created_at": now_iso(),
    }
    if material_type == "file":
        source_path = Path(source).expanduser()
        if not source_path.exists():
            raise FileNotFoundError(f"material file not found: {source_path}")
        record["original_name"] = source_path.name
        record["extension"] = source_path.suffix.lower() or None
        record["material_kind"] = material_kind or _infer_material_kind(source_path.suffix)
        target = state_dir(root) / "阶段0" / "原始资料" / f"{material_id}_{source_path.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        record["stored_path"] = str(target.relative_to(root))
    elif material_type == "text":
        record["material_kind"] = material_kind or "text"
        target = state_dir(root) / "阶段0" / "提取文本" / f"{material_id}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        record["stored_path"] = str(target.relative_to(root))
    elif material_type == "url":
        record["material_kind"] = material_kind or "url"
        record["stored_path"] = None
    else:
        raise ValueError("material_type must be one of: file, text, url")
    materials.append(record)
    write_json(materials_index_path(root), index)
    refresh_material_docs(root)
    return record


def list_materials(run_dir: str | Path) -> list[dict[str, Any]]:
    return list(load_materials(run_dir).get("materials", []))


def refresh_material_docs(run_dir: str | Path) -> None:
    root = Path(run_dir)
    materials = list_materials(root)
    lines = ["# 资料清单", ""]
    if not materials:
        lines.append("暂无资料。")
    else:
        lines.append("| ID | 类型 | 名称 | 材料类型 | 角色 | 优先级 | 定位提示 | 位置 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for item in materials:
            lines.append(
                f"| {_markdown_cell(item.get('id'))} | {_markdown_cell(item.get('type'))} | {_markdown_cell(item.get('label'))} | "
                f"{_markdown_cell(item.get('material_kind'))} | {_markdown_cell(item.get('role_hint'))} | "
                f"{_markdown_cell(item.get('source_priority'))} | {_markdown_cell(item.get('locator_hint'))} | "
                f"{_markdown_cell(item.get('stored_path') or item.get('source'))} |"
            )
    lines.append("")
    (root / "阶段0_资料整理" / "资料清单.md").write_text("\n".join(lines), encoding="utf-8")

    summary_path = root / "阶段0_资料整理" / "资料摘要.md"
    preserved_summary = _preserve_controller_summary(summary_path)
    summary = [
        "# 资料摘要",
        "",
        f"已登记资料数量：{len(materials)}",
        "",
        "## Runtime 登记概览",
        "",
        *_summary_lines(materials),
        "",
        "## 主控摘要区",
        "",
        CONTROLLER_SUMMARY_BEGIN,
        preserved_summary,
        CONTROLLER_SUMMARY_END,
        "",
        "Runtime 只登记和归档资料，不生成正式阶段1规划。",
        "",
    ]
    summary_path.write_text("\n".join(summary), encoding="utf-8")


def _infer_material_kind(extension: str) -> str:
    normalized = extension.lower().lstrip(".")
    if normalized in {"ppt", "pptx"}:
        return "ppt"
    if normalized in {"doc", "docx"}:
        return "word"
    if normalized == "pdf":
        return "pdf"
    if normalized in {"md", "txt"}:
        return "text"
    return normalized or "file"


def _display(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "待判断"


def _markdown_cell(value: Any) -> str:
    return _display(value).replace("\n", " ").replace("|", "\\|")


def _initial_original_name(material_type: str, source: str, label: str | None) -> str:
    if isinstance(label, str) and label.strip():
        return label.strip()
    if material_type == "text":
        return "text_material"
    return source


def _initial_label(material_type: str, source: str, label: str | None, material_id: str) -> str:
    if isinstance(label, str) and label.strip():
        return label.strip()
    if material_type == "file":
        return Path(source).expanduser().name
    if material_type == "text":
        return f"文本资料 {material_id}"
    return source


def _preserve_controller_summary(summary_path: Path) -> str:
    if not summary_path.exists():
        return DEFAULT_CONTROLLER_SUMMARY
    existing = summary_path.read_text(encoding="utf-8")
    start = existing.find(CONTROLLER_SUMMARY_BEGIN)
    end = existing.find(CONTROLLER_SUMMARY_END)
    if start == -1 or end == -1 or end < start:
        return DEFAULT_CONTROLLER_SUMMARY
    preserved = existing[start + len(CONTROLLER_SUMMARY_BEGIN) : end].strip()
    return preserved or DEFAULT_CONTROLLER_SUMMARY


def _summary_lines(materials: list[dict[str, Any]]) -> list[str]:
    if not materials:
        return ["暂无资料。"]
    counts: dict[str, int] = {}
    for item in materials:
        kind = _display(item.get("material_kind"))
        counts[kind] = counts.get(kind, 0) + 1
    return [f"- {kind}：{count} 个" for kind, count in sorted(counts.items())]
