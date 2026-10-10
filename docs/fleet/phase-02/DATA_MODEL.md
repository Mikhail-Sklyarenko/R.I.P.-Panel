# Phase 02 data model

## Local catalog (`data/fleet_catalog.db` on each PC)

Sidecar to `accounts.index.json`. The login is the join key and is not part of the coordinator snapshot. Passwords and maFile contents stay in `vault.enc`.

- `accounts`: `local_account_id` (stable hex id), `login` (NOCASE unique), `steam_id64`, `display_name`, `enabled`, `binding_status`, `availability_status`, `last_verified_at`, `last_verified_source`, `catalog_revision`, `vault_present`, `last_error`.
- `meta.catalog_generation` is the catalog-wide counter. It is not `MAX(catalog_revision)`. `catalog_revision` remains the per-account counter.
- Partial unique index `accounts_one_steam` on non-empty `steam_id64`.
- `binding_history` records previous and new SteamID64 and the source. No secrets.
- `sync_issues` records index/vault divergence. Rows are not deleted automatically. `vault_logins is None` means the vault was not read, so index logins stay present. `vault_logins == []` means the vault was read and is empty, so those index logins are marked absent and kept.
- `reservations` plus `active_reservation` (single row) enforce one open reservation per computer.
- `meta.schema_version` is 1. Opening an existing file again is a no-op. A newer schema than this program raises.

Binding and availability are separate columns. `manually_bound` is not `verified`.

## Coordinator (`FleetStore` SQLite)

Existing tables `runs`, `commands`, `events`, `friendships`, `agents` stay. New tables:

- `operator_requests(request_key)` and `operator_stops(run_id, agent_id)` from phase 02.0. One active run is enforced by `runs_one_active`.
- `preparations` and `preparation_slots`. Partial unique indexes `assignment_one_agent` and `assignment_one_steam` apply to statuses `prepared`, `committed`, `active`, `reconcile_required`.
- `assignment_events` is the transition log.
- `agent_credentials` stores a SHA-256 of a per-agent token, not the token, plus `registration_generation`.
- `agent_presence` stores `boot_id`, `protocol`, `last_seen`, `process_generation`, and `registration_generation`. It is the admitted session and the availability row used by draft, prepare, and READY. A catalog cache row can still be shown after it goes stale; it is not that proof.
- `verification_seq(preparation_id, agent_id, next_seq)` allocates VERIFY order. It is not a wall clock.
- `catalog_cache` stores the public snapshot fields only.
- `catalog_heads` keeps `boot_id` and `sequence`. Once `process_generation` is admitted, the snapshot must name that session. An empty boot id does not reset the fence.
- `PRAGMA user_version` is 4 after `AssignmentBook` opens the file. A higher version refuses to open. Opening twice does not drop rows.

`RunPlan` is still the immutable run snapshot in `runs.plan_json`. A preparation is not a run. `FleetRoster` JSON remains the slot layout and is not proof of READY.

## Agent journal

`agent_session` is one row: `run_id`, `stopped`, `generation`, `process_generation`, `registration_generation`. `generation` is still the SAFE_STOP / lease latch. `process_generation` is the process fence and is not reset by `save_session`. `PRAGMA user_version` is 2. A newer journal refuses to open. A negative or non-integer process counter fails closed. Interrupted `running` commands are still marked failed on open and are not replayed. An unacked result keeps the evidence it was finished with, including the old boot and process generation.
