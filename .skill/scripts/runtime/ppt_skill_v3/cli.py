from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .decisions import execute_decision, load_decision, record_decision
from .decision_factory import make_decision
from .control import build_next_action, build_resume_brief, render_resume_brief_markdown
from .canva_task import create_canva_task_brief, record_canva_task_event, record_canva_task_export
from .cover_options import dispatch_cover_option_packets, promote_selected_cover_option
from .deliverable_organizer import organize_deliverables
from .doctor import check_project
from .drift_check import run_drift_check
from .image_deck import build_image_deck
from .image_api import configure_image_api_key, default_batch_path_for_stage, image_api_key_status, load_image_api_config, run_image_api_batch
from .image_packets import dispatch_image_api_packets, dispatch_image_generation_packets
from .image_results import record_image_result
from .image_routes import DEFAULT_IMAGE_GENERATION_ROUTE
from .installation import inspect_installation, install_profile
from .json_io import read_json
from .layout_migration import migrate_decisions_layout
from .workspace_paths import default_output_root
from .education_context import subject_profile_registry_report
from .lesson_plan import build_lesson_plan
from .lesson_plan_context import build_lesson_plan_context, lesson_plan_context_path
from .lesson_plan_qa import record_lesson_plan_qa
from .migration_v1 import render_v1_summary_markdown, summarize_v1_project, write_v1_summary
from .materials import add_material, list_materials
from .project_init import create_project
from .qa_drafts import create_stage2_visual_qa_draft
from .layout_safety_contract import record_layout_safety_contract
from .stage_docs import sync_stage_docs
from .image_style import accept_image_result, migrate_image_style_doc, reconcile_image_style
from .image_prompt_docs import prepare_image_request, refresh_prompt_delivery, export_prompt_document
from .stage1_plan import create_stage1_draft, sync_stage1_derivatives, validate_stage1_project
from .stage2_trial import (
    authorize_stage2_trial_skip,
    dispatch_stage2_remaining_packets,
    dispatch_stage2_trial_first5_packets,
    migrate_legacy_trial_first5_images,
    promote_stage2_trial_first5,
)
from .stage2_visual_qa import record_stage2_aesthetic_review
from .state import read_state
from .speaker_script import build_speaker_script
from .style_templates import (
    list_style_templates,
    resolve_style_template,
    style_template_summary,
    validate_style_templates_report,
)
from .validation import ValidationError
from .work_packets import close_work_packet, create_work_packet


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pptctl",
        description="PPT Skill v3 passive runtime CLI.",
    )
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Create a v3 project skeleton.")
    init_parser.add_argument("--project-name", required=True)
    init_parser.add_argument("--output-root")

    install_profile_parser = subparsers.add_parser("install-profile", help="Install the root entry file for Codex or WorkBuddy.")
    install_profile_parser.add_argument("--target", choices=["codex", "workbuddy"], required=True)
    inspect_installation_parser = subparsers.add_parser("inspect-installation", help="Inspect root entry, .skill layout, UTF-8, and ignore sync.")
    migrate_decisions_parser = subparsers.add_parser("migrate-decisions-layout", help="Move legacy project _decisions into _state/decisions.")
    migrate_decisions_parser.add_argument("--run-dir", required=True)
    migrate_decisions_parser.add_argument("--dry-run", action="store_true")

    style_migrate_parser = subparsers.add_parser("migrate-image-style", help="显式合并旧风格文档，保留原文与确认状态。")
    style_migrate_parser.add_argument("--run-dir", required=True)
    style_migrate_parser.add_argument("--merged-file")
    accept_image_parser = subparsers.add_parser("accept-image-result", help="主控核对后接纳旧图继续适用于当前图片风格。")
    accept_image_parser.add_argument("--run-dir", required=True)
    accept_image_parser.add_argument("--result", required=True)
    accept_image_parser.add_argument("--reason", required=True)
    reconcile_style_parser = subparsers.add_parser("reconcile-image-style", help="记录图片风格变更后的受影响页和可复用页。")
    reconcile_style_parser.add_argument("--run-dir", required=True)
    reconcile_style_parser.add_argument("--reason", required=True)
    reconcile_style_parser.add_argument("--affected-slide", type=int, action="append", default=[])
    reconcile_style_parser.add_argument("--reusable-slide", type=int, action="append", default=[])

    plan_parser = subparsers.add_parser("record-image-prompt-plan", help="保存主控整理的本页画面计划，继承适用组件与限制，不发起生图。")
    plan_parser.add_argument("--run-dir", required=True)
    plan_parser.add_argument("--slide-index", type=int, required=True)
    plan_parser.add_argument("--plan-file", required=True)
    plan_parser.add_argument("--option-id", choices=["A", "B", "C", "D"])
    sources_parser = subparsers.add_parser("image-prompt-sources", help="只读查看当前画面计划的来源与依据。")
    sources_parser.add_argument("--run-dir", required=True)
    sources_parser.add_argument("--slide-index", type=int, required=True)
    sources_parser.add_argument("--option-id", choices=["A", "B", "C", "D"])
    prepare_prompt_parser = subparsers.add_parser("prepare-image-request", help="生图调用前保存本次提示词快照，内置工具结果须用返回的快照路径登记。")
    prepare_prompt_parser.add_argument("--run-dir", required=True)
    prepare_prompt_parser.add_argument("--packet", required=True)
    refresh_prompts_parser = subparsers.add_parser("refresh-image-prompts", help="从已有请求和图片恢复提示词文档，不重新生图。")
    refresh_prompts_parser.add_argument("--run-dir", required=True)
    refresh_prompts_parser.add_argument("--output-dir")
    status_parser = subparsers.add_parser("status", help="Read project state.")
    status_parser.add_argument("--run-dir", required=True)
    resume_brief_parser = subparsers.add_parser("resume-brief", help="Build a resumable project control brief.")
    resume_brief_parser.add_argument("--run-dir", required=True)
    resume_brief_parser.add_argument("--format", choices=["json", "markdown"], default="json")
    resume_brief_parser.add_argument("--persist", action="store_true", help="Explicitly save the generated control brief.")
    next_action_parser = subparsers.add_parser("next-action", help="Build the next permitted controller action summary.")
    next_action_parser.add_argument("--run-dir", required=True)
    next_action_parser.add_argument("--persist", action="store_true", help="Explicitly save the generated next-action view.")
    drift_check_parser = subparsers.add_parser("drift-check", help="Check whether a controller action would drift across stage boundaries.")
    drift_check_parser.add_argument("--run-dir", required=True)
    drift_check_parser.add_argument("--action")
    drift_check_parser.add_argument("--persist", action="store_true", help="Explicitly save the generated drift report.")
    create_packet_parser = subparsers.add_parser("create-work-packet", help="Create one bounded long-task work packet.")
    create_packet_parser.add_argument("--run-dir", required=True)
    create_packet_parser.add_argument("--stage", choices=["stage0", "stage1", "stage2", "stage3", "stage4"], required=True)
    create_packet_parser.add_argument("--action", required=True)
    create_packet_parser.add_argument("--slide", type=int, action="append", default=[])
    create_packet_parser.add_argument("--allowed-command", action="append", default=[])
    create_packet_parser.add_argument("--input-artifact", action="append", default=[])
    create_packet_parser.add_argument("--expected-output", action="append", default=[])
    create_packet_parser.add_argument("--stop-condition", action="append", default=[])
    create_packet_parser.add_argument("--requires-user-confirmation", action="store_true")
    create_packet_parser.add_argument("--confirmation-decision-type")
    close_packet_parser = subparsers.add_parser("close-work-packet", help="Close one active work packet with a completion summary.")
    close_packet_parser.add_argument("--run-dir", required=True)
    close_packet_parser.add_argument("--packet", required=True)
    close_packet_parser.add_argument("--status", choices=["completed", "blocked", "failed"], required=True)
    close_packet_parser.add_argument("--summary", required=True)

    sync_parser = subparsers.add_parser("sync-stage-docs", help="Refresh user-facing stage docs.")
    sync_parser.add_argument("--run-dir", required=True)
    organize_parser = subparsers.add_parser(
        "organize-deliverables",
        help="Copy existing stage1/stage2/stage3 deliverables into the project topic folder and render stage3 PDFs with pdftoppm.",
    )
    organize_parser.add_argument("--run-dir", required=True)
    canva_task_parser = subparsers.add_parser("create-canva-task-brief", help="Create a stage-external Canva auxiliary edit task brief.")
    canva_task_parser.add_argument("--run-dir", required=True)
    canva_task_parser.add_argument("--task-id")
    canva_task_parser.add_argument("--trigger", default="/canva")
    canva_task_parser.add_argument("--provider", default="canva_international")
    canva_task_parser.add_argument("--host-profile", choices=["codex", "workbuddy", "unknown"], default="unknown")
    canva_task_parser.add_argument("--executor", choices=["canva_mcp", "canva_plugin", "manual_handoff", "unresolved"], default="unresolved")
    canva_event_parser = subparsers.add_parser("record-canva-task-event", help="Append one sanitized stage-external Canva batch event.")
    canva_event_parser.add_argument("--run-dir", required=True)
    canva_event_parser.add_argument("--task-id", required=True)
    canva_event_parser.add_argument("--event-json", required=True, help="Inline JSON object for one batch_edit event.")
    canva_event_parser.add_argument(
        "--status",
        choices=[
            "brief_ready",
            "waiting_manual_magic_layers",
            "ready_for_page_audit",
            "editing",
            "waiting_batch_confirmation",
            "completed",
            "cancelled",
            "blocked_connector",
        ],
    )
    canva_export_parser = subparsers.add_parser("record-canva-task-export", help="Record one sanitized stage-external Canva export attempt.")
    canva_export_parser.add_argument("--run-dir", required=True)
    canva_export_parser.add_argument("--task-id", required=True)
    canva_export_parser.add_argument("--export-json", required=True, help="Inline JSON object for one actual export attempt.")
    validate_stage1_parser = subparsers.add_parser("validate-stage1", help="Validate controller-authored stage1 plan.")
    validate_stage1_parser.add_argument("--run-dir", required=True)
    sync_stage1_parser = subparsers.add_parser("sync-stage1-derivatives", help="Regenerate stage1 plan, prompt briefs, and review text from content.json.")
    sync_stage1_parser.add_argument("--run-dir", required=True)
    layout_safety_parser = subparsers.add_parser("record-layout-safety-contract", help="Record controller-authored stage1 layout safety contract.")
    layout_safety_parser.add_argument("--run-dir", required=True)
    layout_safety_parser.add_argument("--contract", required=True)
    stage1_draft_parser = subparsers.add_parser("create-stage1-draft", help="Create a stage1 draft template.")
    stage1_draft_parser.add_argument("--run-dir", required=True)
    stage1_draft_parser.add_argument("--slides", type=int, default=1)
    record_decision_parser = subparsers.add_parser("record-decision", help="Record a controller decision.")
    record_decision_parser.add_argument("--run-dir", required=True)
    record_decision_parser.add_argument("--decision-file", required=True)
    make_decision_parser = subparsers.add_parser("make-decision", help="Create and record a controller decision from thin inputs.")
    make_decision_parser.add_argument("--run-dir", required=True)
    make_decision_parser.add_argument("--type", required=True, dest="decision_type")
    make_decision_parser.add_argument("--notes", required=True)
    make_decision_parser.add_argument("--user-confirmed", action="store_true")
    make_decision_parser.add_argument("--controller-reviewed", dest="controller_reviewed", action="store_true", default=True)
    make_decision_parser.add_argument("--not-controller-reviewed", dest="controller_reviewed", action="store_false")
    make_decision_parser.add_argument("--confirmed-file", action="append", default=[])
    make_decision_parser.add_argument("--allowed-action", action="append")
    make_decision_parser.add_argument("--slide", type=int, action="append", default=[])
    make_decision_parser.add_argument("--image-generation-route", choices=["codex_image_gen", "openai_image_api"])

    execute_decision_parser = subparsers.add_parser("execute-decision", help="Execute one allowed decision action.")
    execute_decision_parser.add_argument("--run-dir", required=True)
    source = execute_decision_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--decision-id")
    source.add_argument("--decision-file")
    add_material_parser = subparsers.add_parser("add-material", help="Register a source material.")
    add_material_parser.add_argument("--run-dir", required=True)
    add_material_parser.add_argument("--type", choices=["file", "text", "url"], required=True)
    add_material_parser.add_argument("--source", required=True)
    add_material_parser.add_argument("--label")
    add_material_parser.add_argument("--material-kind")
    add_material_parser.add_argument("--mime-hint")
    add_material_parser.add_argument("--role-hint")
    add_material_parser.add_argument("--source-priority")
    add_material_parser.add_argument("--locator-hint")

    list_materials_parser = subparsers.add_parser("list-materials", help="List registered source materials.")
    list_materials_parser.add_argument("--run-dir", required=True)
    list_style_templates_parser = subparsers.add_parser("list-style-templates", help="List registered style templates.")
    list_style_templates_parser.add_argument("--include-deprecated", action="store_true")
    resolve_style_template_parser = subparsers.add_parser("resolve-style-template", help="Resolve a style template by id, name, or slash trigger.")
    resolve_style_template_parser.add_argument("--query", required=True)
    validate_style_templates_parser = subparsers.add_parser("validate-style-templates", help="Validate style template registry and markdown files.")
    validate_k12_profiles_parser = subparsers.add_parser("validate-k12-subject-profiles", help="Validate K12 lesson plan subject profile registry.")
    configure_image_api_parser = subparsers.add_parser("configure-image-api-key", help="Store the image API key in a local user secret file.")
    key_source = configure_image_api_parser.add_mutually_exclusive_group(required=True)
    key_source.add_argument("--api-key")
    key_source.add_argument("--stdin", action="store_true", help="Read the API key from standard input.")
    configure_image_api_parser.add_argument("--key-file")
    image_api_key_status_parser = subparsers.add_parser("image-api-key-status", help="Check image API key configuration without printing the key.")
    image_api_key_status_parser.add_argument("--key-file")
    cover_options_parser = subparsers.add_parser("dispatch-cover-options", help="Create four parallel cover style image generation packets.")
    cover_options_parser.add_argument("--run-dir", required=True)
    cover_options_parser.add_argument("--route", choices=["codex-image-gen", "codex_image_gen", "image-gen", "image_gen", "openai-image-api", "openai_image_api", "direct-api", "direct_api", "cangyuan", "cangyuan-api", "cangyuan_api", "grsai", "grsai-api", "grsai_api"], default=DEFAULT_IMAGE_GENERATION_ROUTE)
    promote_cover_parser = subparsers.add_parser("promote-selected-cover-option", help="Promote the approved cover option to a formal stage2 full_slide result.")
    promote_cover_parser.add_argument("--run-dir", required=True)
    promote_cover_parser.add_argument("--force", action="store_true")
    dispatch_image_api_parser = subparsers.add_parser("dispatch-image-api", help="Create parallel image API packets for the openai_image_api relay route.")
    dispatch_image_api_parser.add_argument("--run-dir", required=True)
    dispatch_image_api_parser.add_argument("--stage", choices=["stage2"], required=True)
    dispatch_generation_parser = subparsers.add_parser("dispatch-image-generation", help="Create parallel image generation packets for the selected route.")
    dispatch_generation_parser.add_argument("--run-dir", required=True)
    dispatch_generation_parser.add_argument("--stage", choices=["stage2"], required=True)
    dispatch_generation_parser.add_argument("--route", choices=["codex-image-gen", "codex_image_gen", "image-gen", "image_gen", "openai-image-api", "openai_image_api", "direct-api", "direct_api", "cangyuan", "cangyuan-api", "cangyuan_api", "grsai", "grsai-api", "grsai_api"], default=DEFAULT_IMAGE_GENERATION_ROUTE)
    trial_parser = subparsers.add_parser("dispatch-stage2-trial-first5", help="Create stage2B trial sample image generation packets.")
    trial_parser.add_argument("--run-dir", required=True)
    trial_parser.add_argument("--sample-count", type=int, default=5, help="试样总共5页，含已选封面，通常新增4张内页；仅用户明确指定时覆盖")
    trial_parser.add_argument("--extra-slide", type=int, action="append", default=[])
    trial_parser.add_argument("--extra-reason", action="append", default=[])
    trial_parser.add_argument("--route", choices=["codex-image-gen", "codex_image_gen", "image-gen", "image_gen", "openai-image-api", "openai_image_api", "direct-api", "direct_api", "cangyuan", "cangyuan-api", "cangyuan_api", "grsai", "grsai-api", "grsai_api"], default=DEFAULT_IMAGE_GENERATION_ROUTE)
    remaining_parser = subparsers.add_parser("dispatch-stage2-remaining", help="Create stage2 remaining full-slide image generation packets after trial approval.")
    remaining_parser.add_argument("--run-dir", required=True)
    remaining_parser.add_argument("--route", choices=["codex-image-gen", "codex_image_gen", "image-gen", "image_gen", "openai-image-api", "openai_image_api", "direct-api", "direct_api", "cangyuan", "cangyuan-api", "cangyuan_api", "grsai", "grsai-api", "grsai_api"], default=DEFAULT_IMAGE_GENERATION_ROUTE)
    promote_trial_parser = subparsers.add_parser("promote-stage2-trial-first5", help="Promote approved stage2 trial sample results to formal full_slide results.")
    promote_trial_parser.add_argument("--run-dir", required=True)
    promote_trial_parser.add_argument("--force", action="store_true")
    skip_trial_parser = subparsers.add_parser("authorize-stage2-trial-skip", help="记录用户明确授权跳过阶段2B试样。")
    skip_trial_parser.add_argument("--run-dir", required=True)
    skip_trial_parser.add_argument("--reason", required=True)
    migrate_trial_parser = subparsers.add_parser("migrate-legacy-trial-first5", help="显式把旧 前5页试样 图片迁移到阶段2 img 目录；遇冲突不覆盖。")
    migrate_trial_parser.add_argument("--run-dir", required=True)

    run_image_api_parser = subparsers.add_parser("run-image-api-batch", help="Run one image API batch with bounded concurrency.")
    run_image_api_parser.add_argument("--run-dir", required=True)
    source = run_image_api_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--batch")
    source.add_argument("--stage", choices=["cover-options", "stage2-trial-first5", "stage2-remaining", "stage2"])
    run_image_api_parser.add_argument("--base-url")
    run_image_api_parser.add_argument("--model")
    run_image_api_parser.add_argument("--size")
    run_image_api_parser.add_argument("--quality")
    run_image_api_parser.add_argument("--response-format")
    run_image_api_parser.add_argument("--key-file")
    run_image_api_parser.add_argument("--max-parallel", type=int, default=6)
    run_image_api_parser.add_argument("--timeout-seconds", type=int, default=500)
    run_image_api_parser.add_argument("--force", action="store_true")
    run_image_api_parser.add_argument("--dry-run", action="store_true")

    image_result_parser = subparsers.add_parser("record-image-result", help="Record a provider image result.")
    image_result_parser.add_argument("--run-dir", required=True)
    image_result_parser.add_argument("--packet", required=True)
    image_result_parser.add_argument("--image", required=True)
    image_result_parser.add_argument("--provider", required=True)
    image_result_parser.add_argument("--source", required=True)
    image_result_parser.add_argument("--generation-id", required=True)
    image_result_parser.add_argument("--tool-call-id")
    image_result_parser.add_argument("--image-gen-result-id")
    image_result_parser.add_argument("--api-call-id")
    image_result_parser.add_argument("--image-api-result-id")
    image_result_parser.add_argument("--request-id")
    image_result_parser.add_argument("--api-base-url")
    image_result_parser.add_argument("--api-endpoint")
    image_result_parser.add_argument("--model")
    image_result_parser.add_argument("--response-format")
    image_result_parser.add_argument("--api-evidence-path")
    image_result_parser.add_argument("--image-gen-evidence-path")
    image_result_parser.add_argument("--provider-image-url")
    image_result_parser.add_argument("--canonical-policy", choices=["preserve_api_raster", "normalize_at_stage2"])
    image_result_parser.add_argument("--canonical-size")
    image_result_parser.add_argument("--canonical-method", choices=["fit_center_crop", "contain_pad"], default="fit_center_crop")
    image_result_parser.add_argument("--dev-fixture", action="store_true")

    image_deck_parser = subparsers.add_parser("build-image-deck", help="Build an image-only PDF.")
    image_deck_parser.add_argument("--run-dir", required=True)
    image_deck_parser.add_argument("--allow-dev-fixture", action="store_true")
    stage2_visual_qa_parser = subparsers.add_parser("record-stage2-visual-qa", help="Record controller aesthetic QA for stage2 images.")
    stage2_visual_qa_parser.add_argument("--run-dir", required=True)
    stage2_visual_qa_parser.add_argument("--review", required=True)
    stage2_visual_qa_draft_parser = subparsers.add_parser("create-stage2-visual-qa-draft", help="Create a controller-review stage2 visual QA draft.")
    stage2_visual_qa_draft_parser.add_argument("--run-dir", required=True)
    stage2_visual_qa_draft_parser.add_argument("--scope", choices=["cover_options", "trial_first5", "full_image_deck"], default="full_image_deck")
    stage2_visual_qa_draft_parser.add_argument("--output")
    speaker_script_parser = subparsers.add_parser("build-speaker-script", help="Render stage3 speaker script Markdown, DOCX, and PDF.")
    speaker_script_parser.add_argument("--run-dir", required=True)
    speaker_script_parser.add_argument("--script-json", required=True)
    lesson_context_parser = subparsers.add_parser("build-lesson-plan-context", help="Build K12 stage3 lesson plan context from stage1 and source materials.")
    lesson_context_parser.add_argument("--run-dir", required=True)
    lesson_plan_parser = subparsers.add_parser("build-lesson-plan", help="Render K12 stage3 lesson plan Markdown, DOCX, and PDF.")
    lesson_plan_parser.add_argument("--run-dir", required=True)
    lesson_plan_parser.add_argument("--lesson-plan-json", required=True)
    lesson_plan_qa_parser = subparsers.add_parser("record-lesson-plan-qa", help="Record controller-reviewed K12 lesson plan QA.")
    lesson_plan_qa_parser.add_argument("--run-dir", required=True)
    lesson_plan_qa_parser.add_argument("--review", required=True)
    doctor_parser = subparsers.add_parser("doctor", help="Check project consistency.")
    doctor_parser.add_argument("--run-dir", required=True)
    v1_summary_parser = subparsers.add_parser("v1-summary", help="Create a read-only v1 project summary.")
    v1_summary_parser.add_argument("--run-dir", required=True)
    v1_summary_parser.add_argument("--output")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "init":
        output_root = args.output_root or default_output_root()
        run_dir = create_project(args.project_name, output_root)
        print(json.dumps({"status": "created", "run_dir": str(run_dir)}, ensure_ascii=False))
        return 0
    if args.command == "install-profile":
        print(json.dumps(install_profile(args.target), ensure_ascii=False))
        return 0
    if args.command == "inspect-installation":
        result = inspect_installation()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    if args.command == "migrate-decisions-layout":
        print(json.dumps(migrate_decisions_layout(args.run_dir, dry_run=args.dry_run), ensure_ascii=False))
        return 0
    if args.command == "migrate-image-style":
        text = Path(args.merged_file).read_text(encoding="utf-8") if args.merged_file else None
        print(json.dumps({"path": str(migrate_image_style_doc(args.run_dir, text))}, ensure_ascii=False))
        return 0
    if args.command == "accept-image-result":
        result = accept_image_result(args.run_dir, args.result, args.reason)
        print(json.dumps({"status": "accepted", "acceptance": result}, ensure_ascii=False))
        return 0
    if args.command == "reconcile-image-style":
        result = reconcile_image_style(
            args.run_dir,
            reason=args.reason,
            affected_slides=args.affected_slide,
            reusable_slides=args.reusable_slide,
        )
        print(json.dumps({"status": "reconciled", "change": result}, ensure_ascii=False))
        return 0
    if args.command == "record-image-prompt-plan":
        from .image_prompt_plan import record_image_prompt_plan
        plan = record_image_prompt_plan(args.run_dir, args.slide_index, read_json(args.plan_file), option_id=args.option_id)
        print(json.dumps({"status": "recorded", "image_prompt_plan": plan}, ensure_ascii=False))
        return 0
    if args.command == "image-prompt-sources":
        from .image_prompt_plan import load_prompt_sources
        print(json.dumps(load_prompt_sources(args.run_dir, args.slide_index, option_id=args.option_id), ensure_ascii=False))
        return 0
    if args.command == "prepare-image-request":
        path = Path(args.packet)
        if not path.is_absolute():
            path = Path(args.run_dir) / path
        snapshot_path, packet = prepare_image_request(args.run_dir, path, read_json(path))
        print(json.dumps({"packet_path": str(snapshot_path), "prompt": packet["prompt"]}, ensure_ascii=False))
        return 0
    if args.command == "refresh-image-prompts":
        path = export_prompt_document(args.run_dir, args.output_dir) if args.output_dir else refresh_prompt_delivery(args.run_dir)
        print(json.dumps({"document": str(path)}, ensure_ascii=False))
        return 0
    if args.command == "status":
        print(json.dumps(read_state(args.run_dir), ensure_ascii=False))
        return 0
    if args.command == "resume-brief":
        brief = build_resume_brief(args.run_dir, persist=args.persist)
        if args.format == "markdown":
            print(render_resume_brief_markdown(brief))
        else:
            print(json.dumps(brief, ensure_ascii=False))
        return 0
    if args.command == "next-action":
        print(json.dumps(build_next_action(args.run_dir, persist=args.persist), ensure_ascii=False))
        return 0
    if args.command == "drift-check":
        result = run_drift_check(args.run_dir, action=args.action, persist=args.persist)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    if args.command == "create-work-packet":
        packet = create_work_packet(
            args.run_dir,
            stage=args.stage,
            action=args.action,
            slide_indices=args.slide,
            allowed_commands=args.allowed_command,
            input_artifacts=args.input_artifact,
            expected_outputs=args.expected_output,
            stop_conditions=args.stop_condition,
            requires_user_confirmation=args.requires_user_confirmation,
            confirmation_decision_type=args.confirmation_decision_type,
        )
        print(json.dumps({"status": "work_packet_created", "packet": packet}, ensure_ascii=False))
        return 0
    if args.command == "close-work-packet":
        packet = close_work_packet(args.run_dir, args.packet, status=args.status, summary=args.summary)
        print(json.dumps({"status": "work_packet_closed", "packet": packet}, ensure_ascii=False))
        return 0
    if args.command == "sync-stage-docs":
        sync_stage_docs(args.run_dir)
        print(json.dumps({"status": "synced", "run_dir": args.run_dir}, ensure_ascii=False))
        return 0
    if args.command == "organize-deliverables":
        print(json.dumps(organize_deliverables(args.run_dir), ensure_ascii=False))
        return 0
    if args.command == "create-canva-task-brief":
        result = create_canva_task_brief(
            args.run_dir,
            task_id=args.task_id,
            trigger=args.trigger,
            provider=args.provider,
            host_profile=args.host_profile,
            executor=args.executor,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "record-canva-task-event":
        try:
            event = json.loads(args.event_json)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"--event-json must be valid JSON: {exc.msg}") from exc
        if not isinstance(event, dict):
            raise ValidationError("--event-json must decode to an object")
        result = record_canva_task_event(args.run_dir, args.task_id, event=event, status=args.status)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "record-canva-task-export":
        try:
            export = json.loads(args.export_json)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"--export-json must be valid JSON: {exc.msg}") from exc
        if not isinstance(export, dict):
            raise ValidationError("--export-json must decode to an object")
        result = record_canva_task_export(args.run_dir, args.task_id, export=export)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "add-material":
        record = add_material(
            args.run_dir,
            material_type=args.type,
            source=args.source,
            label=args.label,
            material_kind=args.material_kind,
            mime_hint=args.mime_hint,
            role_hint=args.role_hint,
            source_priority=args.source_priority,
            locator_hint=args.locator_hint,
        )
        print(json.dumps({"status": "added", "material": record}, ensure_ascii=False))
        return 0
    if args.command == "list-materials":
        print(json.dumps({"materials": list_materials(args.run_dir)}, ensure_ascii=False))
        return 0
    if args.command == "list-style-templates":
        templates = [
            style_template_summary(template)
            for template in list_style_templates(include_deprecated=args.include_deprecated)
        ]
        print(json.dumps({"status": "ok", "templates": templates}, ensure_ascii=False))
        return 0
    if args.command == "resolve-style-template":
        template = style_template_summary(resolve_style_template(args.query))
        print(json.dumps({"status": "resolved", "template": template}, ensure_ascii=False))
        return 0
    if args.command == "validate-style-templates":
        report = validate_style_templates_report()
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["ok"] else 1
    if args.command == "validate-k12-subject-profiles":
        report = subject_profile_registry_report()
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["ok"] else 1
    if args.command == "configure-image-api-key":
        api_key = sys.stdin.read().strip() if args.stdin else args.api_key
        path = configure_image_api_key(api_key or "", key_file=args.key_file)
        print(json.dumps({"status": "configured", "key_file": str(path)}, ensure_ascii=False))
        return 0
    if args.command == "image-api-key-status":
        print(json.dumps(image_api_key_status(key_file=args.key_file), ensure_ascii=False))
        return 0
    if args.command == "dispatch-cover-options":
        packets = dispatch_cover_option_packets(args.run_dir, route=args.route)
        print(json.dumps({"status": "cover_option_packets_created", "packets": [str(path) for path in packets]}, ensure_ascii=False))
        return 0
    if args.command == "promote-selected-cover-option":
        result = promote_selected_cover_option(args.run_dir, force=args.force)
        print(json.dumps({"status": "selected_cover_option_promoted", "result": str(result)}, ensure_ascii=False))
        return 0
    if args.command == "dispatch-image-api":
        packets = dispatch_image_api_packets(args.run_dir, args.stage)
        print(json.dumps({"status": "packets_created", "packets": [str(path) for path in packets]}, ensure_ascii=False))
        return 0
    if args.command == "dispatch-image-generation":
        packets = dispatch_image_generation_packets(args.run_dir, args.stage, route=args.route)
        print(json.dumps({"status": "packets_created", "packets": [str(path) for path in packets]}, ensure_ascii=False))
        return 0
    if args.command == "dispatch-stage2-trial-first5":
        extra_complex_slides = _extra_complex_slides(args.extra_slide, args.extra_reason)
        packets = dispatch_stage2_trial_first5_packets(
            args.run_dir,
            extra_complex_slides=extra_complex_slides,
            sample_count=args.sample_count,
            route=args.route,
        )
        print(json.dumps({"status": "stage2_trial_first5_packets_created", "packets": [str(path) for path in packets]}, ensure_ascii=False))
        return 0
    if args.command == "promote-stage2-trial-first5":
        promoted = promote_stage2_trial_first5(args.run_dir, force=args.force)
        print(json.dumps({"status": "stage2_trial_first5_promoted", "results": [str(path) for path in promoted]}, ensure_ascii=False))
        return 0
    if args.command == "authorize-stage2-trial-skip":
        result = authorize_stage2_trial_skip(args.run_dir, reason=args.reason)
        print(json.dumps({"status": "stage2_trial_skip_authorized", "skip": result}, ensure_ascii=False))
        return 0
    if args.command == "migrate-legacy-trial-first5":
        result = migrate_legacy_trial_first5_images(args.run_dir)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "dispatch-stage2-remaining":
        packets = dispatch_stage2_remaining_packets(args.run_dir, route=args.route)
        print(json.dumps({"status": "stage2_remaining_packets_created", "packets": [str(path) for path in packets]}, ensure_ascii=False))
        return 0
    if args.command == "run-image-api-batch":
        config = load_image_api_config(
            base_url=args.base_url,
            model=args.model,
            size=args.size,
            quality=args.quality,
            response_format=args.response_format,
            max_parallel=args.max_parallel,
            timeout_seconds=args.timeout_seconds,
            key_file=args.key_file,
        )
        batch_path = args.batch or default_batch_path_for_stage(args.run_dir, args.stage)
        report = run_image_api_batch(args.run_dir, batch_path, config=config, force=args.force, dry_run=args.dry_run)
        print(json.dumps({"status": report["status"], "report": report}, ensure_ascii=False))
        return 0 if report["status"] in {"completed", "dry_run"} else 1
    if args.command == "record-image-result":
        result = record_image_result(
            args.run_dir,
            args.packet,
            args.image,
            args.provider,
            args.source,
            args.generation_id,
            tool_call_id=args.tool_call_id,
            image_gen_result_id=args.image_gen_result_id,
            api_call_id=args.api_call_id,
            image_api_result_id=args.image_api_result_id,
            request_id=args.request_id,
            api_base_url=args.api_base_url,
            api_endpoint=args.api_endpoint,
            model=args.model,
            response_format=args.response_format,
            api_evidence_path=args.api_evidence_path,
            image_gen_evidence_path=args.image_gen_evidence_path,
            provider_image_url=args.provider_image_url,
            canonical_policy=args.canonical_policy,
            canonical_size=args.canonical_size,
            canonical_method=args.canonical_method,
            dev_fixture=args.dev_fixture,
        )
        print(json.dumps({"status": "image_result_recorded", "result": result}, ensure_ascii=False))
        return 0
    if args.command == "build-image-deck":
        deck = build_image_deck(args.run_dir, allow_dev_fixture=args.allow_dev_fixture)
        print(json.dumps({"status": "image_deck_built", "deck_path": str(deck)}, ensure_ascii=False))
        return 0
    if args.command == "record-layout-safety-contract":
        contract_path = record_layout_safety_contract(args.run_dir, args.contract)
        print(json.dumps({"status": "layout_safety_contract_recorded", "contract_path": str(contract_path)}, ensure_ascii=False))
        return 0
    if args.command == "record-stage2-visual-qa":
        review_path = record_stage2_aesthetic_review(args.run_dir, args.review)
        print(json.dumps({"status": "stage2_visual_qa_recorded", "review_path": str(review_path)}, ensure_ascii=False))
        return 0
    if args.command == "create-stage2-visual-qa-draft":
        review_path = create_stage2_visual_qa_draft(args.run_dir, scope=args.scope, output_file=args.output)
        print(json.dumps({"status": "stage2_visual_qa_draft_created", "review_path": str(review_path)}, ensure_ascii=False))
        return 0
    if args.command == "build-speaker-script":
        manifest = build_speaker_script(args.run_dir, args.script_json)
        print(json.dumps({"status": "speaker_script_built", "manifest": manifest}, ensure_ascii=False))
        return 0
    if args.command == "build-lesson-plan-context":
        context = build_lesson_plan_context(args.run_dir)
        print(
            json.dumps(
                {
                    "status": "lesson_plan_context_built",
                    "path": str(lesson_plan_context_path(args.run_dir)),
                    "context": context,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "build-lesson-plan":
        manifest = build_lesson_plan(args.run_dir, args.lesson_plan_json)
        print(json.dumps({"status": "lesson_plan_built", "manifest": manifest}, ensure_ascii=False))
        return 0
    if args.command == "record-lesson-plan-qa":
        review_path = record_lesson_plan_qa(args.run_dir, args.review)
        print(json.dumps({"status": "lesson_plan_qa_recorded", "review_path": str(review_path)}, ensure_ascii=False))
        return 0
    if args.command == "v1-summary":
        summary = summarize_v1_project(args.run_dir)
        if args.output:
            output = write_v1_summary(summary, args.output)
            print(json.dumps({"status": "v1_summary_written", "summary": summary, "output": str(output)}, ensure_ascii=False))
        else:
            print(render_v1_summary_markdown(summary))
        return 0
    if args.command == "create-stage1-draft":
        path = create_stage1_draft(args.run_dir, args.slides)
        print(json.dumps({"status": "draft_created", "slides_path": str(path)}, ensure_ascii=False))
        return 0
    if args.command == "validate-stage1":
        report = validate_stage1_project(args.run_dir)
        print(json.dumps(report, ensure_ascii=False))
        return 0 if report["ok"] else 1
    if args.command == "sync-stage1-derivatives":
        print(json.dumps(sync_stage1_derivatives(args.run_dir), ensure_ascii=False))
        return 0
    if args.command == "record-decision":
        target = record_decision(args.run_dir, read_json(args.decision_file))
        print(json.dumps({"status": "recorded", "path": str(target)}, ensure_ascii=False))
        return 0
    if args.command == "make-decision":
        result = make_decision(
            args.run_dir,
            decision_type=args.decision_type,
            notes=args.notes,
            user_confirmed=args.user_confirmed,
            controller_reviewed=args.controller_reviewed,
            confirmed_files=args.confirmed_file,
            allowed_actions=args.allowed_action,
            slide_indices=args.slide,
            image_generation_route=args.image_generation_route,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "execute-decision":
        decision = load_decision(args.run_dir, args.decision_id, args.decision_file)
        state = execute_decision(args.run_dir, decision)
        print(json.dumps({"status": "executed", "state": state}, ensure_ascii=False))
        return 0
    if args.command == "doctor":
        result = check_project(args.run_dir)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    parser.error(f"command is not implemented yet: {args.command}")
    return 2


def _extra_complex_slides(extra_slide: list[int], extra_reason: list[str]) -> list[dict[str, object]]:
    if not extra_slide:
        return []
    if len(extra_slide) != len(extra_reason):
        raise ValidationError("--extra-slide and --extra-reason must be provided in pairs")
    return [
        {
            "slide_index": slide_index,
            "reason": reason,
        }
        for slide_index, reason in zip(extra_slide, extra_reason)
    ]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValidationError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": exc.__class__.__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
