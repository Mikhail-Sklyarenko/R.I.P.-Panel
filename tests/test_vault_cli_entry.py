"""main.py --vault-cli entry."""

from __future__ import annotations

import pytest

from main import main


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    from config.loader import ensure_config

    ensure_config()
    return tmp_path


def test_vault_cli_list_empty(data_dir) -> None:
    code = main(["--vault-cli", "list"])
    assert code == 0
