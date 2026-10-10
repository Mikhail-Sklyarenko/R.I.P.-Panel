"""Local account catalog: bindings, vault sync, and secret-free snapshots."""
from __future__ import annotations

import json

import pytest

from core.wingman_fleet.accounts import BindingStatus, CatalogError, parse_steam_id64
from modules.fleet_accounts.catalog import AccountCatalog

SID = "76561197960265729"
OTHER = "76561197960265730"


def _catalog(tmp_path, logins=("alpha", "beta")) -> AccountCatalog:
    catalog = AccountCatalog(tmp_path / "catalog.db", agent_id="pc1")
    catalog.sync_logins(list(logins), list(logins))
    return catalog


def test_steam_id64_range():
    assert parse_steam_id64(SID) == SID
    with pytest.raises(CatalogError):
        parse_steam_id64("123")
    with pytest.raises(CatalogError):
        parse_steam_id64(str(76561197960265728))


def test_sync_keeps_stable_ids_and_reports_divergence(tmp_path):
    catalog = _catalog(tmp_path)
    first = catalog.by_login("Alpha")
    catalog.sync_logins(["alpha", "alpha", "gamma"], ["alpha"])
    assert catalog.by_login("alpha")["local_account_id"] == first["local_account_id"]
    issues = dict(catalog.issues())
    assert issues["alpha"] == "duplicate_login" or any(item[1] == "duplicate_login" for item in catalog.issues())
    assert any(issue == "vault_without_index" or issue == "index_without_vault" for _, issue in catalog.issues())
    with pytest.raises(CatalogError):
        catalog.sync_index_payload("{")
    assert catalog.by_login("alpha") is not None
    catalog.close()


def test_bind_is_not_verification_and_blocks_duplicates(tmp_path):
    catalog = _catalog(tmp_path)
    alpha = catalog.by_login("alpha")["local_account_id"]
    beta = catalog.by_login("beta")["local_account_id"]
    catalog.bind(alpha, SID)
    assert catalog.get(alpha)["binding_status"] == BindingStatus.MANUALLY_BOUND.value
    with pytest.raises(CatalogError):
        catalog.bind(beta, SID)
    with pytest.raises(CatalogError):
        catalog.bind(alpha, OTHER)
    catalog.bind(alpha, OTHER, confirm_rebind=True)
    assert catalog.history(alpha)[-1]["steam_id64"] == OTHER
    assert catalog.note_identity(alpha, OTHER, source="manual", now=10) == BindingStatus.UNCONFIRMED.value
    assert catalog.note_identity(alpha, OTHER, source="loginusers", now=10) == BindingStatus.UNCONFIRMED.value
    assert catalog.note_identity(alpha, SID, source="gsi", now=10) == BindingStatus.MISMATCH.value
    assert catalog.note_identity(alpha, OTHER, source="gsi", now=20) == BindingStatus.VERIFIED.value
    assert catalog.identity_fresh(alpha, 30) is True
    assert catalog.identity_fresh(alpha, 1000) is False
    snapshot = catalog.snapshot().as_dict()
    assert "login" not in json.dumps(snapshot)
    assert "password" not in json.dumps(snapshot)
    catalog.close()


def test_prepare_commit_release_are_idempotent(tmp_path):
    catalog = _catalog(tmp_path)
    alpha = catalog.by_login("alpha")
    catalog.bind(alpha["local_account_id"], SID)
    revision = catalog.get(alpha["local_account_id"])["catalog_revision"]
    assert catalog.prepare(
        preparation_id="prep-1", local_account_id=alpha["local_account_id"], steam_id64=SID,
        catalog_revision=revision, generation=1, coordinator_generation=1,
    ) == "prepared"
    assert catalog.prepare(
        preparation_id="prep-1", local_account_id=alpha["local_account_id"], steam_id64=SID,
        catalog_revision=revision, generation=1, coordinator_generation=1,
    ) == "prepared"
    with pytest.raises(CatalogError):
        catalog.prepare(
            preparation_id="prep-2", local_account_id=alpha["local_account_id"], steam_id64=SID,
            catalog_revision=revision, generation=1, coordinator_generation=1,
        )
    assert catalog.commit(preparation_id="prep-1", generation=1, run_id="run-1") == "committed"
    assert catalog.commit(preparation_id="prep-1", generation=1, run_id="run-1") == "committed"
    with pytest.raises(CatalogError):
        catalog.commit(preparation_id="prep-1", generation=2, run_id="run-1")
    with pytest.raises(CatalogError):
        catalog.commit(preparation_id="prep-1", generation=1, run_id="run-other")
    catalog.db.execute(
        "UPDATE reservations SET status='active' WHERE preparation_id='prep-1'"
    )
    with pytest.raises(CatalogError):
        catalog.release("prep-1")
    catalog.db.execute(
        "UPDATE reservations SET status='committed' WHERE preparation_id='prep-1'"
    )
    assert catalog.release("prep-1") == "released"
    assert catalog.release("prep-1") == "released"
    catalog.close()


def test_migration_is_repeatable(tmp_path):
    catalog = _catalog(tmp_path, ["one"])
    catalog.close()
    again = AccountCatalog(tmp_path / "catalog.db", agent_id="pc1")
    assert again.by_login("one") is not None
    again.close()
