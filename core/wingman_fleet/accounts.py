"""Public account metadata. Secrets never appear in these types."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

STEAMID64_BASE = 76561197960265728
STEAM_ACCOUNT_MAX = 2**32


class BindingStatus(str, Enum):
    UNBOUND = "unbound"
    MANUALLY_BOUND = "manually_bound"
    VERIFIED = "verified"
    UNCONFIRMED = "unconfirmed"
    MISMATCH = "mismatch"


class Availability(str, Enum):
    AVAILABLE = "available"
    PREPARED = "prepared"
    COMMITTED = "committed"
    ACTIVE = "active"
    RECONCILE_REQUIRED = "reconcile_required"
    RELEASED = "released"
    DISABLED = "disabled"


class CatalogError(ValueError):
    pass


def parse_steam_id64(value: object) -> str:
    text = str(value or "").strip()
    if not text.isdigit() or len(text) != 17:
        raise CatalogError("steam_id64 must be 17 digits")
    account = int(text) - STEAMID64_BASE
    if account <= 0 or account >= STEAM_ACCOUNT_MAX:
        raise CatalogError("steam_id64 is outside the public Steam user range")
    return text


@dataclass(frozen=True)
class CatalogAccountView:
    """Fields an agent may send to the coordinator. Login and secrets are absent."""
    local_account_id: str
    steam_id64: str
    display_name: str
    enabled: bool
    binding_status: str
    availability_status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "local_account_id": self.local_account_id,
            "steam_id64": self.steam_id64,
            "display_name": self.display_name,
            "enabled": self.enabled,
            "binding_status": self.binding_status,
            "availability_status": self.availability_status,
        }


@dataclass(frozen=True)
class CatalogSnapshot:
    agent_id: str
    catalog_revision: int
    accounts: tuple[CatalogAccountView, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "catalog_revision": self.catalog_revision,
            "accounts": [item.as_dict() for item in self.accounts],
        }
