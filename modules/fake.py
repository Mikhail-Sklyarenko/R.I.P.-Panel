"""Заглушки модулей для --test-mode (без Steam, Node, csgobot)."""

from __future__ import annotations

from typing import Any

_ENABLED = False


def is_enabled() -> bool:
    return _ENABLED


def enable() -> None:
    global _ENABLED
    _ENABLED = True


def disable() -> None:
    global _ENABLED
    _ENABLED = False


def _ok(module: str, **extra: Any) -> dict[str, Any]:
    return {"module": module, "fake": True, **extra}


class FakeLauncher:
    def run(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return _ok("launcher", events=["steam_ok", "cs2_ok"])


class FakeDmRunner:
    def run(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return _ok("dm_runner", events=["in_menu", "searching_dm", "in_dm"])


class FakeCombat:
    def start(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return _ok("combat", mode="ai")

    def stop(self, ctx: dict[str, Any] | None = None) -> None:
        return None


class FakeDropPicker:
    def pick(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return _ok("drop_picker")


class FakeLooter:
    def send_trade(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        return _ok("looter", events=["loot_ok"])


class FakeTelegram:
    def notify(self, ctx: dict[str, Any] | None = None) -> None:
        return None


class FakeVault:
    def load_account(self, account_id: str) -> dict[str, Any]:
        return {
            "login": account_id,
            "password": "fake",
            "shared_secret": "fake",
            "identity_secret": "fake",
            "level": 0,
            "farmed_this_week": False,
        }


def get_registry() -> dict[str, Any]:
    """Имена модулей → fake-реализации."""
    return {
        "launcher": FakeLauncher(),
        "dm_runner": FakeDmRunner(),
        "combat": FakeCombat(),
        "drop_picker": FakeDropPicker(),
        "looter": FakeLooter(),
        "telegram": FakeTelegram(),
        "vault": FakeVault(),
    }
