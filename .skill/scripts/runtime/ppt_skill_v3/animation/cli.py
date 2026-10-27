"""Animation CLI kept independent of optional dependencies in other PPT stages."""
from __future__ import annotations

import argparse
import json
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from ..validation import ValidationError
from .task import inspect_task, apply_task, verify_task


def add_parser(subparsers):
    parser = subparsers.add_parser("animation", help="原位添加动画，保持全部内容与主阶段状态不变。")
    commands = parser.add_subparsers(dest="animation_command", required=True)
    for operation in ("inspect", "apply", "verify"):
        command = commands.add_parser(operation)
        command.add_argument("--run-dir", required=True)
        command.add_argument("--task-id", required=True)
        if operation == "inspect":
            command.add_argument("--source")
            command.add_argument("--active-ppt")
            command.add_argument("--project-ppt")
            command.add_argument("--page", type=int)
        elif operation == "apply":
            command.add_argument("--plan-file", required=True)


def dispatch(args):
    try:
        if args.animation_command == "inspect":
            result = inspect_task(args.run_dir, args.task_id, source=args.source,
                                  active_ppt=args.active_ppt, project_ppt=args.project_ppt, page=args.page)
        elif args.animation_command == "apply":
            result = apply_task(args.run_dir, args.task_id, args.plan_file)
        else:
            result = verify_task(args.run_dir, args.task_id)
    except (ValidationError, ValueError, OSError, KeyError, BadZipFile, ParseError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pptctl")
    commands = parser.add_subparsers(dest="command", required=True)
    add_parser(commands)
    return dispatch(parser.parse_args(argv))
