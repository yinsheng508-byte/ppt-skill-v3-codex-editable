from __future__ import annotations

from pathlib import Path

from .state import read_state
from .ppt_consistency import CONSISTENCY_RELPATH, consistency_template_path


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
- 阶段2封面风格：{_yes_no(state['confirmed'].get('stage2_cover_style'))}
- 阶段2试样：{_yes_no(state['confirmed'].get('stage2_trial_first5'))}
- 阶段2图片版 PDF：{_yes_no(state['confirmed'].get('stage2_image_deck'))}
- 阶段3锁定稿来源：{_stage3_source_label(state)}
- 阶段3逐字稿输出：{_yes_no(state['confirmed'].get('stage3_speaker_script'))}
- 阶段3教案设计：{_yes_no(state['confirmed'].get('stage3_lesson_plan'))}
- 阶段4文件整理交付：{_yes_no(state['confirmed'].get('stage4_deliverables'))}
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
    if state.get("current_stage") != "stage0" or state.get("confirmed", {}).get("stage1_plan"):
        _write_if_missing(root / CONSISTENCY_RELPATH, consistency_template_path().read_text(encoding="utf-8"))

    # 说明类薄索引不再作为用户可见目录结构的一部分；阶段证据以
    # _state 下的 state、manifest、decision 为准。


def _yes_no(value: object) -> str:
    return "已确认" if value else "未确认"


def _stage3_source_label(state: dict) -> str:
    source = state.get("stage3_locked_presentation_source")
    if not isinstance(source, dict):
        return "暂无"
    labels = {
        "stage2_image_deck": "阶段2图片版 PDF",
        "external_locked_deck": "外部锁定稿",
    }
    mode = labels.get(source.get("source_mode"), source.get("source_mode") or "未知")
    path = source.get("source_path") or "未记录路径"
    return f"{mode}｜{path}"
