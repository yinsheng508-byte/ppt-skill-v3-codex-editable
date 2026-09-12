from __future__ import annotations

from pathlib import Path

from .events import append_event
from .json_io import write_json
from .paths import control_dir, decisions_dir, state_dir
from .stage_docs import sync_stage_docs
from .state import make_initial_state, write_state


USER_STAGE_DIRS = [
    "阶段0_资料整理",
    "阶段1_规划确认",
    "阶段2_图片版PPT",
    "阶段3_逐字稿与教案输出",
    "阶段4_文件整理交付",
]


def create_project(project_name: str, output_root: str | Path) -> Path:
    run_dir = Path(output_root) / project_name
    run_dir.mkdir(parents=True, exist_ok=True)

    for dirname in USER_STAGE_DIRS:
        (run_dir / dirname).mkdir(parents=True, exist_ok=True)

    (run_dir / "阶段2_图片版PPT" / "img").mkdir(parents=True, exist_ok=True)
    (run_dir / "阶段2_图片版PPT" / "pdf").mkdir(parents=True, exist_ok=True)
    (run_dir / "阶段2_图片版PPT" / "封面风格候选").mkdir(parents=True, exist_ok=True)
    (run_dir / "阶段3_逐字稿与教案输出" / "逐字稿").mkdir(parents=True, exist_ok=True)
    (run_dir / "阶段3_逐字稿与教案输出" / "教案设计").mkdir(parents=True, exist_ok=True)

    state_root = state_dir(run_dir)
    for dirname in [
        "阶段0/原始资料",
        "阶段0/原始资料/wechat_images",
        "阶段0/提取文本",
        "阶段0/提取文本/ocr_raw",
        "阶段0/网页资料/微信公众号",
        "工具任务/canva",
        "阶段1",
        "阶段2/packets",
        "阶段2/prompts",
        "阶段2/final_prompts",
        "阶段2/results",
        "阶段2/attempts",
        "阶段2/visual_qa",
        "阶段2/image_api_batches",
        "阶段2/image_gen_batches",
        "阶段2/api_calls",
        "阶段2/image_gen_calls",
        "阶段2/api_outputs",
        "阶段2/image_gen_outputs",
        "阶段2/api_batch_runs",
        "阶段2/image_gen_runs",
        "阶段2/manifests",
        "阶段2/logs",
        "阶段2/cover_options/packets",
        "阶段2/cover_options/prompts",
        "阶段2/cover_options/results",
        "阶段2/cover_options/batches",
        "阶段2/cover_options/api_calls",
        "阶段2/cover_options/image_gen_calls",
        "阶段2/cover_options/api_outputs",
        "阶段2/cover_options/image_gen_outputs",
        "阶段2/cover_options/api_batch_runs",
        "阶段2/cover_options/image_gen_runs",
        "阶段2/cover_options/selection",
        "阶段2/cover_options/style_cards",
        "阶段2/trial_first5/packets",
        "阶段2/trial_first5/prompts",
        "阶段2/trial_first5/results",
        "阶段2/trial_first5/review",
        "阶段2/trial_first5/batches",
        "阶段2/trial_first5/api_calls",
        "阶段2/trial_first5/image_gen_calls",
        "阶段2/trial_first5/api_outputs",
        "阶段2/trial_first5/image_gen_outputs",
        "阶段2/trial_first5/api_batch_runs",
        "阶段2/trial_first5/image_gen_runs",
        "阶段3/packets",
        "阶段3/speaker_script",
        "阶段3/lesson_plan",
        "阶段3/pdf_conversion",
        "阶段3/qa",
        "阶段3/logs",
        "阶段4/manifests",
        "阶段4/pdf_page_images",
        "阶段4/logs",
    ]:
        (state_root / dirname).mkdir(parents=True, exist_ok=True)
    control_dir(run_dir).mkdir(parents=True, exist_ok=True)
    (control_dir(run_dir) / "work_packets").mkdir(parents=True, exist_ok=True)
    decisions_dir(run_dir).mkdir(parents=True, exist_ok=True)

    write_json(state_root / "阶段0" / "materials_index.json", {"schema_version": "2.0", "materials": []})
    state = make_initial_state(project_name, run_dir)
    write_state(run_dir, state)
    append_event(run_dir, "project_created", "runtime", project_name=project_name)
    sync_stage_docs(run_dir)
    return run_dir
