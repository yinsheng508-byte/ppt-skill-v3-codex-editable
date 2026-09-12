from __future__ import annotations

import base64
import binascii
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import ssl
import time
from typing import Any
import urllib.error
import urllib.request
import uuid

from .image_api_defaults import (
    DEFAULT_IMAGE_API_BASE_URL,
    DEFAULT_IMAGE_API_BASE_URL_ENV,
    DEFAULT_IMAGE_API_EDITS_ENDPOINT,
    DEFAULT_IMAGE_API_GENERATION_ENDPOINT,
    DEFAULT_IMAGE_API_KEY_ENV,
    DEFAULT_IMAGE_API_KEY_FILE,
    DEFAULT_IMAGE_API_KEY_FILE_ENV,
    DEFAULT_IMAGE_API_MODEL,
    DEFAULT_IMAGE_API_MODEL_ENV,
    DEFAULT_IMAGE_API_OUTPUT_FORMAT,
    DEFAULT_IMAGE_API_PARALLELISM,
    DEFAULT_IMAGE_API_QUALITY,
    DEFAULT_IMAGE_API_QUALITY_ENV,
    DEFAULT_IMAGE_API_RESPONSE_FORMAT,
    DEFAULT_IMAGE_API_RESPONSE_FORMAT_ENV,
    DEFAULT_IMAGE_API_SIZE,
    DEFAULT_IMAGE_API_SIZE_ENV,
    DEFAULT_IMAGE_API_TIMEOUT_SECONDS,
    IMAGE_API_PROVIDER,
    LEGACY_GRSAI_DRAW_COMPLETIONS_ENDPOINT,
    SUPPORTED_IMAGE_API_ENDPOINTS,
)
from .image_results import record_image_result
from .image_routes import IMAGE_ROUTE_OPENAI_IMAGE_API, normalize_image_generation_route
from .json_io import read_json, write_json
from .image_prompt_docs import require_current_image_style, record_prompt_document, prepare_image_request
from .time_utils import now_iso
from .validation import ValidationError


GRSAI_DRAW_COMPLETIONS_ENDPOINT = LEGACY_GRSAI_DRAW_COMPLETIONS_ENDPOINT


@dataclass(frozen=True)
class ImageApiConfig:
    api_key: str
    base_url: str = DEFAULT_IMAGE_API_BASE_URL
    model: str = DEFAULT_IMAGE_API_MODEL
    size: str = DEFAULT_IMAGE_API_SIZE
    quality: str = DEFAULT_IMAGE_API_QUALITY
    max_parallel: int = DEFAULT_IMAGE_API_PARALLELISM
    timeout_seconds: int = DEFAULT_IMAGE_API_TIMEOUT_SECONDS
    output_format: str = DEFAULT_IMAGE_API_OUTPUT_FORMAT
    response_format: str = DEFAULT_IMAGE_API_RESPONSE_FORMAT
    key_source: str = DEFAULT_IMAGE_API_KEY_ENV
    model_override: bool = False
    size_override: bool = False
    quality_override: bool = False
    output_format_override: bool = False
    response_format_override: bool = False


@dataclass(frozen=True)
class ImageApiResponse:
    image_bytes: bytes
    endpoint: str
    http_status: int
    elapsed_seconds: float
    request_id: str | None
    response_id: str | None
    created: int | None
    usage: dict[str, Any] | None
    response_keys: list[str]
    provider_image_url: str | None = None


