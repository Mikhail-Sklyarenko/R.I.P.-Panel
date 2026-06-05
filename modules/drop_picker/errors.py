"""drop_picker errors."""

from __future__ import annotations


class DropPickerError(Exception):
    pass


class CarePackageNotFoundError(DropPickerError):
    pass
