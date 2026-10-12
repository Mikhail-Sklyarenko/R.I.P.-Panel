# Catalog acceptance

Branch `fix/fleet-phase02-catalog-ui-lan-acceptance`, from `5418eaca345de00547e5ef662e442f5824a4fb28`. Protocol stays 4. Coordinator schema stays at `user_version` 5. This did not start Phase 03.

## Defects

| Id | Defect | Cause | Fix | Test |
|---|---|---|---|---|
| A1 | After v4→v5, `catalog_heads.registration_generation=0` treated generation 150 as the current registration, so a valid generation 1 snapshot was ignored | `new_registration` required a non-zero stored registration | An inherited head (`registration_generation=0`) is not a current catalog. The first snapshot from the live registration may start at generation 1. Monotonicity inside a known registration is unchanged | `tests/test_fleet_catalog_acceptance.py::test_v4_head_does_not_block_the_current_registration_catalog` |
| A2 | A fresh-by-time catalog from a previous registration could still be chosen and prepared | `_require_present` did not compare `catalog_heads.registration_generation` with `agent_credentials.registration_generation` | `catalog_usable()` is required for choose, draft, and prepare. The dropdown omits stale and disabled rows. Diagnostics may still list them as `устаревший снимок` | `test_previous_registration_catalog_cannot_be_selected_or_prepared` |

The operator message is:

`Каталог этого компьютера устарел. Дождитесь нового подключения агента.`

## Migration v4 → v5

A fixture builds a real schema-4 file: no `last_sequence`, no `catalog_heads.registration_generation`, `PRAGMA user_version=4`, plus credentials, presence, catalog generation 150, a committed reservation, a pending command, and `operator_stops`.

Opening `AssignmentBook` adds the missing columns, keeps those rows, and sets `user_version` to 5. A second open is a no-op. `user_version=6` refuses to open. SQLite `backup()` of the migrated file reads back with `integrity_check=ok`. User databases are not deleted.

PREPARE is forbidden until a snapshot of the current registration replaces the inherited head. Wrong `boot_id` or `process_generation` still cannot replace it. A committed reservation from the old file is not deleted automatically.

## Selection

- Previous registration, still fresh by `received_at` → not assignable.
- New registration without a new snapshot → not assignable.
- New valid snapshot → assignable.
- Registration change between choose and PREPARE → error, no silent substitute account.
- Unknown `local_account_id` → error, no substitute.
- Agent A's catalog cannot be chosen for agent B.
- Disabled accounts are omitted from the dropdown.
- An empty new catalog does not revive old cache rows.
- Re-enrollment keeps COMMITTED and does not restore READY.
