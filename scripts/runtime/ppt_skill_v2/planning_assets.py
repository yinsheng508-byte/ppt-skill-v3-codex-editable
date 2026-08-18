from __future__ import annotations

from pathlib import Path
from typing import Any

from .json_io import read_json, write_json
from .paths import state_dir


def content_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / "阶段1" / "content.json"


def slide_prompt_briefs_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / "阶段1" / "slide_prompt_briefs.json"


def design_contract_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / "阶段1" / "design_contract.json"


def cover_selection_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / "阶段2" / "cover_options" / "selection" / "selection.json"


def cover_option_style_card_path(run_dir: str | Path, option_id: str) -> Path:
    return state_dir(run_dir) / "阶段2" / "cover_options" / "style_cards" / f"cover_option_{option_id}.json"


def deck_style_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / "阶段2" / "deck_style.json"


def layout_intent_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / "阶段2" / "layout_intent.json"


def stage2_aesthetic_review_path(run_dir: str | Path) -> Path:
    return state_dir(run_dir) / "阶段2" / "visual_qa" / "stage2_aesthetic_review.json"


def load_content(run_dir: str | Path) -> dict[str, Any]:
    return read_json(content_path(run_dir))


def save_content(run_dir: str | Path, content: dict[str, Any]) -> None:
    write_json(content_path(run_dir), content)


def load_slide_prompt_briefs(run_dir: str | Path) -> dict[str, Any]:
    return read_json(slide_prompt_briefs_path(run_dir))


def save_slide_prompt_briefs(run_dir: str | Path, briefs: dict[str, Any]) -> None:
    write_json(slide_prompt_briefs_path(run_dir), briefs)


def save_design_contract(run_dir: str | Path, contract: dict[str, Any]) -> None:
    write_json(design_contract_path(run_dir), contract)


def load_design_contract(run_dir: str | Path) -> dict[str, Any]:
    return read_json(design_contract_path(run_dir))


def save_cover_option_style_card(run_dir: str | Path, option_id: str, card: dict[str, Any]) -> None:
    write_json(cover_option_style_card_path(run_dir, option_id), card)


def load_cover_option_style_card(run_dir: str | Path, option_id: str) -> dict[str, Any]:
    return read_json(cover_option_style_card_path(run_dir, option_id))


def save_deck_style(run_dir: str | Path, style: dict[str, Any]) -> None:
    write_json(deck_style_path(run_dir), style)


def load_deck_style(run_dir: str | Path) -> dict[str, Any]:
    return read_json(deck_style_path(run_dir))


def save_layout_intent(run_dir: str | Path, intent: dict[str, Any]) -> None:
    write_json(layout_intent_path(run_dir), intent)


def load_layout_intent(run_dir: str | Path) -> dict[str, Any]:
    return read_json(layout_intent_path(run_dir))


def save_cover_selection(run_dir: str | Path, selection: dict[str, Any]) -> None:
    write_json(cover_selection_path(run_dir), selection)


def load_cover_selection(run_dir: str | Path) -> dict[str, Any]:
    return read_json(cover_selection_path(run_dir))


def save_stage2_aesthetic_review(run_dir: str | Path, review: dict[str, Any]) -> None:
    write_json(stage2_aesthetic_review_path(run_dir), review)


def load_stage2_aesthetic_review(run_dir: str | Path) -> dict[str, Any]:
    return read_json(stage2_aesthetic_review_path(run_dir))
