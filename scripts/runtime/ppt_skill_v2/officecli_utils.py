from __future__ import annotations

import json
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from .json_io import write_json
from .time_utils import now_iso
from .validation import ValidationError


SLIDE_WIDTH_PT = 960.0
SLIDE_HEIGHT_PT = 540.0


def require_officecli() -> str:
    executable = shutil.which("officecli")
    if not executable:
        raise ValidationError("OfficeCLI is required for stage3 editable PPT builder")
    return executable


@lru_cache(maxsize=1)
def officecli_version() -> str:
    result = _run_raw(["officecli", "--version"], check=True)
    version = result.stdout.strip()
    if not version:
        raise ValidationError("OfficeCLI version output is empty")
    return version


def run_officecli(args: list[str], *, check: bool = True) -> dict[str, Any]:
    require_officecli()
    result = _run_raw(["officecli", *args], check=False)
    payload = _parse_json_output(result.stdout)
    if check and result.returncode != 0:
        raise ValidationError(_officecli_error_message(args, result, payload))
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "json": payload,
    }


def close_officecli_document(path: str | Path) -> dict[str, Any] | None:
    try:
        return run_officecli(["close", str(path), "--json"], check=False)
    except ValidationError:
        return None


def collect_officecli_slides_readback(
    pptx_file: str | Path,
    slide_indices: list[int],
    *,
    output_file: str | Path | None = None,
) -> dict[str, Any]:
    pptx_path = Path(pptx_file)
    slides = []
    for slide_index in slide_indices:
        result = run_officecli(["get", str(pptx_path), f"/slide[{slide_index}]", "--depth", "3", "--json"])
        raw = result["json"]
        slide_node = _first_result_node(raw)
        slides.append(
            {
                "slide_index": slide_index,
                "path": slide_node.get("path") if isinstance(slide_node, dict) else f"/slide[{slide_index}]",
                "format": slide_node.get("format", {}) if isinstance(slide_node, dict) else {},
                "children": slide_node.get("children", []) if isinstance(slide_node, dict) else [],
                "raw": raw,
            }
        )
    readback = {
        "schema_version": "1.0",
        "provider": "officecli",
        "officecli_version": officecli_version(),
        "pptx": str(pptx_path),
        "generated_at": now_iso(),
        "slides": slides,
    }
    if output_file is not None:
        write_json(output_file, readback)
    return readback


def iter_officecli_nodes(nodes: Any) -> list[dict[str, Any]]:
    if not isinstance(nodes, list):
        return []
    flattened: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        flattened.append(node)
        flattened.extend(iter_officecli_nodes(node.get("children")))
    return flattened


def parse_officecli_length_pt(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)([a-zA-Z]*)", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2).lower() or "pt"
    if unit == "pt":
        return number
    if unit == "in":
        return number * 72.0
    if unit == "cm":
        return number * 72.0 / 2.54
    if unit == "mm":
        return number * 72.0 / 25.4
    if unit == "px":
        return number * 72.0 / 96.0
    if unit == "emu":
        return number / 12700.0
    return None


def officecli_relative_box(format_data: dict[str, Any]) -> dict[str, float] | None:
    x = parse_officecli_length_pt(format_data.get("x"))
    y = parse_officecli_length_pt(format_data.get("y"))
    width = parse_officecli_length_pt(format_data.get("width"))
    height = parse_officecli_length_pt(format_data.get("height"))
    if x is None or y is None or width is None or height is None:
        return None
    return {
        "x": round(x / SLIDE_WIDTH_PT, 6),
        "y": round(y / SLIDE_HEIGHT_PT, 6),
        "w": round(width / SLIDE_WIDTH_PT, 6),
        "h": round(height / SLIDE_HEIGHT_PT, 6),
    }


def pt(value: float | int) -> str:
    return f"{float(value):.4f}pt"


def relative_box_to_pt(relative_box: dict[str, Any]) -> dict[str, str]:
    return {
        "x": pt(float(relative_box["x"]) * SLIDE_WIDTH_PT),
        "y": pt(float(relative_box["y"]) * SLIDE_HEIGHT_PT),
        "width": pt(float(relative_box["w"]) * SLIDE_WIDTH_PT),
        "height": pt(float(relative_box["h"]) * SLIDE_HEIGHT_PT),
    }


def file_sha256(path: str | Path) -> str:
    import hashlib

    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _run_raw(command: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if check and result.returncode != 0:
        raise ValidationError(_officecli_error_message(command[1:], result, _parse_json_output(result.stdout)))
    return result


def _parse_json_output(stdout: str) -> Any | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _first_result_node(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list) and results and isinstance(results[0], dict):
                return results[0]
    return {}


def _officecli_error_message(
    args: list[str],
    result: subprocess.CompletedProcess[str],
    payload: Any | None,
) -> str:
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error")
        if isinstance(message, str) and message.strip():
            return f"OfficeCLI command failed ({' '.join(args)}): {message}"
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    detail = stderr or stdout or f"exit code {result.returncode}"
    return f"OfficeCLI command failed ({' '.join(args)}): {detail}"
