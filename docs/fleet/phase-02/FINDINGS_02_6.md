# Phase 02.6 findings

Baseline before these changes: commit `b795e4d93d544f9072a15a09992cd48ee46b84a6`, branch `feature/fleet-account-manager-v2`. The profile pytest command reported `115 passed`. That run was repeated on this machine before the fixes.

## Confirmed and fixed

### False READY from a non-fresh match

- Place: `AssignmentBook.note_identity` and `_slot_proven` in `core/wingman_fleet/assignments.py`.
- Reproduction: four matching SteamID64 values with `fresh=False` used to store `identity_observed` and `identity_at`. `_refresh_ready` only compared the id and the age.
- Cause: freshness was a local argument and was not stored as a verification status.
- Fix: each slot stores `verification_status`, `verification_source`, `verification_generation`, `verification_boot_id`, `verification_id`, `verification_seq`, and `link_state`. READY requires `verified`, source `steam_local` or `gsi`, the current generation, age `0 <= now - identity_at <= ttl`, and a healthy link when links are supplied. `fresh=False`, `manual`, and `loginusers` stay `unverified`.
- Test: `tests/test_fleet_acceptance.py::test_fresh_false_match_is_not_ready`, `test_manual_source_and_mismatch_block_ready`, `test_four_fresh_gsi_matches_are_ready_until_link_or_clock_breaks`.
- Result: those tests pass.
- Remaining risk: a live Steam client was not probed. The whitelist is enforced on the stored source string.

### VERIFY trusted the coordinator's observed id

- Place: assignment command params and `AgentService._apply_assignment`.
- Reproduction: a coordinator could put `observed_steam_id64` in the VERIFY params.
- Cause: the measurement boundary was on the wrong side of the network.
- Fix: `enqueue(..., "verify")` sends a new `verification_id` and does not send an observed id. The agent calls `identity_probe` or `WindowsBackend.verify_active_identity`. The fold reads `result.evidence` and the coordinator clock.
- Test: `tests/test_fleet_phase026.py::test_verify_uses_the_agent_probe_not_the_coordinator_hint` and `test_four_simulated_agents_commit_and_freeze_a_run_plan`.
- Remaining risk: GSI versus local Steam disagreement is a mismatch only when the probe reports it. There is no second live reader in the simulator.

### RunPlan could follow the roster instead of the book

- Place: `FleetHost.start_run`.
- Reproduction: the UI checked `current_ready()` and the host then built a plan from `FleetRoster`.
- Cause: two sources of truth.
- Fix: production `start_run` calls `AssignmentBook.build_run_plan`, which freezes the committed slots inside one transaction and projects the roster. `account_id` is `{agent_id}:{local_account_id}`. There is no skip flag. `Coordinator.start_run` remains the isolated FSM entry used by older gameplay tests.
- Test: `tests/test_fleet_acceptance.py::test_run_plan_is_frozen_from_the_assignment`.
- Remaining risk: a test that calls `Coordinator.start_run` directly still does not consult the book. The panel path does.

### Result fold could acknowledge a change that rolled back

- Place: `Coordinator.handle_heartbeat`.
- Reproduction: recording the terminal result and folding the book were separate. An exception after the write could still be treated as done on the next delivery.
- Cause: the two writes were not one `BEGIN IMMEDIATE`.
- Fix: assignment results call `record_result` and `_fold_assignment_result` inside `store.transaction()`. `AssignmentBook._tx` joins that transaction instead of opening another. An `OperationalError` rolls both back and the command stays pending. A logical reject of a missing preparation still rolls back, so it is not acknowledged.
- Test: `tests/test_fleet_phase026.py::test_result_crash_does_not_ack_and_retry_applies_once` and `tests/test_fleet_integration.py::test_coordinator_accepts_assignment_result_without_an_active_run`.
- Remaining risk: a logical `AssignmentError` after a partial slot write would roll the result back too. The current rejects raise before they write.

### Direct release

- Place: `AssignmentBook.release`.
- Reproduction: one coordinator call marked four slots released while agents could still hold reservations.
- Fix: `release()` raises. The operator path is `begin_release`, enqueue `RELEASE`, then `note_release` per agent. A mismatched generation is ignored and does not free the slot. An unknown catalog reservation raises.
- Test: `tests/test_fleet_assignments.py::test_prepare_commit_and_release_are_idempotent_and_fenced` and `tests/test_fleet_phase026.py::test_late_release_and_restart_do_not_invent_a_new_run`.

