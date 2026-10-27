from __future__ import annotations

import hashlib
import json
import re

from ..validation import ValidationError
from . import PROFILE

SCENES = {"general", "k12", "pitch", "healthcare", "competition", "defense"}
ROLES = {"question", "given", "options", "answer", "answer_marker", "explanation", "content", "decoration", "safety"}


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def keys(value, allowed, required):
    require(isinstance(value, dict), "Expected an object")
    require(set(required) <= value.keys() and value.keys() <= set(allowed), "Missing or unsupported plan fields")


def validate_plan(plan, inventory=None):
    """Validate semantics without inferring answers or modifying the plan."""
    keys(plan, {"schema_version", "source", "scene", "profile", "existing_timing_policy", "pages"},
         {"schema_version", "source", "scene", "profile", "existing_timing_policy", "pages"})
    require(plan["schema_version"] == "1.0" and plan["profile"] == PROFILE, "Unsupported animation plan/profile")
    require(isinstance(plan["scene"], str) and plan["scene"] in SCENES, "Unsupported scene")
    require(isinstance(plan["existing_timing_policy"], str) and plan["existing_timing_policy"] in {"reject", "replace_selected"}, "Unsupported timing policy")
    keys(plan["source"], {"path", "sha256"}, {"path", "sha256"})
    require(isinstance(plan["source"]["path"], str) and bool(plan["source"]["path"]), "Missing source path")
    require(isinstance(plan["source"]["sha256"], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", plan["source"]["sha256"]), "Expected sha256: hash")
    if inventory is not None:
        require(plan["source"] == inventory["source"], "Source changed; inspect again and rebind plan")
    require(isinstance(plan["pages"], list) and plan["pages"], "Select at least one page")
    seen_pages = set()
    for page in plan["pages"]:
        keys(page, {"slide_index", "part", "units", "needs_layering", "visual_checked"}, {"slide_index", "part", "units"})
        index = page["slide_index"]
        require(type(index) is int and index > 0 and index not in seen_pages, "Duplicate or invalid page")
        seen_pages.add(index)
        require(isinstance(page["part"], str) and bool(page["part"]), "Missing slide part")
        for key in ("needs_layering", "visual_checked"):
            require(key not in page or type(page[key]) is bool, f"{key} must be boolean")
        require(not page.get("needs_layering"), f"Page {index}: needs_layering; content cannot be split by animation")
        require(isinstance(page["units"], list), "Expected units list")
        ids, targets, clicks, questions, answers = set(), [], set(), {}, {}
        for unit in page["units"]:
            keys(unit, {"id", "role", "targets", "click", "question_id"}, {"id", "role", "targets", "click"})
            require(isinstance(unit["id"], str) and unit["id"] and unit["id"] not in ids, "Duplicate/empty unit id")
            ids.add(unit["id"])
            require(isinstance(unit["role"], str) and unit["role"] in ROLES, "Unsupported role")
            click = unit["click"]
            require(type(click) is int and click >= 0, "Only manual integer click steps are supported")
            clicks.add(click)
            require(isinstance(unit["targets"], list) and unit["targets"] and
                    all(type(t) is int and t > 0 for t in unit["targets"]), "Invalid targets")
            targets.extend(unit["targets"])
            role, qid = unit["role"], unit.get("question_id")
            if qid is not None:
                require(isinstance(qid, str) and bool(qid), "Invalid question_id")
            if role in {"question", "given", "options", "answer", "answer_marker", "explanation"}:
                require(qid is not None, "Question/answer units require question_id")
            if role == "question":
                require(click == 0, "Questions must be initially visible")
                questions[qid] = click
            if role in {"given", "options", "safety", "decoration"}:
                require(click == 0, f"{role} must remain initially visible")
            if role == "answer":
                require(click > 0, "Answer requires a new manual click")
                answers.setdefault(qid, set()).add(click)
        require(len(targets) == len(set(targets)), "Duplicate target / mixed question-answer target: needs_layering")
        dynamic = sorted(clicks - {0})
        require(dynamic == list(range(1, len(dynamic) + 1)), "Click steps must be contiguous")
        for qid, values in answers.items():
            require(qid in questions and len(values) == 1, "Answer must bind one question and one synchronized step")
        for unit in page["units"]:
            role, qid = unit["role"], unit.get("question_id")
            if role in {"given", "options", "answer", "answer_marker", "explanation"}:
                require(qid in questions, "Unknown question_id")
            if role in {"answer_marker", "explanation"}:
                require(qid in answers, "Marker/explanation requires its answer")
                answer_click = next(iter(answers[qid]))
                require(unit["click"] == answer_click if role == "answer_marker" else unit["click"] > answer_click,
                        "Marker must reveal with answer; explanation requires a later manual click")
        if inventory is not None:
            rows = [p for p in inventory["pages"] if p["slide_index"] == index]
            require(len(rows) == 1 and rows[0]["part"] == page["part"], "Slide order/part mismatch")
            row = rows[0]
            require(set(targets) == {o["id"] for o in row["objects"]}, "Missing or foreign targets; classify every top-level object")
            if questions and row["has_visual_content"]:
                require(page.get("visual_checked") is True, "Question page contains images/graphics: inspect existing preview for baked-in answers")
            require(not row["auto_advance"], "Automatic slide advance conflicts with manual reveal; adjust separately")
            require(not row["has_timing"] or plan["existing_timing_policy"] == "replace_selected", "Existing timing: explicitly select replace_selected within authorized pages")
    return plan


def plan_signature(plan):
    return "sha256:" + hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def steps(page):
    """Flatten complete units by click, keeping plan order within a click."""
    return [[t for u in page["units"] if u["click"] == click for t in u["targets"]]
            for click in sorted({u["click"] for u in page["units"]} - {0})]
