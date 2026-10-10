# Phase 02 test report

Environment: Windows 10 (10.0.19045), Python 3.11.0, pytest 9.1.1, branch `feature/fleet-account-manager-v2`. No Steam account, maFile, or CS2 process was used.

Command:

```text
.venv\Scripts\python.exe -m pytest -q tests/test_fleet_integration.py tests/test_fleet_assignments.py tests/test_fleet_catalog.py tests/test_fleet_reliability.py tests/test_wingman_fleet_foundation.py tests/test_wingman_fleet_agents.py tests/test_wingman_fleet_fsm.py tests/test_wingman_fleet_safety.py tests/test_wingman_fleet_observe.py tests/test_panel_controller.py --tb=line
```

Result after the protocol 3 and UI wiring: `115 passed in 20.41s`. That figure is the Phase 02 baseline. Phase 02.6 added tests; see the section below.

The same six Phase 01 files were `92 passed` on commit `08de63c` before these changes. They are included in the 115.

Covered here:

- Operator SAFE_STOP and the active-run flag commit together. A SQLite `RAISE(ROLLBACK)` leaves no command and no stop.
- Agent SAFE_STOP restores from `agent_session`. A corrupt session fails closed. A late `set_gameplay` with an older generation does not replace a newer one.
- Catalog sync, duplicate SteamID64, rebind confirmation, manual bind is not verification, secret-free snapshot, idempotent prepare/commit/release.
- Four-slot draft, duplicate steam and agent, offline and suspect links, disabled and unbound accounts, stale revision, commit without ACKs after reopening the database, identity mismatch is not READY.
- Assignment command on the heartbeat with no gameplay run, wrong agent token rejected, protocol 2 receives no commands, desk validation failure does not report success.

Not run:

- CustomTkinter click-through. The desk model is tested without a window.
- Four physical computers.
- A live IdentityProbe against a running Steam client. Probe logic is covered by the existing identity tests and by catalog `note_identity` with synthetic ids.

## Phase 02.6

Branch `fix/fleet-phase02-acceptance`. The same profile plus `tests/test_fleet_acceptance.py` and `tests/test_fleet_phase026.py` passed as `136 passed in 25.32s`. Localhost HTTPS with an ephemeral certificate is included. `lan_ready` is computed from the SECURE_LAN configuration and is not a four-PC result. `four_pc_proven` stays false.

The full suite excluding `tests/test_csgobot*.py` (those files fail at import) was `11 failed, 938 passed, 3 skipped` on the tree before the last documentation pass. The 11 failures are outside the fleet assignment modules: combat mode selection, menu-wait logging, a mouse mock, nav goal id, orchestrator idle, path-picker monkeypatch, simulated window width, and a missing `tools.replay_wingman`. They are not treated as fleet passes.

## Phase 02.7

Branch `fix/fleet-phase02-final-hardening`. The 02.6 profile plus `tests/test_fleet_phase027.py` passed as `146 passed in 27.82s`. The eight audit findings and the restart lifecycle are in `FINDINGS_02_7.md`. `four_pc_proven` stays false.

The full suite excluding `tests/test_csgobot*.py` was `11 failed, 961 passed, 3 skipped` in 489.78s. The pass count is higher than the 02.6 intermediate `938` because the fleet tests were added. The same 11 failures remain, all outside fleet assignment:

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

CustomTkinter created a withdrawn window on a 1920x1080 display. The Wingman tab buttons were not clicked, and Steam was not started.

## Phase 02.8

Branch `fix/fleet-phase02-message-fencing`. The 02.7 profile plus `tests/test_fleet_phase028.py` passed as `167 passed in 48.49s`. The base profile on `cce9210` was `146 passed`. The new file is 21 tests. See `ACCEPTANCE_02_8.md` and `FINDINGS_02_8.md`.

The full suite excluding `tests/test_csgobot*.py` was `11 failed, 982 passed, 3 skipped` in 857.23s. The same 11 names as Phase 02.7 failed. The pass count rose by 21, which is the new fencing file. `four_pc_proven` stays false.

## Identity integrity

Branch `fix/fleet-phase02-identity-integrity`. The 02.8 profile plus `tests/test_fleet_identity_integrity.py` passed as `181 passed in 52.99s`. The 02.8 profile on `bb00bc0` was `167 passed`. The new file is 14 tests. See `FINAL_IDENTITY_INTEGRITY.md`.

The full suite excluding `tests/test_csgobot*.py` was `11 failed, 995 passed, 3 skipped` in 1061.60s. It collected 13 of the 14 new tests; `test_already_applied_does_not_restore_ready` was added while that process was running and passed in the 181 profile above. The same 11 names as Phase 02.8 failed. No new failure appeared outside that list. `four_pc_proven` stays false. Windows UI and four physical PCs were not run.