def load_image_api_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    size: str | None = None,
    quality: str | None = None,
    response_format: str | None = None,
    max_parallel: int | None = None,
    timeout_seconds: int | None = None,
    key_file: str | Path | None = None,
) -> ImageApiConfig:
    key, key_source = _load_api_key(api_key=api_key, key_file=key_file)
    if not isinstance(key, str) or not key.strip():
        raise ValidationError(
            f"{DEFAULT_IMAGE_API_KEY_ENV} is required for image API generation, "
            "or configure a local key file with `python3 .skill/scripts/pptctl.py configure-image-api-key --stdin`"
        )
    resolved_parallel = max_parallel if max_parallel is not None else DEFAULT_IMAGE_API_PARALLELISM
    resolved_timeout = timeout_seconds if timeout_seconds is not None else DEFAULT_IMAGE_API_TIMEOUT_SECONDS
    if resolved_parallel < 1:
        raise ValidationError("image API max_parallel must be positive")
    if resolved_timeout < 1:
        raise ValidationError("image API timeout_seconds must be positive")
    env_model = os.environ.get(DEFAULT_IMAGE_API_MODEL_ENV)
    env_size = os.environ.get(DEFAULT_IMAGE_API_SIZE_ENV)
    env_quality = os.environ.get(DEFAULT_IMAGE_API_QUALITY_ENV)
    env_response_format = os.environ.get(DEFAULT_IMAGE_API_RESPONSE_FORMAT_ENV)
    return ImageApiConfig(
        api_key=key,
        base_url=(base_url or os.environ.get(DEFAULT_IMAGE_API_BASE_URL_ENV) or DEFAULT_IMAGE_API_BASE_URL).rstrip("/") + "/",
        model=model or env_model or DEFAULT_IMAGE_API_MODEL,
        size=size or env_size or DEFAULT_IMAGE_API_SIZE,
        quality=quality or env_quality or DEFAULT_IMAGE_API_QUALITY,
        response_format=response_format or env_response_format or DEFAULT_IMAGE_API_RESPONSE_FORMAT,
        max_parallel=resolved_parallel,
        timeout_seconds=resolved_timeout,
        key_source=key_source,
        model_override=model is not None or env_model is not None,
        size_override=size is not None or env_size is not None,
        quality_override=quality is not None or env_quality is not None,
        response_format_override=response_format is not None or env_response_format is not None,
    )


