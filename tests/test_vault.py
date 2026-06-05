"""Vault CLI: add → list без logpass.txt."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.loader import ensure_config
from modules.vault.cli import main as vault_main
from modules.vault.store import AccountExistsError, add_account, list_accounts


FIXTURE_MAFILE = Path(__file__).parent / "fixtures" / "sample_mafile.json"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    ensure_config()
    return tmp_path


def test_add_account_list_metadata(data_dir) -> None:
    add_account(
        login="test_user",
        password="secret_pass",
        mafile_path=FIXTURE_MAFILE,
    )
    rows = list_accounts()
    assert len(rows) == 1
    assert rows[0].login == "test_user"
    assert rows[0].level == 0
    assert rows[0].farmed_this_week is False


def test_add_duplicate_raises(data_dir) -> None:
    add_account(login="test_user", password="p1", mafile_path=FIXTURE_MAFILE)
    with pytest.raises(AccountExistsError):
        add_account(login="test_user", password="p2", mafile_path=FIXTURE_MAFILE)


def test_cli_add_and_list(data_dir, capsys) -> None:
    code = vault_main(
        [
            "add",
            "--login",
            "test_user",
            "--password",
            "secret_pass",
            "--mafile",
            str(FIXTURE_MAFILE),
        ]
    )
    assert code == 0
    assert "added: test_user" in capsys.readouterr().out

    capsys.readouterr()
    assert vault_main(["list"]) == 0
    out = capsys.readouterr().out
    assert "test_user" in out
    assert "0" in out
    assert "false" in out


def test_index_has_no_password_field(data_dir) -> None:
    add_account(login="test_user", password="secret_pass", mafile_path=FIXTURE_MAFILE)
    text = (data_dir / "accounts.index.json").read_text(encoding="utf-8")
    assert "secret_pass" not in text
    assert "password" not in text