### Catalog revision used the maximum account row

- Place: `AccountCatalog.revision` versus `prepare`.
- Cause: the global figure was `MAX(catalog_revision)` while prepare compared one account.
- Fix: `meta.catalog_generation` increases on add, remove, bind, enable, and vault-presence changes. Prepare compares that account's `catalog_revision`. `remember_catalog` ignores an older generation or an older sequence.
- Test: `tests/test_fleet_phase026.py::test_catalog_generation_is_not_the_max_account_revision` and `test_stale_snapshot_and_empty_catalog_keep_their_head`.

### Revoked agent fell back to the shared token

- Place: `Coordinator.handle_heartbeat` when `has_credential` was false.
- Cause: revocation deleted the credential check instead of recording `REVOKED`.
- Fix: `registration_state` is `unregistered`, `registered`, or `revoked`. `authorize` rejects the last two failure cases. Production `FleetHost` always attaches the book, so an unregistered heartbeat is 403. There is no shared-token fallback.
- Test: `tests/test_fleet_acceptance.py::test_revoked_agent_cannot_fall_back_to_the_shared_token` and `tests/test_fleet_phase026.py::test_revoked_registration_has_no_shared_token_path_and_unregistered_is_rejected`.
- Remaining risk: a `Coordinator` constructed without an assignment book still accepts the shared token. That is the old FSM test harness, not `FleetHost`.

### Vault index was not checked against the vault

- Place: `FleetHost.start_agent` called `sync_index_payload` with the index only.
- Fix: `vault_login_names()` returns logins and a code (`ok`, `missing`, `bad_key`, `corrupt`, `unreadable`). Secrets are not returned. The catalog records the diagnostic and does not delete rows. `vault_present` marks an index login that has no vault record. SQLite migration backup uses the backup API.
- Test: `tests/test_fleet_phase026.py::test_vault_diagnostics_do_not_return_secrets` and `tests/test_fleet_catalog.py::test_migration_is_repeatable`.

### Gameplay cancel could be confused with assignment lifetime

- Place: `AgentService._accept`.
- Fix: assignment commands run even when the gameplay cancel flag is set and `run_id` is empty. They still fail when the service is stopped or fail-closed. They do not call `backend.execute` and do not clear SAFE_STOP.
- Test: `tests/test_fleet_acceptance.py::test_assignment_survives_a_cancelled_gameplay_context`.

## Transport and UI

- Cleartext HTTP on a non-loopback bind raises. `SECURE_LAN` requires a certificate, a key, and a CA. `HttpTransport` uses `ssl.create_default_context` and refuses HTTPS without a CA file. `verify=False` is not a setting.
- `lan_ready` is true only for that configuration with four registered agents. `four_pc_proven` is always false.
- Tests: `test_cleartext_lan_is_refused_and_lan_ready_is_only_configuration`, `test_https_accepts_a_trusted_certificate_and_rejects_a_bad_one`, `test_https_wrong_name_and_expired_certificate_fail`, `test_identity_assignment_does_not_mark_verified_or_four_pc`.
- The Wingman tab has four account menus, no fallback to the first account, and local SQLite actions for enroll, revoke, verify, reconcile, and diagnostics. Claiming a code stores the agent token with DPAPI and does not write the token to the log.
- Remaining risk: the CustomTkinter window was not click-tested. Enrollment over localhost HTTP is allowed only for `127.0.0.1` and `localhost`. A real LAN still needs `SECURE_LAN` and has not been run on four computers.

## Not reproduced as a separate failing test

The full pytest run, excluding `tests/test_csgobot*.py` which do not collect, was `11 failed, 938 passed, 3 skipped` on the tree before the last vault and UI edits. Those 11 failures are combat mode, menu wait, mouse mock, nav goal, orchestrator idle, path-picker monkeypatch, window width, and a missing `tools.replay_wingman`. They are outside the assignment path. They were not "fixed" and they are not counted as Phase 02.6 passes.

No hypothesis in the assignment list was disproved. The false READY path, the shared-token fallback for a revoked agent, and the split result write were all visible in the code and are now covered by tests that fail on the old behavior.