def configure_image_api_key(api_key: str, *, key_file: str | Path | None = None) -> Path:
    key = api_key.strip()
    if not key:
        raise ValidationError("image API key cannot be empty")
    path = _resolve_key_file(key_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def image_api_key_status(*, key_file: str | Path | None = None) -> dict[str, Any]:
    env_key = os.environ.get(DEFAULT_IMAGE_API_KEY_ENV)
    path = _resolve_key_file(key_file)
    file_key = _read_key_file(path)
    if isinstance(env_key, str) and env_key.strip():
        source = DEFAULT_IMAGE_API_KEY_ENV
        configured = True
    elif isinstance(file_key, str) and file_key.strip():
        source = str(path)
        configured = True
    else:
        source = "missing"
        configured = False
    return {
        "status": "configured" if configured else "missing",
        "env": DEFAULT_IMAGE_API_KEY_ENV,
        "env_configured": isinstance(env_key, str) and bool(env_key.strip()),
        "key_file": str(path),
        "key_file_configured": isinstance(file_key, str) and bool(file_key.strip()),
        "effective_source": source,
    }


def run_image_api_batch(
    run_dir: str | Path,
    batch_file: str | Path,
    *,
    config: ImageApiConfig,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = Path(run_dir)
    batch_path = _resolve_path(root, batch_file)
    batch = read_json(batch_path)
    route = normalize_image_generation_route(batch.get("image_generation_route") or batch.get("execution_tool"))
    if route != IMAGE_ROUTE_OPENAI_IMAGE_API:
        raise ValidationError("run-image-api-batch can only execute openai_image_api batches; use Codex image_gen manually for codex_image_gen packets")
    if batch.get("stage") != "stage2":
        raise ValidationError("run-image-api-batch only supports formal stage2 image batches")
    packet_paths = [_resolve_path(root, path) for path in batch.get("packet_paths", [])]
    if not packet_paths:
        raise ValidationError("image API batch has no packet_paths")

    completed = batch.get("results") if isinstance(batch.get("results"), dict) else {}
    work_items: list[tuple[Path, dict[str, Any]]] = []
    skipped: list[str] = []
    for packet_path in packet_paths:
        packet = read_json(packet_path)
        packet_id = packet.get("packet_id")
        require_current_image_style(root, packet)
        prior = completed.get(packet_id, {})
        prompt_digest = hashlib.sha256(packet["prompt"].encode()).hexdigest()
        expected = batch.get("packet_prompt_hashes", {}).get(packet_id)
        if expected and expected != prompt_digest:
            raise ValidationError("批次创建后提示词已变化，请重新派发")
        prior_image = root / prior.get("image_path", "__missing__")
        reusable = (prior.get("prompt_text_sha256") == prompt_digest and prior_image.is_file()
                    and "sha256:" + hashlib.sha256(prior_image.read_bytes()).hexdigest() == prior.get("image_sha256"))
        if not force and reusable:
            skipped.append(packet_id)
            continue
        work_items.append((packet_path, packet))

    started_at = now_iso()
    effective_parallel = min(
        config.max_parallel,
        _batch_max_parallel(batch),
        DEFAULT_IMAGE_API_PARALLELISM,
        max(len(work_items), 1),
    )
    report_path = _batch_run_report_path(root, batch_path, batch)
    if dry_run:
        report = {
            "schema_version": "1.0",
            "status": "dry_run",
            "batch_path": _relative_or_text(root, batch_path),
            "total_packets": len(packet_paths),
            "planned_packets": len(work_items),
            "skipped_packets": skipped,
            "max_parallel": effective_parallel,
            "timeout_seconds": config.timeout_seconds,
            "model": config.model,
            "size": config.size,
            "quality": config.quality,
            "response_format": config.response_format,
            "key_source": config.key_source,
            "started_at": started_at,
            "completed_at": now_iso(),
        }
        write_json(report_path, report)
        return report

    for _, packet in work_items:
        require_current_image_style(root, packet)
    work_items = [prepare_image_request(root, path, packet) for path, packet in work_items]

    request_results: list[dict[str, Any]] = []
    if work_items:
        with ThreadPoolExecutor(max_workers=effective_parallel) as executor:
            futures = {
                executor.submit(_request_packet_image, root, packet_path, packet, config): (packet_path, packet)
                for packet_path, packet in work_items
            }
            for future in as_completed(futures):
                packet_path, packet = futures[future]
                try:
                    response = future.result()
                    request_results.append(_write_api_output(root, packet_path, packet, response, config))
                except Exception as exc:  # noqa: BLE001 - stored as batch evidence.
                    request_results.append(_failed_packet_result(root, packet_path, packet, exc))
                    record_prompt_document(root, packet, status="生成失败，待主控检查或重试")

    recorded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for item in request_results:
        if item.get("status") != "api_completed":
            failed.append(item)
            continue
        packet_path = _resolve_path(root, item["packet_path"])
        packet = read_json(packet_path)
        api_call_id = item["api_call_id"]
        image_api_result_id = item["image_api_result_id"]
        result = record_image_result(
            root,
            packet_path,
            _resolve_path(root, item["output_image_path"]),
            IMAGE_API_PROVIDER,
            IMAGE_API_PROVIDER,
            image_api_result_id,
            tool_call_id=api_call_id,
            image_gen_result_id=image_api_result_id,
            api_call_id=api_call_id,
            image_api_result_id=image_api_result_id,
            request_id=item.get("request_id"),
            api_base_url=_redacted_base_url(config.base_url),
            api_endpoint=item["api_endpoint"],
            model=item["model"],
            response_format=item["response_format"],
            api_evidence_path=item["api_evidence_path"],
            provider_image_url=item.get("provider_image_url"),
        )
        evidence = read_json(_resolve_path(root, item["api_evidence_path"]))
        evidence["recorded_result_path"] = result.get("result_path")
        evidence["visible_image_path"] = result["image_path"]
        evidence["recorded_at"] = now_iso()
        write_json(_resolve_path(root, item["api_evidence_path"]), evidence)
        recorded.append(
            {
                "packet_id": packet["packet_id"],
                "slide_index": packet["slide_index"],
                "option_id": packet.get("option_id"),
                "image_path": result["image_path"],
                "result_path": result.get("result_path"),
                "prompt_document_status": result.get("prompt_document_status", "ready"),
                "image_sha256": result["image_sha256"],
                "api_evidence_path": item["api_evidence_path"],
            }
        )

    status = "completed" if not failed else ("failed" if not recorded else "partial_failed")
    pending_docs = [x["packet_id"] for x in recorded if x.get("prompt_document_status") == "pending_repair"]
    if pending_docs and status == "completed":
        status = "images_completed_document_pending"
    report = {
        "schema_version": "1.0",
        "document_repair_required": pending_docs,
        "status": status,
        "batch_path": _relative_or_text(root, batch_path),
        "total_packets": len(packet_paths),
        "requested_packets": len(work_items),
        "recorded_packets": len(recorded),
        "failed_packets": len(failed),
        "skipped_packets": skipped,
        "max_parallel": effective_parallel,
        "timeout_seconds": config.timeout_seconds,
        "model": config.model,
        "size": config.size,
        "quality": config.quality,
        "response_format": config.response_format,
        "key_source": config.key_source,
        "records": recorded,
        "failures": failed,
        "started_at": started_at,
        "completed_at": now_iso(),
    }
    write_json(report_path, report)
    return report


def default_batch_path_for_stage(run_dir: str | Path, stage: str) -> Path:
    root = Path(run_dir).resolve()
    if stage == "cover-options":
        return root / "_state" / "阶段2" / "cover_options" / "batches" / "stage2-cover-options-image-api.json"
    if stage == "stage2-trial-first5":
        return root / "_state" / "阶段2" / "trial_first5" / "batches" / "stage2-trial-first5-image-api.json"
    if stage == "stage2-remaining":
        return root / "_state" / "阶段2" / "image_api_batches" / "stage2-remaining-image-api.json"
    if stage == "stage2":
        return root / "_state" / "阶段2" / "image_api_batches" / "stage2-image-api.json"
    if stage in {"stage3", "stage3-background"}:
        raise ValidationError("stage3 background image API batches were removed from the formal workflow")
    raise ValidationError(f"unsupported image API stage: {stage}")


def _request_packet_image(root: Path, packet_path: Path, packet: dict[str, Any], config: ImageApiConfig) -> ImageApiResponse:
    image_input = packet.get("image_api_input")
    if not isinstance(image_input, dict):
        raise ValidationError("packet.image_api_input is required for image API execution")
    endpoint = image_input.get("endpoint")
    if endpoint not in SUPPORTED_IMAGE_API_ENDPOINTS:
        raise ValidationError("packet.image_api_input.endpoint is invalid")
    prompt = packet.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValidationError("packet.prompt is required for image API execution")
    deadline = time.monotonic() + config.timeout_seconds
    if endpoint == GRSAI_DRAW_COMPLETIONS_ENDPOINT:
        return _post_grsai_draw_completion(config, prompt, endpoint, image_input, deadline)
    if endpoint == DEFAULT_IMAGE_API_EDITS_ENDPOINT:
        references = image_input.get("referenced_image_paths")
        if not isinstance(references, list) or not references:
            raise ValidationError("image edits require referenced_image_paths")
        image_paths = [_resolve_path(root, path) for path in references]
        return _post_image_edit(config, prompt, endpoint, image_paths, image_input, deadline)
    return _post_image_generation(config, prompt, endpoint, image_input, deadline)


def _post_image_generation(
    config: ImageApiConfig,
    prompt: str,
    endpoint: str,
    image_input: dict[str, Any],
    deadline: float,
) -> ImageApiResponse:
    options = _request_options(config, image_input)
    body = {
        "model": options["model"],
        "prompt": prompt,
        "n": 1,
        "size": options["size"],
        "quality": options["quality"],
        "output_format": options["output_format"],
        "response_format": options["response_format"],
    }
    status, headers, raw, elapsed = _http_request(config, endpoint, "application/json", json.dumps(body).encode("utf-8"), deadline)
    return _parse_image_api_response(status, headers, raw, elapsed, endpoint, deadline)


def _post_grsai_draw_completion(
    config: ImageApiConfig,
    prompt: str,
    endpoint: str,
    image_input: dict[str, Any],
    deadline: float,
) -> ImageApiResponse:
    options = _request_options(config, image_input)
    body: dict[str, Any] = {
        "model": options["model"],
        "prompt": prompt,
        "aspectRatio": image_input.get("aspectRatio") or options["size"],
        "shutProgress": bool(image_input.get("shutProgress", False)),
    }
    urls = image_input.get("urls")
    if isinstance(urls, list) and urls:
        body["urls"] = urls
    web_hook = image_input.get("webHook")
    if isinstance(web_hook, str) and web_hook.strip():
        body["webHook"] = web_hook
    status, headers, raw, elapsed = _http_request(config, endpoint, "application/json", json.dumps(body).encode("utf-8"), deadline)
    return _parse_image_api_response(status, headers, raw, elapsed, endpoint, deadline)


def _post_image_edit(
    config: ImageApiConfig,
    prompt: str,
    endpoint: str,
    image_paths: list[Path],
    image_input: dict[str, Any],
    deadline: float,
) -> ImageApiResponse:
    options = _request_options(config, image_input)
    fields = {
        "model": options["model"],
        "prompt": prompt,
        "n": "1",
        "size": options["size"],
        "quality": options["quality"],
        "output_format": options["output_format"],
        "response_format": options["response_format"],
    }
    body, content_type = _encode_multipart(fields, image_paths)
    status, headers, raw, elapsed = _http_request(config, endpoint, content_type, body, deadline)
    return _parse_image_api_response(status, headers, raw, elapsed, endpoint, deadline)


def _http_request(
    config: ImageApiConfig,
    endpoint: str,
    content_type: str,
    body: bytes,
    deadline: float,
) -> tuple[int, dict[str, str], bytes, float]:
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": content_type,
    }
    request = urllib.request.Request(_join_url(config.base_url, endpoint), data=body, headers=headers, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=_socket_timeout(deadline), context=ssl.create_default_context()) as response:
            return response.status, dict(response.headers), _read_response_body(response, deadline), time.monotonic() - started
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), _read_response_body(exc, deadline), time.monotonic() - started
    except urllib.error.URLError as exc:
        raise ValidationError(f"image API request failed before HTTP response: {exc.reason}") from exc
    except OSError as exc:
        raise ValidationError(f"image API request failed before HTTP response: {exc}") from exc


