# Phase 02.8 acceptance

Branch `fix/fleet-phase02-message-fencing`. Base `cce921064cb4871cc6a4ed10e59c9c5c1a1a20f0`. The profile on that commit, before these edits, was `146 passed`.

The reproducing file `tests/test_fleet_phase028.py` was run against that commit first: `4 failed, 1 passed`. The failures were equal VERIFY sequences, a duplicate terminal fold, a stale process accepted with HTTP 200, and `verify_active_identity` ignoring a fresh conflicting GSI. The passing test already rejected a strictly older sequence. It stays as a regression guard.

## Profile

```text
.venv\Scripts\python.exe -m pytest -q tests/test_fleet_integration.py tests/test_fleet_assignments.py tests/test_fleet_catalog.py tests/test_fleet_reliability.py tests/test_fleet_acceptance.py tests/test_fleet_phase026.py tests/test_fleet_phase027.py tests/test_fleet_phase028.py tests/test_wingman_fleet_foundation.py tests/test_wingman_fleet_agents.py tests/test_wingman_fleet_fsm.py tests/test_wingman_fleet_safety.py tests/test_wingman_fleet_observe.py tests/test_panel_controller.py --tb=line
```

Final tree: `167 passed in 48.49s`. That is the previous 146 plus the 21 tests in `tests/test_fleet_phase028.py`. No previous profile test was removed.

## Full suite

`pytest -q --ignore-glob=tests/test_csgobot*.py` on this tree: `11 failed, 982 passed, 3 skipped` in 857.23s.

The 02.7 full suite was `11 failed, 961 passed, 3 skipped`. The extra 21 passes are the new fencing tests. The same 11 failures remain, all outside fleet assignment:

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

`tests/test_csgobot*.py` still fails at collection (`FOVConfig` import) and was excluded, as before.

## Checklist

| Check | Result |
|---|---|
| Duplicate terminal VERIFY does not change the book | `test_duplicate_terminal_verify_does_not_apply_twice`, `test_concurrent_delivery_applies_a_terminal_result_once` |
| VERIFY sequence is durable and monotonic | `test_two_verifies_in_one_millisecond_get_distinct_sequences`, `test_verification_sequence_survives_restart_and_a_backward_clock` |
| `verification_id` must match the command | `test_forged_verification_id_and_old_generation_are_not_acked` |
| An older VERIFY does not restore READY | `test_verify_a_match_then_verify_b_mismatch_stays_mismatch`, `test_older_verify_cannot_restore_ready_after_a_newer_mismatch` |
| A stale process is rejected and does not touch catalog, presence, READY, VERIFY, or commands | `test_stale_process_cannot_replace_a_newer_session`, `test_stale_process_cannot_verify_or_receive_commands` |
| Generation survives coordinator restart | `test_generation_fence_survives_coordinator_restart` |
| Same generation and a different boot is `boot_conflict` | `test_same_generation_different_boot_is_a_conflict` |
| Fresh GSI is part of VERIFY; a Steam/GSI conflict is `MISMATCH` | `test_verify_uses_the_same_fresh_gsi_snapshot_as_observe`, `test_identity_sources_agree_or_the_probe_reports_mismatch` |
| Four simulated agents, then a stale process | `test_four_agents_reject_a_stale_message_after_a_new_process` |
| SAFE_STOP still survives restart | `tests/test_fleet_reliability.py` in the profile above |
| SQLite failure does not ACK | `test_sqlite_failure_during_fold_does_not_ack` |
| Lost ACK does not apply twice | the duplicate VERIFY test |
| No production switch disables fencing | no such flag in the diff |

`execute()` is not on the assignment path. The four-agent test uses a backend whose `execute` raises.

## Status

| Gate | Status |
|---|---|
| SIMULATION_ACCEPTANCE | PASSED |
| WINDOWS_LOCAL_ACCEPTANCE | BLOCKED |
| FOUR_PC_LAN_ACCEPTANCE | BLOCKED |

Windows local is blocked because the Wingman tab was not clicked through. Four-PC LAN is blocked because this machine is not four PCs. `four_pc_proven` stays false. Steam and CS2 were not started.
