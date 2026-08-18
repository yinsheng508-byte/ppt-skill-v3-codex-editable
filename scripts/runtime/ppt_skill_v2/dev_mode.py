from __future__ import annotations

import os

from .validation import ValidationError


DEV_FIXTURE_ENV = "PPT_SKILL_V2_ENABLE_DEV_FIXTURES"


def require_dev_fixture_enabled() -> None:
    if os.environ.get(DEV_FIXTURE_ENV) != "1":
        raise ValidationError(f"dev fixture mode requires {DEV_FIXTURE_ENV}=1")