def _parse_image_api_response(
    status: int,
    headers: dict[str, str],
    raw: bytes,
    elapsed: float,
    endpoint: str,
    deadline: float,
) -> ImageApiResponse:
    _raise_if_deadline_exceeded(deadline)
    request_id = headers.get("x-request-id") or headers.get("X-Request-Id")
    raw_text = raw.decode("utf-8", errors="replace")
    content_type = headers.get("content-type") or headers.get("Content-Type") or ""
    if "text/event-stream" in content_type or raw_text.lstrip().startswith("data:"):
        return _parse_grsai_event_stream_response(status, headers, raw_text, elapsed, endpoint, deadline)
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"image API returned non-JSON response with status {status}") from exc
    if status != 200:
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else str(payload)[:300]
        raise ValidationError(f"image API request failed with HTTP {status}: {message}")
    if not isinstance(payload, dict):
        raise ValidationError("image API response must be an object")
    if "results" in payload or ("data" in payload and isinstance(payload.get("data"), dict)):
        return _parse_grsai_json_response(payload, status, headers, elapsed, endpoint, deadline)
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise ValidationError("image API response missing data[0]")
    item = data[0]
    if not isinstance(item, dict):
        raise ValidationError("image API response data[0] must be an object")
    image_bytes, provider_image_url = _extract_image_bytes(item, deadline)
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    created = payload.get("created") if isinstance(payload.get("created"), int) else None
    response_id = payload.get("id") if isinstance(payload.get("id"), str) else None
    return ImageApiResponse(
        image_bytes=image_bytes,
        endpoint=endpoint,
        http_status=status,
        elapsed_seconds=elapsed,
        request_id=request_id,
        response_id=response_id,
        created=created,
        usage=usage,
        response_keys=sorted(payload.keys()),
        provider_image_url=provider_image_url,
    )


