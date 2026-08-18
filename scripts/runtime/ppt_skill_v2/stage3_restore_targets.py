from __future__ import annotations

import hashlib
import json
from typing import Any


RESTORE_TARGET_ACTIONS = {
    "remove_and_restore",
    "preserve_in_background",
    "remove_without_restore",
}


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def restore_targets_hash(restore_targets: list[dict[str, Any]]) -> str:
    return stable_json_hash(restore_targets)


def restore_targets_bundle_hash(slides: list[dict[str, Any]]) -> str:
    payload = [
        {
            "slide_index": slide["slide_index"],
            "restore_targets": slide["restore_targets"],
        }
        for slide in sorted(slides, key=lambda item: item["slide_index"])
    ]
    return stable_json_hash(payload)


def build_restore_targets(content_slide: dict[str, Any], prompt_brief: dict[str, Any]) -> list[dict[str, Any]]:
    explicit_targets = prompt_brief.get("restore_targets") or content_slide.get("restore_targets")
    if isinstance(explicit_targets, list) and explicit_targets:
        return [dict(target) for target in explicit_targets if isinstance(target, dict)]

    visible_text = prompt_brief.get("final_visible_text") or content_slide.get("final_visible_text") or [content_slide["title"]]
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    slide_index = content_slide["slide_index"]
    for index, raw_text in enumerate(visible_text, start=1):
        if not isinstance(raw_text, str):
            continue
        text = raw_text.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        source_field = f"slides[{slide_index - 1}].final_visible_text[{index - 1}]"
        source_key = "slide_prompt_briefs_path" if prompt_brief.get("final_visible_text") else "content_json_path"
        semantic_role = "slide_title" if index == 1 and text == content_slide.get("title") else "body_text"
        targets.append(
            {
                "target_id": f"s{slide_index:03d}_restore_{index:03d}",
                "action": "remove_and_restore",
                "text": text,
                "semantic_role": semantic_role,
                "source": {
                    source_key: "_state/阶段1/slide_prompt_briefs.json"
                    if source_key == "slide_prompt_briefs_path"
                    else "_state/阶段1/content.json",
                    "source_field": source_field,
                },
                "expected_restore_as": "foreground_text",
                "notes": "fallback_coarse_target",
            }
        )
    return targets
