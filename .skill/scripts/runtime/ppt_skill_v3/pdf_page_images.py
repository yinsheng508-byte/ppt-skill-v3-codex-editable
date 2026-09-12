from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from PIL import Image, UnidentifiedImageError


DEFAULT_RENDER_DPI = 216
BASE_PDF_DPI = 72
DEFAULT_RENDER_SCALE = "3x_72dpi"
PDFTOPPM_ENV = "PPT_SKILL_PDFTOPPM"
POPPLER_PATH_ENV = "PPT_SKILL_POPPLER_PATH"
PDFTOPPM_TOOL = "pdftoppm"

_PDFTOPPM_PAGE_SUFFIX = re.compile(r"-(\d+)$")


class PdfPageImageError(RuntimeError):
    """PDF page image rendering failed after pdftoppm was found."""


class PdfPageImageUnavailable(PdfPageImageError):
    """pdftoppm is not available in the current environment."""


def render_pdf_pages_to_png(
    source_pdf: str | Path,
    target_dir: str | Path,
    *,
    dpi: int = DEFAULT_RENDER_DPI,
    filename_prefix: str = "page",
    pdftoppm_path: str | Path | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Render a PDF into target_dir/page_001.png ... using pdftoppm only."""

    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi <= 0:
        raise ValueError("dpi must be a positive integer")
    if not filename_prefix or not re.fullmatch(r"[A-Za-z0-9_-]+", filename_prefix):
        raise ValueError("filename_prefix must contain only ASCII letters, digits, underscores, or hyphens")

    pdf = Path(source_pdf)
    if not pdf.is_file():
        raise FileNotFoundError(f"source PDF not found: {pdf}")

    executable = Path(pdftoppm_path) if pdftoppm_path is not None else find_pdftoppm()
    if executable is None:
        raise PdfPageImageUnavailable(
            f"{PDFTOPPM_TOOL} not found; install Poppler or set {PDFTOPPM_ENV}/{POPPLER_PATH_ENV}"
        )

    target = Path(target_dir)
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".pdf_page_images_", dir=str(target.parent)) as tmp:
        staging_dir = Path(tmp)
        output_prefix = staging_dir / filename_prefix
        command = [
            str(executable),
            "-png",
            "-r",
            str(dpi),
            "-forcenum",
            str(pdf),
            str(output_prefix),
        ]
        try:
            result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout_seconds)
        except FileNotFoundError as exc:
            raise PdfPageImageUnavailable(f"{PDFTOPPM_TOOL} executable not found: {executable}") from exc
        except subprocess.TimeoutExpired as exc:
            raise PdfPageImageError(f"{PDFTOPPM_TOOL} timed out after {timeout_seconds}s") from exc

        if result.returncode != 0:
            detail = _short_error(result.stderr or result.stdout)
            raise PdfPageImageError(f"{PDFTOPPM_TOOL} failed with exit code {result.returncode}: {detail}")

        rendered_sources = sorted(
            staging_dir.glob(f"{filename_prefix}-*.png"),
            key=_pdftoppm_page_sort_key,
        )
        if not rendered_sources:
            raise PdfPageImageError(f"{PDFTOPPM_TOOL} did not produce PNG files")

        staged_outputs: list[dict[str, Any]] = []
        target.mkdir(parents=True, exist_ok=True)
        for index, rendered_source in enumerate(rendered_sources, start=1):
            width, height = _probe_png_size(rendered_source)
            temp_target = target / f".{filename_prefix}_{index:03d}.tmp.png"
            final_target = target / f"{filename_prefix}_{index:03d}.png"
            if temp_target.exists():
                temp_target.unlink()
            shutil.copy2(rendered_source, temp_target)
            staged_outputs.append(
                {
                    "page": index,
                    "temp_target": temp_target,
                    "final_target": final_target,
                    "width_px": width,
                    "height_px": height,
                }
            )

        for old_page in target.glob(f"{filename_prefix}_*.png"):
            if old_page.is_file():
                old_page.unlink()
        images: list[dict[str, Any]] = []
        for item in staged_outputs:
            item["temp_target"].replace(item["final_target"])
            images.append(
                {
                    "page": item["page"],
                    "path": str(item["final_target"]),
                    "width_px": item["width_px"],
                    "height_px": item["height_px"],
                    "sha256": _sha256_file(item["final_target"]),
                }
            )

    return {
        "schema_version": "1.0",
        "status": "rendered",
        "source_pdf": str(pdf),
        "target_dir": str(target),
        "render_dpi": dpi,
        "render_scale": _render_scale(dpi),
        "tool": PDFTOPPM_TOOL,
        "tool_path": str(executable),
        "pages": len(images),
        "images": images,
    }


def find_pdftoppm(
    *,
    env: Mapping[str, str] | None = None,
    system_name: str | None = None,
    which: Callable[[str], str | None] = shutil.which,
    exists: Callable[[Path], bool] | None = None,
) -> Path | None:
    env_map = os.environ if env is None else env
    system = platform.system() if system_name is None else system_name
    exists_fn = (lambda path: path.is_file()) if exists is None else exists
    command_names = _pdftoppm_command_names(system)

    explicit = _clean_env_path(env_map.get(PDFTOPPM_ENV))
    if explicit:
        path = _resolve_explicit_command(explicit, which=which, exists=exists_fn)
        return path

    poppler_dir = _clean_env_path(env_map.get(POPPLER_PATH_ENV))
    if poppler_dir:
        for command_name in command_names:
            candidate = Path(poppler_dir).expanduser() / command_name
            if exists_fn(candidate):
                return candidate

    for command_name in command_names:
        resolved = which(command_name)
        if resolved:
            return Path(resolved)

    for candidate in _common_pdftoppm_paths(env_map, system):
        if exists_fn(candidate):
            return candidate
    return None


def _resolve_explicit_command(
    value: str,
    *,
    which: Callable[[str], str | None],
    exists: Callable[[Path], bool],
) -> Path | None:
    path = Path(value).expanduser()
    if exists(path):
        return path
    resolved = which(value)
    if resolved:
        return Path(resolved)
    return None


def _pdftoppm_command_names(system_name: str) -> tuple[str, ...]:
    if system_name.lower().startswith("win"):
        return ("pdftoppm.exe", "pdftoppm")
    return ("pdftoppm",)


def _common_pdftoppm_paths(env: Mapping[str, str], system_name: str) -> list[Path]:
    if system_name.lower().startswith("win"):
        paths: list[Path] = []
        for key in ("ProgramFiles", "ProgramFiles(x86)"):
            base = _clean_env_path(env.get(key))
            if base:
                paths.extend(
                    [
                        Path(base) / "poppler" / "Library" / "bin" / "pdftoppm.exe",
                        Path(base) / "poppler" / "bin" / "pdftoppm.exe",
                    ]
                )
        userprofile = _clean_env_path(env.get("USERPROFILE"))
        if userprofile:
            paths.append(Path(userprofile) / "scoop" / "apps" / "poppler" / "current" / "bin" / "pdftoppm.exe")
        chocolatey = _clean_env_path(env.get("ChocolateyInstall"))
        if chocolatey:
            paths.append(Path(chocolatey) / "bin" / "pdftoppm.exe")
        paths.extend(
            [
                Path("C:/poppler/Library/bin/pdftoppm.exe"),
                Path("C:/poppler/bin/pdftoppm.exe"),
                Path("C:/ProgramData/chocolatey/bin/pdftoppm.exe"),
            ]
        )
        return paths
    return [
        Path("/opt/homebrew/bin/pdftoppm"),
        Path("/usr/local/bin/pdftoppm"),
        Path("/usr/bin/pdftoppm"),
    ]


def _clean_env_path(value: str | None) -> str:
    return value.strip().strip('"') if isinstance(value, str) else ""


def _pdftoppm_page_sort_key(path: Path) -> tuple[int, str]:
    match = _PDFTOPPM_PAGE_SUFFIX.search(path.stem)
    if not match:
        return (10**9, path.name)
    return (int(match.group(1)), path.name)


def _probe_png_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise PdfPageImageError(f"rendered PNG is invalid: {path}") from exc
    return width, height


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _render_scale(dpi: int) -> str:
    if dpi == DEFAULT_RENDER_DPI:
        return DEFAULT_RENDER_SCALE
    if dpi % BASE_PDF_DPI == 0:
        return f"{dpi // BASE_PDF_DPI}x_72dpi"
    return f"{dpi / BASE_PDF_DPI:.2f}x_72dpi"


def _short_error(text: str, limit: int = 500) -> str:
    stripped = " ".join(text.split())
    if not stripped:
        return "no error output"
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3] + "..."