def _parse_grsai_event_stream_response(
    status: int,
    headers: dict[str, str],
    raw_text: str,
    elapsed: float,
    endpoint: str,
    deadline: float,
) -> ImageApiResponse:
    _raise_if_deadline_exceeded(deadline)
    if status != 200:
        raise ValidationError(f"image API request failed with HTTP {status}: {raw_text[:300]}")
    events: list[dict[str, Any]] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            item = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    if not events:
        raise ValidationError("image API event stream did not contain JSON data events")
    return _parse_grsai_json_response(events[-1], status, headers, elapsed, endpoint, deadline)


def _parse_grsai_json_response(
    payload: dict[str, Any],
    status: int,
    headers: dict[str, str],
    elapsed: float,
    endpoint: str,
    deadline: float,
) -> ImageApiResponse:
    _raise_if_deadline_exceeded(deadline)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        raise ValidationError("image API Grsai response data must be an object")
    response_status = data.get("status")
    if response_status not in {"succeeded", "success", "finish", "finished"}:
        error = data.get("error") or data.get("failure_reason") or payload.get("msg") or str(data)[:300]
        raise ValidationError(f"image API Grsai task did not succeed: {response_status or 'unknown'} {error}")
    results = data.get("results")
    if not isinstance(results, list) or not results:
        raise ValidationError("image API Grsai response missing results[0]")
    first = results[0]
    if isinstance(first, str):
        item = {"url": first}
    elif isinstance(first, dict):
        item = first
    else:
        raise ValidationError("image API Grsai response results[0] must be a URL or object")
    image_bytes, provider_image_url = _extract_image_bytes(item, deadline)
    request_id = headers.get("x-request-id") or headers.get("X-Request-Id")
    response_id = data.get("id") if isinstance(data.get("id"), str) else None
    created = data.get("start_time") if isinstance(data.get("start_time"), int) else None
    return ImageApiResponse(
        image_bytes=image_bytes,
        endpoint=endpoint,
        http_status=status,
        elapsed_seconds=elapsed,
        request_id=request_id,
        response_id=response_id,
        created=created,
        usage=None,
        response_keys=sorted(data.keys()),
        provider_image_url=provider_image_url,
    )


