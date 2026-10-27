from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ..json_io import read_json
from ..time_utils import now_iso
from . import PROFILE
from .compiler import apply_in_place
from .plan import plan_signature, require, validate_plan
from .reader import compact_inventory, digest, inspect_source, resolve_source
from .verify import verify_file

TASKS_REL = Path("_state/工具任务/animation")


def guard_run_dir(run_dir):
    root = Path(run_dir).expanduser().resolve()
    skill = Path(__file__).resolve().parents[4]
    require(root != skill.parent and root != skill and skill not in root.parents,
            "RUN must be a PPT project, not the workspace or Skill directory")
    require(not (root / ".skill").is_dir() and not (root / "SKILL.md").exists(), "RUN cannot be workspace/Skill root")
    return root


def task_dir(run_dir, task_id):
    root = guard_run_dir(run_dir)
    require(isinstance(task_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", task_id), "Invalid task-id")
    folder = root / TASKS_REL / task_id
    require(folder.resolve().is_relative_to(root), "Task path escapes project (including symlinks)")
    return folder


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _state(root):
    path = root / "_state/project_state.json"
    return read_json(path) if path.is_file() else {}


def _project_source(root):
    state = _state(root)
    locked = state.get("stage3_locked_presentation_source") or {}
    choices = [locked.get("source_path"), (state.get("user_artifacts") or {}).get("stage3_locked_presentation_source"),
               (state.get("user_artifacts") or {}).get("stage2_image_deck")]
    for value in choices:
        if isinstance(value, str) and Path(value).suffix.lower() == ".pptx":
            return str(Path(value) if Path(value).is_absolute() else root / value)
    return None


def _summary(folder, task):
    return {k: task[k] for k in ("task_id", "status", "source", "before_sha256", "after_sha256", "error") if k in task} | {"path": str(folder)}


def inspect_task(run_dir, task_id, *, source=None, active_ppt=None, project_ppt=None, page=None):
    folder = task_dir(run_dir, task_id)
    root = guard_run_dir(run_dir)
    directories = [root]
    if root.is_dir():
        directories += [d for d in root.iterdir() if d.is_dir() and d.name.startswith("阶段")]
    selection = resolve_source(explicit=source, active=active_ppt, project=project_ppt or _project_source(root), directories=directories)
    if selection["status"] != "resolved":
        return selection
    selected = Path(selection["path"])
    skill = Path(__file__).resolve().parents[4]
    require(not selected.is_relative_to(skill) and not selected.is_relative_to((root / TASKS_REL).resolve()), "Source cannot be internal Skill/task data")
    if (folder / "task.json").exists():
        task = read_json(folder / "task.json")
        require(task["source"] == str(selected), "task-id already belongs to another source; choose a new ID")
        accepted = {task["before_sha256"], task.get("after_sha256")}
        require(digest(selected.read_bytes()) in accepted, "Source changed; inspect under a new task-id")
        inv = read_json(folder / "inventory.json")
    else:
        require(not folder.exists(), "task-id already exists without a valid record; use a new ID")
        inv = inspect_source(selected)
        task = {"schema_version": "1.0", "task_id": task_id, "status": "inspected", "source": str(selected),
                "resolution_basis": selection["basis"], "before_sha256": inv["source"]["sha256"], "profile": PROFILE,
                "created_at": now_iso()}
        _write(folder / "inventory.json", inv)
        _write(folder / "task.json", task)
    result = _summary(folder, task) | {"inventory_path": str(folder / "inventory.json"), "inventory": compact_inventory(inv)}
    if page is not None:
        matches = [p for p in inv["pages"] if p["slide_index"] == page]
        require(bool(matches), "Unknown page")
        result["page_detail"] = matches[0]
    return result


def _locked_conflict(root, source):
    locked = _state(root).get("stage3_locked_presentation_source") or {}
    value = locked.get("source_path")
    if value and locked.get("source_sha256"):
        path = Path(value) if Path(value).is_absolute() else root / value
        require(path.resolve() != source, "Locked reference conflict: stage3_locked_presentation_source.source_sha256 binds this PPTX; animation would change its hash. No source/state was changed; resolve this specific source binding separately.")


def apply_task(run_dir, task_id, plan_file):
    folder = task_dir(run_dir, task_id)
    require((folder / "task.json").is_file(), "Run animation inspect first")
    task = read_json(folder / "task.json")
    try:
        plan = read_json(plan_file)
        validate_plan(plan)
        signature = plan_signature(plan)
        source = Path(task["source"])
        current_hash = digest(source.read_bytes())
        if current_hash == task.get("after_sha256") and signature == task.get("plan_signature"):
            report = verify_file(source, read_json(folder / "baseline.json"), read_json(folder / "plan.json"))
            task.update(status="applied", error=None)
            _write(folder / "verification.json", report)
            _write(folder / "task.json", task)
            return _summary(folder, task) | {"status": "already_applied", "verification": report}
        require(current_hash == task["before_sha256"], "Source changed since inspect; create a new task")
        require(plan["source"] == read_json(folder / "inventory.json")["source"], "Plan is not bound to inspected source")
        _locked_conflict(guard_run_dir(run_dir), source)
        def prepare(result):
            _write(folder / "baseline.json", result["baseline"])
            _write(folder / "old_timing.json", result["old_timing"])
            _write(folder / "plan.json", plan)
            task.update(status="prepared", plan_signature=signature, after_sha256=result["after_sha256"], error=None)
            _write(folder / "task.json", task)
        result = apply_in_place(source, plan, prepare_commit=prepare)
        task.update(status="applied", after_sha256=result["after_sha256"], plan_signature=signature,
                    completed_at=now_iso(), error=None)
        _write(folder / "verification.json", result["verification"])
        _write(folder / "task.json", task)
        return _summary(folder, task) | {"verification": result["verification"]}
    except Exception as exc:
        task.update(status="failed", error=str(exc))
        _write(folder / "task.json", task)
        raise


def verify_task(run_dir, task_id):
    folder = task_dir(run_dir, task_id)
    task = read_json(folder / "task.json")
    require(task.get("after_sha256") and digest(Path(task["source"]).read_bytes()) == task["after_sha256"], "Current file does not match applied revision")
    report = verify_file(task["source"], read_json(folder / "baseline.json"), read_json(folder / "plan.json"))
    return _summary(folder, task) | {"verification": report}


def task_summaries(run_dir):
    root = Path(run_dir) / TASKS_REL
    result = []
    for path in sorted(root.glob("*/task.json")):
        try:
            task = read_json(path)
            result.append(_summary(path.parent, task))
        except (ValueError, OSError, KeyError):
            result.append({"task_id": path.parent.name, "status": "unreadable", "path": str(path.parent)})
    return result
