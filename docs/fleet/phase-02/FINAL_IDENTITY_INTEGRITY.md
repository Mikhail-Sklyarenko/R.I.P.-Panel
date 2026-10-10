# Identity integrity

Branch `fix/fleet-phase02-identity-integrity`, from `bb00bc038e70c463cf19b69e66c6288abe4ce5cc`. Protocol stays 4. Coordinator `PRAGMA user_version` moves from 4 to 5. This did not start Phase 03.

## Defects

| Id | Defect | Cause | Fix | Test |
|---|---|---|---|---|
| P0-A | Registry B and fresh GSI A, with expected A, became VERIFIED | `_measure_identity` rewrote `Identity.MISMATCH` to source `gsi` because the detail text contained `GSI`. The catalog compared ids only | The probe status is kept as `identity_status` through the agent, the local catalog, and the book. A conflict stays `mismatch` when one id equals the expected id | `test_registry_b_and_fresh_gsi_matching_expected_is_not_ready`, `test_identity_matrix_reaches_ready_only_for_a_single_fresh_source` |
| P0-B | `FAILED` with `fresh: true` and a matching id kept READY | The fold treated `fresh` as success and did not require `ResultStatus.COMPLETED`. A cancel could leave the local catalog VERIFIED | Positive proof requires COMPLETED plus a consistent `steam_local` or `gsi` proof. Other terminal results clear the proof. Cancel marks the local row unconfirmed. `ALREADY_APPLIED` does not create a proof. ACK means the result was stored | `test_terminal_status_gates_identity_and_a_replay_cannot_restore_ready`, `test_cancel_during_verify_clears_the_local_catalog_and_the_coordinator`, `test_already_applied_does_not_restore_ready` |
| P1-C | After a coordinator restart a lower heartbeat sequence was accepted | `observation.sequence` lived only in memory | `agent_presence.last_sequence` is updated in the same transaction as the session. Memory is updated after that commit. A store error returns `store_failed` and changes nothing | `test_heartbeat_sequence_survives_coordinator_restart`, `test_process_generation_restarts_sequence_and_a_store_failure_rolls_back`, `test_rejected_heartbeat_does_not_change_ready_catalog_or_commands` |
| P1-D | A new registration could not publish catalog generation 1, and the old READY survived | `catalog_heads` was not tied to `registration_generation`, and re-enrollment did not clear the identity proof | A new registration accepts its own generation sequence. The old registration's snapshots are ignored. Committed reservations stay, but they are not READY | `test_new_registration_accepts_a_lower_catalog_generation`, `test_registration_restart_empty_catalog_and_repeat_are_safe` |

The four-agent path is `test_four_agents_lose_ready_on_conflict_and_recover_only_after_fresh_proof`. It uses one coordinator and four `AgentService` processes, real heartbeats, and no gameplay `execute()`.

## Rules that now block VERIFIED

READY requires four COMMITTED slots and four fresh non-conflicting proofs for the current preparation, assignment generation, verification id, process generation, and boot. `mismatch`, `unconfirmed`, `manual`, and `loginusers` do not qualify. A later conflict or a newer unsuccessful VERIFY removes READY. An older COMPLETED result does not put it back. RunPlan reads that gate and is not built from a stale registration or an unconfirmed local account.

## Migration

Opening `AssignmentBook` adds `agent_presence.last_sequence` and `catalog_heads.registration_generation` when they are missing, then sets `user_version` to 5. Rows, unfinished commands, reservations, and `operator_stops` stay. The agent journal stays at `user_version` 2. A schema newer than this program refuses to open.

VERIFY evidence should include `identity_status`. Heartbeats that omit it still parse. A COMPLETED VERIFY without that field is not a proof. Update the coordinator and the four agents together.

## Tests

The fleet profile, including `tests/test_fleet_identity_integrity.py`, passed as `181 passed in 52.99s`. The profile on `bb00bc0` was `167 passed`. The new file is 14 tests.

The full suite excluding `tests/test_csgobot*.py` was `11 failed, 995 passed, 3 skipped` in 1061.60s. That process collected 13 of the 14 new tests. `test_already_applied_does_not_restore_ready` was added while it was running and then passed inside the 181 profile. The pass count is 13 above the Phase 02.8 count of 982. No new name failed.

The 11 failures outside fleet, from Phase 02.7 and 02.8, are not hidden and are not part of this patch:

- `tests/test_combat.py::test_resolve_mode_auto_without_csgobot`
- `tests/test_combat.py::test_auto_emits_fallback_when_ai_missing`
- `tests/test_cs2_main_menu_wait.py::test_dm_runner_logs_menu_probe_warn`
- `tests/test_dm_recovery.py::test_release_only_sends_keyups_without_stealing_focus`
- `tests/test_nav_farm_runtime.py::test_real_controller_yields_keys_and_mouse_to_combat`
- `tests/test_orchestrator.py::test_orchestrator_two_accounts_sequential_done`
- `tests/test_path_picker.py::test_pick_steam_path_updates_config`
- `tests/test_path_picker.py::test_pick_cancel_does_not_change_config`
- `tests/test_path_picker.py::test_pick_invalid_basename_not_saved`
- `tests/test_utils.py::test_list_and_move_cs_windows_sim`
- `tests/test_wingman.py::test_complete_synthetic_cycle`

## Remaining limits

`SIMULATION_ACCEPTANCE` can be recorded only after the new tests and the four-agent simulation pass. `WINDOWS_LOCAL_ACCEPTANCE` was not a CustomTkinter click-through. `FOUR_PC_LAN_ACCEPTANCE` was not run. `four_pc_proven` stays false. No Steam client and no CS2 process were started.