def _extract_image_bytes(item: dict[str, Any], deadline: float) -> tuple[bytes, str | None]:
    _raise_if_deadline_exceeded(deadline)
    b64_json = item.get("b64_json")
    if isinstance(b64_json, str) and b64_json.strip():
        try:
            return base64.b64decode(b64_json, validate=True), None
        except (binascii.Error, ValueError) as exc:
            raise ValidationError("image API response data[0].b64_json is not valid base64") from exc
    url = item.get("url")
    if isinstance(url, str) and url.strip():
        try:
            with urllib.request.urlopen(url, timeout=_socket_timeout(deadline), context=ssl.create_default_context()) as response:
                return _read_response_body(response, deadline), url
        except urllib.error.HTTPError as exc:
            raise ValidationError(f"image API returned provider URL but downloading it failed with HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ValidationError(f"image API returned provider URL but downloading it failed: {exc.reason}") from exc
        except OSError as exc:
            raise ValidationError(f"image API returned provider URL but downloading it failed: {exc}") from exc
    raise ValidationError("image API response data[0] does not contain b64_json or url")


def _write_api_output(
    root: Path,
    packet_path: Path,
    packet: dict[str, Any],
    response: ImageApiResponse,
    config: ImageApiConfig,
) -> dict[str, Any]:
    packet_id = _require_packet_id(packet)
    image_input = packet.get("image_api_input") if isinstance(packet.get("image_api_input"), dict) else {}
    options = _request_options(config, image_input)
    image_sha = "sha256:" + hashlib.sha256(response.image_bytes).hexdigest()
    output_path = _api_output_path(root, packet, options["output_format"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.image_bytes)

    api_call_id = response.request_id or _fallback_api_call_id(packet_id, response)
    image_api_result_id = response.response_id or f"{api_call_id}:image-0"
    evidence_path = _api_evidence_path(root, packet)
    evidence = {
        "schema_version": "1.0",
        "provider": IMAGE_API_PROVIDER,
        "packet_id": packet_id,
        "packet_path": _relative_or_text(root, packet_path),
        "prompt_hash": packet.get("prompt_hash"),
        "api_call_id": api_call_id,
        "image_api_result_id": image_api_result_id,
        "request_id": response.request_id,
        "api_base_url": _redacted_base_url(config.base_url),
        "key_source": config.key_source,
        "api_endpoint": response.endpoint,
        "model": options["model"],
        "size": options["size"],
        "quality": options["quality"],
        "output_format": options["output_format"],
        "response_format": options["response_format"],
        "packet_image_api_input": image_input,
        "timeout_seconds": config.timeout_seconds,
        "http_status": response.http_status,
        "elapsed_seconds": round(response.elapsed_seconds, 3),
        "response_id": response.response_id,
        "created": response.created,
        "usage": response.usage,
        "response_keys": response.response_keys,
        "provider_image_url": response.provider_image_url,
        "output_image_path": _relative_or_text(root, output_path),
        "image_sha256": image_sha,
        "created_at": now_iso(),
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(evidence_path, evidence)
    return {
        "status": "api_completed",
        "packet_id": packet_id,
        "packet_path": _relative_or_text(root, packet_path),
        "output_image_path": _relative_or_text(root, output_path),
        "api_evidence_path": _relative_or_text(root, evidence_path),
        "api_call_id": api_call_id,
        "image_api_result_id": image_api_result_id,
        "request_id": response.request_id,
        "api_endpoint": response.endpoint,
        "model": options["model"],
        "response_format": options["response_format"],
        "image_sha256": image_sha,
        "provider_image_url": response.provider_image_url,
    }


def _failed_packet_result(root: Path, packet_path: Path, packet: dict[str, Any], exc: Exception) -> dict[str, Any]:
    return {
        "status": "failed",
        "packet_id": packet.get("packet_id"),
        "packet_path": _relative_or_text(root, packet_path),
        "error_type": type(exc).__name__,
        "error": str(exc),
        "failed_at": now_iso(),
    }


def _encode_multipart(fields: dict[str, str], image_paths: list[Path]) -> tuple[bytes, str]:
    boundary = f"----ppt-skill-v3-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for path in image_paths:
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"referenced image not found: {path}")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="image[]"; filename="{path.name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8")
        )
        chunks.append(path.read_bytes())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _api_output_path(root: Path, packet: dict[str, Any], output_format: str) -> Path:
    packet_id = _require_packet_id(packet)
    if packet.get("generation_request_id"):
        packet_id += "-" + packet["generation_request_id"]
    suffix = f".{output_format.lower()}"
    if packet.get("purpose") == "cover_option":
        return root / "_state" / "阶段2" / "cover_options" / "api_outputs" / f"{packet_id}{suffix}"
    if packet.get("purpose") == "trial_first5":
        return root / "_state" / "阶段2" / "trial_first5" / "api_outputs" / f"{packet_id}{suffix}"
    if packet.get("stage") == "stage2":
        return root / "_state" / "阶段2" / "api_outputs" / f"{packet_id}{suffix}"
    if packet.get("stage") == "stage3":
        raise ValidationError("stage3 background image API outputs were removed from the formal workflow")
    raise ValidationError("packet.stage must be stage2 or stage3")


