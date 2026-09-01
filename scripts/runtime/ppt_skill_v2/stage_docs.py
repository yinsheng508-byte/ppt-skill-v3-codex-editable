from __future__ import annotations

from pathlib import Path

from .deliverable_naming import project_deliverable_relpaths
from .state import read_state


def _write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def sync_stage_docs(run_dir: str | Path) -> None:
    root = Path(run_dir)
    state = read_state(root)
    overview = f"""# 项目总览

## 基本信息

- 项目名称：{state['project_name']}
- 当前阶段：{state['current_stage']}
- 当前状态：{state['status']}
- 待处理人：{state['required_actor']}
- 最近决策：{state.get('last_decision_id') or '暂无'}

## 下一步

{state.get('next_required_action', '暂无')}

## 用户确认

- 阶段1规划：{_yes_no(state['confirmed'].get('stage1_plan'))}
- 阶段2试样：{_yes_no(state['confirmed'].get('stage2_trial_first5'))}
- 阶段2图片版 PDF：{_yes_no(state['confirmed'].get('stage2_image_deck'))}
- 阶段3文字坐标：{_yes_no(state['confirmed'].get('stage3_coordinate_plan'))}
- 阶段3可编辑 PPT：{_yes_no(state['confirmed'].get('stage3_editable_deck'))}
- 阶段4锁定稿来源：{_stage4_source_label(state)}
- 阶段4演讲稿输出：{_yes_no(state['confirmed'].get('stage4_speaker_script'))}
"""
    (root / "项目总览.md").write_text(overview, encoding="utf-8")

    _write_if_missing(
        root / "阶段0_资料整理" / "资料清单.md",
        "# 资料清单\n\n暂无资料。由主控大模型登记素材后刷新。\n",
    )
    _write_if_missing(
        root / "阶段0_资料整理" / "资料摘要.md",
        "# 资料摘要\n\n暂无摘要。主控大模型根据资料整理，当前步骤不自动生成正式规划。\n",
    )
    _write_if_missing(root / "阶段1_规划确认" / "页面规划.md", "# 页面规划\n\n待主控大模型填写 pageType、最终可见中文文字、事实保护点和每页目的。\n")
    _write_if_missing(root / "阶段1_规划确认" / "每页干净逐字稿.md", "# 每页干净逐字稿\n\n待主控大模型按页整理最终可见文字。本文档用于用户审阅每页内容，必须与 `页面规划.md` 和 `_state/阶段1/content.json` 一致。\n")
    _write_if_missing(root / "阶段1_规划确认" / "风格与提示词方案.md", "# 风格与提示词方案\n\n待主控大模型填写初步风格方向、视觉系统草案、全局提示词方向和逐页提示词概要。结构化 brief 放 `_state/阶段1/slide_prompt_briefs.json`。\n")

    user_artifacts = state.get("user_artifacts", {})
    if not isinstance(user_artifacts, dict):
        user_artifacts = {}

    has_stage2_index_material = any(
        user_artifacts.get(key)
        for key in ("stage2_cover_options", "stage2_trial_first5", "stage2_image_deck")
    )
    if has_stage2_index_material:
        _write_stage2_index(root, state)

    has_stage3_index_material = any(
        user_artifacts.get(key)
        for key in ("stage3_coordinate_preview", "stage3_editable_deck")
    )
    if has_stage3_index_material:
        _write_stage3_index(root, state)

    _write_if_missing(
        root / "阶段4_演讲稿输出" / "讲稿生成说明.md",
        "# 讲稿生成说明\n\n锁定稿经用户确认后，由主控大模型生成演讲逐字稿、Word 和 PDF。\n",
    )
    _write_stage4_placeholder_if_ready(root, state)


def _write_stage2_index(root: Path, state: dict) -> None:
    stage2_doc = f"""# 阶段2_确认说明

- 当前状态：{state['status']}
- 封面风格候选：{state['user_artifacts'].get('stage2_cover_options') or '暂无'}
- 已选封面风格：{_yes_no(state['confirmed'].get('stage2_cover_style'))}
- 阶段2试样：{state['user_artifacts'].get('stage2_trial_first5') or '暂无'}
- 阶段2试样已确认：{_yes_no(state['confirmed'].get('stage2_trial_first5'))}
- 图片版 PDF：{state['user_artifacts'].get('stage2_image_deck') or '暂无'}
- 下一步：{state.get('next_required_action', '等待主控大模型推进')}
"""
    (root / "阶段2_图片版PPT" / "阶段2_确认说明.md").write_text(stage2_doc, encoding="utf-8")


def _write_stage3_index(root: Path, state: dict) -> None:
    runtime_artifacts = state.get("runtime_artifacts", {})
    if not isinstance(runtime_artifacts, dict):
        runtime_artifacts = {}
    quality = state.get("quality", {})
    if not isinstance(quality, dict):
        quality = {}
    stage3_doc = f"""# 阶段3_确认说明

- 当前状态：{state['status']}
- 文字坐标确认：{_yes_no(state['confirmed'].get('stage3_coordinate_plan'))}
- 拆字计划：{runtime_artifacts.get('stage3_text_unit_split_plan') or '暂无'}
- 字体校准 profile：{runtime_artifacts.get('stage3_font_calibration_profile') or '暂无'}
- 字体 probe 状态：{quality.get('stage3_font_calibration_profile') or '暂无'}
- 坐标复刻预览：{state['user_artifacts'].get('stage3_coordinate_preview') or '暂无'}
- 可编辑 PPT：{state['user_artifacts'].get('stage3_editable_deck') or '暂无'}
- 下一步：{state.get('next_required_action', '等待主控大模型推进')}
"""
    (root / "阶段3_可编辑PPT" / "阶段3_确认说明.md").write_text(stage3_doc, encoding="utf-8")


def _write_stage4_placeholder_if_ready(root: Path, state: dict) -> None:
    if state.get("current_stage") != "stage4":
        return
    if state.get("status") not in {"ready_for_stage4_script"}:
        return
    relpath = project_deliverable_relpaths(root, state=state)["stage4_speaker_script"]
    _write_if_missing(
        root / relpath,
        "# 逐字稿\n\n待主控大模型基于已确认锁定稿填写。\n",
    )


def _yes_no(value: object) -> str:
    return "已确认" if value else "未确认"


def _stage4_source_label(state: dict) -> str:
    source = state.get("stage4_locked_presentation_source")
    if not isinstance(source, dict):
        return "暂无"
    labels = {
        "stage3_editable_deck": "阶段3可编辑 PPT",
        "stage2_image_deck": "阶段2图片版 PDF",
        "external_editable_deck": "外部锁定稿",
    }
    mode = labels.get(source.get("source_mode"), source.get("source_mode") or "未知")
    path = source.get("source_path") or "未记录路径"
    return f"{mode}｜{path}"
