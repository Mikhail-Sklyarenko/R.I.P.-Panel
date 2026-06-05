"""B-IMPORT: logpass + maFiles → vault.enc."""

from __future__ import annotations

from pathlib import Path

import pytest

from config.loader import ensure_config
from config.paths import get_vault_enc_path
from modules.vault.cli import main as vault_main
from modules.vault.fsm_import import (
    find_mafile,
    import_from_fsm_files,
    is_import_staging_empty,
    parse_logpass,
)
from modules.vault.store import AccountExistsError, add_account, list_accounts, upsert_account

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "fsm_import"
FIXTURE_LOGPASS = FIXTURE_ROOT / "logpass.txt"
FIXTURE_MAFILES = FIXTURE_ROOT / "maFiles"
FIXTURE_MA_ONE = FIXTURE_MAFILES / "acc_one.maFile"


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FARM_PANEL_DATA_DIR", str(tmp_path))
    ensure_config()
    return tmp_path


def test_parse_logpass_first_colon_edge_case() -> None:
    pairs = parse_logpass(FIXTURE_LOGPASS)
    by_login = dict(pairs)
    assert by_login["acc_two"] == "pass_two:extra"


def test_parse_logpass_bad_line(tmp_path) -> None:
    bad = tmp_path / "bad.txt"
    bad.write_text("nocolon\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        parse_logpass(bad)


def test_find_mafile_case_insensitive(tmp_path) -> None:
    ma_dir = tmp_path / "maFiles"
    ma_dir.mkdir()
    (ma_dir / "UserX.maFile").write_text("{}", encoding="utf-8")
    found = find_mafile(ma_dir, "userx")
    assert found is not None
    assert found.name == "UserX.maFile"


def test_import_two_accounts(data_dir) -> None:
    results = import_from_fsm_files(
        logpass_path=FIXTURE_LOGPASS,
        mafiles_dir=FIXTURE_MAFILES,
    )
    statuses = {r.login: r.status for r in results if r.login in ("acc_one", "acc_two")}
    assert statuses["acc_one"] == "added"
    assert statuses["acc_two"] == "added"
    assert len(list_accounts()) == 2


def test_import_idempotent_update(data_dir) -> None:
    import_from_fsm_files(
        logpass_path=FIXTURE_LOGPASS,
        mafiles_dir=FIXTURE_MAFILES,
    )
    results = import_from_fsm_files(
        logpass_path=FIXTURE_LOGPASS,
        mafiles_dir=FIXTURE_MAFILES,
    )
    assert sum(1 for r in results if r.status == "updated") >= 2
    assert len(list_accounts()) == 2


def test_login_without_mafile_skipped(data_dir) -> None:
    results = import_from_fsm_files(
        logpass_path=FIXTURE_LOGPASS,
        mafiles_dir=FIXTURE_MAFILES,
    )
    row = next(r for r in results if r.login == "no_mafile")
    assert row.status == "skipped"
    assert len(list_accounts()) == 2


def test_dry_run_does_not_write_vault(data_dir) -> None:
    import_from_fsm_files(
        logpass_path=FIXTURE_LOGPASS,
        mafiles_dir=FIXTURE_MAFILES,
        dry_run=True,
    )
    assert not get_vault_enc_path().exists()


def test_cli_import_fsm(data_dir, capsys) -> None:
    code = vault_main(
        [
            "import-fsm",
            "--logpass",
            str(FIXTURE_LOGPASS),
            "--mafiles-dir",
            str(FIXTURE_MAFILES),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "added" in out
    assert len(list_accounts()) == 2


def test_upsert_updates_password(data_dir) -> None:
    add_account(
        login="acc_one",
        password="old",
        mafile_path=FIXTURE_MA_ONE,
    )
    upsert_account(
        login="acc_one",
        password="new_pass",
        mafile_path=FIXTURE_MA_ONE,
        update_existing=True,
    )
    from modules.vault.store import load_account

    acc = load_account("acc_one")
    assert acc["password"] == "new_pass"


def test_add_duplicate_still_raises(data_dir) -> None:
    add_account(login="acc_one", password="p", mafile_path=FIXTURE_MA_ONE)
    with pytest.raises(AccountExistsError):
        add_account(login="acc_one", password="p2", mafile_path=FIXTURE_MA_ONE)


def test_is_import_staging_empty_template_only(data_dir) -> None:
    ensure_config()
    assert is_import_staging_empty() is True


def test_main_vault_cli_import_fsm(data_dir) -> None:
    from main import main

    code = main(
        [
            "--vault-cli",
            "import-fsm",
            "--logpass",
            str(FIXTURE_LOGPASS),
            "--mafiles-dir",
            str(FIXTURE_MAFILES),
        ]
    )
    assert code == 0
    assert len(list_accounts()) == 2