def _api_evidence_path(root: Path, packet: dict[str, Any]) -> Path:
    packet_id = _require_packet_id(packet)
    if packet.get("generation_request_id"):
        packet_id += "-" + packet["generation_request_id"]
    if packet.get("purpose") == "cover_option":
        return root / "_state" / "阶段2" / "cover_options" / "api_calls" / f"{packet_id}.json"
    if packet.get("purpose") == "trial_first5":
        return root / "_state" / "阶段2" / "trial_first5" / "api_calls" / f"{packet_id}.json"
    if packet.get("stage") == "stage2":
        return root / "_state" / "阶段2" / "api_calls" / f"{packet_id}.json"
    if packet.get("stage") == "stage3":
        raise ValidationError("stage3 background image API evidence was removed from the formal workflow")
    raise ValidationError("packet.stage must be stage2 or stage3")


def _load_api_key(*, api_key: str | None, key_file: str | Path | None) -> tuple[str | None, str]:
    if isinstance(api_key, str) and api_key.strip():
        return api_key, "argument"
    env_key = os.environ.get(DEFAULT_IMAGE_API_KEY_ENV)
    if isinstance(env_key, str) and env_key.strip():
        return env_key, DEFAULT_IMAGE_API_KEY_ENV
    path = _resolve_key_file(key_file)
    file_key = _read_key_file(path)
    if isinstance(file_key, str) and file_key.strip():
        return file_key, str(path)
    return None, "missing"


