"""Drop picker: 4 slots → OCR → Steam/cache price → click top 2."""

from __future__ import annotations

from typing import Any

from modules.drop_picker.errors import CarePackageNotFoundError, DropPickerError
from modules.drop_picker.pick import pick_care_package

__all__ = [
    "CarePackageNotFoundError",
    "DropPickerError",
    "pick",
    "pick_care_package",
]


def pick(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    return pick_care_package(ctx)
