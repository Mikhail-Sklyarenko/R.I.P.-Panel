"""Плагины фарм-цикла (launcher, dm_runner, …)."""

from importlib import import_module


__all__ = [
    "combat",
    "dm_runner",
    "drop_picker",
    "launcher",
    "looter",
    "telegram",
    "utils",
    "vault",
]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(name)
    module = import_module(f"{__name__}.{name}")
    globals()[name] = module
    return module
