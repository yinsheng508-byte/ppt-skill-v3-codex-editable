from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STATE_CANDIDATES = [
    "agent_state.json",
    "run_manifest.json",
    "planning/stage1_status.json",
    "planning/planning_manifest.json",
    "image_master/stage2_status.json",
    "editable_final/stage3_run_manifest.json",
    "operator_checkpoint.json",
    "operator_runner_checkpoint.json",
    "项目状态.json",
]

ARTIFACT_PATTERNS = [
    "planning/*.md",
    "planning/*.json",
    "image_master/*.pptx",
    "image_master/*.png",
    "image_master/*.jpg",
    "editable_final/*.pptx",
    "editable_final/*.md",
    "editable_final/pages/**/*.png",
    "delivery/**/*",
]


def summarize_v1_project(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir)
    agent_state = _read_json_if_exists(root / "agent_state.json")
    run_manifest = _read_json_if_exists(root / "run_manifest.json")
    state_files = [rel for rel in STATE_CANDIDATES if (root / rel).exists()]
    artifacts = _find_artifacts(root)
    likely_stage = _infer_stage(root, agent_state, artifacts)
    gaps = _infer_gaps(root, agent_state, artifacts, state_files)
    summary = {
        "schema_version": "2.0",
        "mode": "v1_read_only_summary",
        "run_dir": str(root),
        "project_name": agent_state.get("deck_slug") or run_manifest.get("deck_slug") or root.name,
        "likely_stage": likely_stage,
        "agent_state": {
            "current_phase": agent_state.get("current_phase"),
            "current_status": agent_state.get("current_status"),
            "next_action": agent_state.get("next_action"),
            "completed_nodes": agent_state.get("completed_nodes") or [],
            "blocked_by": agent_state.get("blocked_by") or [],
            "risk_flags": agent_state.get("risk_flags") or [],
        },
        "slide_count": run_manifest.get("slide_count"),
        "state_files_found": state_files,
        "visible_artifacts": artifacts,
        "gaps": gaps,
        "suggested_next_steps": _suggest_next_steps(likely_stage, gaps),
        "read_only": True,
    }
    return summary


def render_v1_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# v1 只读迁移摘要",
        "",
        f"- 项目：{summary['project_name']}",
        f"- 目录：{summary['run_dir']}",
        f"- 推断阶段：{summary['likely_stage']}",
        f"- 页数：{summary.get('slide_count') or '未知'}",
        f"- 当前状态：{summary['agent_state'].get('current_status') or '未知'}",
        f"- 下一步字段：{summary['agent_state'].get('next_action') or '未知'}",
        "",
        "## 找到的状态文件",
        "",
    ]
    lines.extend([f"- {item}" for item in summary["state_files_found"]] or ["- 未找到典型 v1 状态文件"])
    lines.extend(["", "## 找到的可见产物", ""])
    lines.extend([f"- {item}" for item in summary["visible_artifacts"]] or ["- 未找到典型可见产物"])
    lines.extend(["", "## 缺口和风险", ""])
    lines.extend([f"- {item}" for item in summary["gaps"]] or ["- 暂未发现明显缺口，但仍需主控大模型人工复核"])
    lines.extend(["", "## 建议下一步", ""])
    lines.extend([f"- {item}" for item in summary["suggested_next_steps"]])
    lines.extend(["", "> 这是只读摘要，不写入 v3 state，不接管 v1 runner。", ""])
    return "\n".join(lines)


def write_v1_summary(summary: dict[str, Any], output: str | Path) -> Path:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_v1_summary_markdown(summary), encoding="utf-8")
    return target


def _read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_error": "json_decode_error", "_path": str(path)}
    return data if isinstance(data, dict) else {"_value": data}


def _find_artifacts(root: Path) -> list[str]:
    artifacts: set[str] = set()
    for pattern in ARTIFACT_PATTERNS:
        for path in root.glob(pattern):
            if path.is_file():
                artifacts.add(path.relative_to(root).as_posix())
    return sorted(artifacts)


def _infer_stage(root: Path, agent_state: dict[str, Any], artifacts: list[str]) -> str:
    phase = str(agent_state.get("current_phase") or "")
    if (root / "editable_final" / "final_editable.pptx").exists() or phase in {"phase3", "stage3"}:
        return "v1遗留阶段3编辑重建PPT"
    if (root / "image_master" / "image_only.pptx").exists() or phase in {"phase2", "stage2"}:
        return "阶段2_图片版PPT"
    if any(item.startswith("planning/") for item in artifacts) or phase in {"phase1", "stage1"}:
        return "阶段1_规划确认"
    return "阶段0_资料整理"


def _infer_gaps(root: Path, agent_state: dict[str, Any], artifacts: list[str], state_files: list[str]) -> list[str]:
    gaps: list[str] = []
    if not state_files:
        gaps.append("未找到典型 v1 状态文件，只能按目录产物粗略判断")
    if not agent_state:
        gaps.append("未找到 agent_state.json，无法信任自动阶段字段")
    if not (root / "controller_decisions").exists() and not (root / "_decisions").exists() and not (root / "_state" / "decisions").exists():
        gaps.append("未找到 v3 风格显式主控决策，阶段确认需要人工复核")
    if not any(item.endswith(".pptx") for item in artifacts):
        gaps.append("未找到 PPTX 产物")
    if not (root / "editable_final" / "final_editable.pptx").exists():
        gaps.append("未找到 v1 final_editable.pptx，不能直接视为可编辑交付完成")
    if agent_state.get("blocked_by"):
        gaps.append("v1 状态里存在 blocked_by，需要先处理阻塞项")
    if agent_state.get("risk_flags"):
        gaps.append("v1 状态里存在 risk_flags，需要主控大模型复核风险")
    return gaps


def _suggest_next_steps(likely_stage: str, gaps: list[str]) -> list[str]:
    steps = ["不要运行 v1 runner；先由主控大模型读取本摘要和可见产物。"]
    if likely_stage == "阶段0_资料整理":
        steps.append("按 v3 新项目方式重新整理资料，并由主控大模型撰写阶段1规划。")
    elif likely_stage == "阶段1_规划确认":
        steps.append("把 v1 planning 内容作为参考，重新生成 v3 阶段1用户确认文档。")
    elif likely_stage == "阶段2_图片版PPT":
        steps.append("核对图片来源证据；缺少 provider 证据时按 v3 阶段2重新登记或返工。")
    else:
        steps.append("核对历史可编辑 PPTX 是否真实可打开、页数是否匹配；若承接 v3，应由主控确认锁定稿后进入新阶段3逐字稿与教案输出。")
    if gaps:
        steps.append("先解决缺口清单，再考虑创建 v3 项目承接。")
    return steps