def _resolve_key_file(key_file: str | Path | None) -> Path:
    if key_file is not None:
        return Path(key_file).expanduser()
    env_path = os.environ.get(DEFAULT_IMAGE_API_KEY_FILE_ENV)
    if isinstance(env_path, str) and env_path.strip():
        return Path(env_path).expanduser()
    return DEFAULT_IMAGE_API_KEY_FILE


def _read_key_file(path: Path) -> str | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValidationError(f"cannot read image API key file: {path}") from exc


def _request_options(config: ImageApiConfig, image_input: dict[str, Any]) -> dict[str, str]:
    return {
        "model": _request_option(config.model, image_input.get("model"), config.model_override),
        "size": _request_option(config.size, image_input.get("size"), config.size_override),
        "quality": _request_option(config.quality, image_input.get("quality"), config.quality_override),
        "output_format": _request_option(config.output_format, image_input.get("output_format"), config.output_format_override),
        "response_format": _request_option(config.response_format, image_input.get("response_format"), config.response_format_override),
    }


def _request_option(config_value: str, packet_value: Any, override: bool) -> str:
    if override:
        return config_value
    if isinstance(packet_value, str) and packet_value.strip():
        return packet_value
    return config_value


def _batch_max_parallel(batch: dict[str, Any]) -> int:
    value = batch.get("max_parallel")
    if isinstance(value, int) and value > 0:
        return value
    return DEFAULT_IMAGE_API_PARALLELISM


def _socket_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("image API task exceeded timeout_seconds")
    return max(0.001, remaining)


def _raise_if_deadline_exceeded(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise TimeoutError("image API task exceeded timeout_seconds")


def _read_response_body(response: Any, deadline: float) -> bytes:
    chunks: list[bytes] = []
    while True:
        _raise_if_deadline_exceeded(deadline)
        chunk = response.read(1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _batch_run_report_path(root: Path, batch_path: Path, batch: dict[str, Any]) -> Path:
    batch_id = batch.get("batch_id") if isinstance(batch.get("batch_id"), str) else "image-api-batch"
    stamp = str(int(time.time()))
    if "cover_options" in batch_path.parts:
        return root / "_state" / "阶段2" / "cover_options" / "api_batch_runs" / f"{batch_id}-{stamp}.json"
    if "trial_first5" in batch_path.parts:
        return root / "_state" / "阶段2" / "trial_first5" / "api_batch_runs" / f"{batch_id}-{stamp}.json"
    if batch.get("stage") == "stage2":
        return root / "_state" / "阶段2" / "api_batch_runs" / f"{batch_id}-{stamp}.json"
    if batch.get("stage") == "stage3":
        raise ValidationError("stage3 background image API batch runs were removed from the formal workflow")
    return root / "_state" / "api_batch_runs" / f"{batch_id}-{stamp}.json"


def _resolve_path(root: Path, path: str | Path) -> Path:
    value = Path(path)
    if value.is_absolute():
        return value
    return root / value


def _relative_or_text(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _require_packet_id(packet: dict[str, Any]) -> str:
    packet_id = packet.get("packet_id")
    if not isinstance(packet_id, str) or not packet_id.strip():
        raise ValidationError("packet.packet_id must be a non-empty string")
    return packet_id


def _fallback_api_call_id(packet_id: str, response: ImageApiResponse) -> str:
    digest = hashlib.sha256(f"{packet_id}:{response.created}:{response.elapsed_seconds}".encode("utf-8")).hexdigest()
    return f"api-call-{packet_id}-{digest[:12]}"


def _join_url(base_url: str, endpoint: str) -> str:
    return base_url.rstrip("/") + "/" + endpoint.lstrip("/")


def _redacted_base_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/"
