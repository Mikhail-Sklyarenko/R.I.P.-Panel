# Phase 02.6 acceptance

Branch `fix/fleet-phase02-acceptance`. Simulation uses four `AgentService` processes in one test, synthetic SteamID64 values, and no Steam or CS2 launch.

Profile command after the changes:

```text
.venv\Scripts\python.exe -m pytest -q tests/test_fleet_integration.py tests/test_fleet_assignments.py tests/test_fleet_catalog.py tests/test_fleet_reliability.py tests/test_fleet_acceptance.py tests/test_fleet_phase026.py tests/test_wingman_fleet_foundation.py tests/test_wingman_fleet_agents.py tests/test_wingman_fleet_fsm.py tests/test_wingman_fleet_safety.py tests/test_wingman_fleet_observe.py tests/test_panel_controller.py --tb=line
```

Last completed result of that command before the two extra tests in `test_fleet_phase026.py`: `134 passed`. Those two tests then passed inside `tests/test_fleet_phase026.py` (`13 passed`). Re-run the profile before calling the number final if the tree has moved.

`four_pc_proven` is false. `lan_ready` does not mean a four-PC trial.

## Invariants

| Id | Statement | Test |
| --- | --- | --- |
| A01 | Secrets stay local | `tests/test_fleet_phase026.py::test_vault_diagnostics_do_not_return_secrets`, `tests/test_fleet_catalog.py::test_sync_keeps_stable_ids_and_reports_divergence` |
| A02 | One computer, one open assignment | `tests/test_fleet_catalog.py::test_prepare_commit_release_are_idempotent`, `tests/test_fleet_assignments.py::test_duplicate_steam_agent_and_offline_are_rejected` |
| A03 | One SteamID64 in the fleet | `tests/test_fleet_assignments.py::test_duplicate_steam_agent_and_offline_are_rejected` |
| A04 | A manual SteamID64 is not VERIFIED | `tests/test_fleet_acceptance.py::test_manual_source_and_mismatch_block_ready`, `tests/test_fleet_catalog.py::test_bind_is_not_verification_and_blocks_duplicates` |
| A05 | `fresh=False` is never READY | `tests/test_fleet_acceptance.py::test_fresh_false_match_is_not_ready` |
| A06 | An older VERIFY does not become READY | `tests/test_fleet_acceptance.py::test_four_fresh_gsi_matches_are_ready_until_link_or_clock_breaks` |
| A07 | READY drops when the proof is no longer current | same test (clock rollback, suspect link, new boot) |
| A08 | A missing agent is not HEALTHY | `tests/test_fleet_assignments.py::test_duplicate_steam_agent_and_offline_are_rejected`, `tests/test_fleet_phase026.py::test_one_offline_agent_blocks_ready_and_a_foreign_result_is_ignored` |
| A09 | Prepare needs the account revision that is current | `tests/test_fleet_assignments.py::test_stale_catalog_and_active_run_block_changes`, `tests/test_fleet_phase026.py::test_catalog_generation_is_not_the_max_account_revision` |
| A10 | All four PREPARE results are required | `tests/test_fleet_acceptance.py::test_four_simulated_agents_commit_and_freeze_a_run_plan` |
| A11 | All four COMMIT results are required | `tests/test_fleet_assignments.py::test_four_assignments_commit_only_after_every_agent` |
| A12 | A lost ACK is not success | `tests/test_fleet_phase026.py::test_result_crash_does_not_ack_and_retry_applies_once` |
| A13 | The commit decision survives restart | `tests/test_fleet_assignments.py::test_commit_decision_survives_restart_without_acks`, `tests/test_fleet_phase026.py::test_late_release_and_restart_do_not_invent_a_new_run` |
| A14 | An old generation does not change the new assignment | `tests/test_fleet_assignments.py::test_prepare_commit_and_release_are_idempotent_and_fenced`, `tests/test_fleet_phase026.py::test_late_release_and_restart_do_not_invent_a_new_run` |
| A15 | The same preparation id cannot switch account | `tests/test_fleet_phase026.py::test_catalog_generation_is_not_the_max_account_revision` |
| A16 | The same preparation id cannot switch run id | `tests/test_fleet_catalog.py::test_prepare_commit_release_are_idempotent`, `tests/test_fleet_phase026.py::test_late_release_and_restart_do_not_invent_a_new_run` |
| A17 | Release waits for the agents | `tests/test_fleet_assignments.py::test_prepare_commit_and_release_are_idempotent_and_fenced` |
| A18 | Unknown is not released | `tests/test_fleet_catalog.py::test_prepare_commit_release_are_idempotent` |
| A19 | The result and the transition commit together | `tests/test_fleet_phase026.py::test_result_crash_does_not_ack_and_retry_applies_once` |
| A20 | A revoked agent is rejected | `tests/test_fleet_acceptance.py::test_revoked_agent_cannot_fall_back_to_the_shared_token` |
| A21 | An unregistered agent gets no production heartbeat | `tests/test_fleet_phase026.py::test_revoked_registration_has_no_shared_token_path_and_unregistered_is_rejected` |
| A22 | An agent cannot complete another agent's command | `tests/test_fleet_phase026.py::test_one_offline_agent_blocks_ready_and_a_foreign_result_is_ignored` |
| A23 | Operator routes are not agent routes | `core/wingman_fleet/server.py` `POST /v1/operator` checks the fleet token; `POST /v1/enroll` checks the one-time code. Heartbeats check the agent token via `authorize`. |
| A24 | SECURE_LAN does not accept cleartext | `tests/test_fleet_phase026.py::test_cleartext_lan_is_refused_and_lan_ready_is_only_configuration`, `tests/test_fleet_acceptance.py::test_https_accepts_a_trusted_certificate_and_rejects_a_bad_one` |
| A25 | The observed SteamID64 is measured on that agent | `tests/test_fleet_phase026.py::test_verify_uses_the_agent_probe_not_the_coordinator_hint` |
| A26 | WindowsBackend uses the committed expected id and does not call it verified | `tests/test_fleet_phase026.py::test_identity_assignment_does_not_mark_verified_or_four_pc` |
| A27 | RunPlan matches the four confirmed accounts | `tests/test_fleet_acceptance.py::test_run_plan_is_frozen_from_the_assignment`, `test_four_simulated_agents_commit_and_freeze_a_run_plan` |
| A28 | A later catalog edit does not change the frozen plan | `tests/test_fleet_acceptance.py::test_run_plan_is_frozen_from_the_assignment` |
| A29 | Production start goes through the book | `FleetHost.start_run` calls `build_run_plan`; the same test refuses an offline link |
| A30 | An empty gameplay run does not block PREPARE after cancel | `tests/test_fleet_acceptance.py::test_assignment_survives_a_cancelled_gameplay_context` |
| A31 | SAFE_STOP still latches and survives restart | `tests/test_fleet_reliability.py::test_operator_stop_survives_coordinator_restart_before_any_lease`, `test_agent_stop_latch_survives_process_restart` |
| A32 | A green simulation is not a four-PC proof | `tests/test_fleet_phase026.py::test_identity_assignment_does_not_mark_verified_or_four_pc` |

A23 is enforced by the server routes and by the authorize tests. There is no separate test that an agent token calls `/v1/operator`.

## Status

```text
SIMULATION_ACCEPTANCE      PASSED
WINDOWS_LOCAL_ACCEPTANCE   BLOCKED
FOUR_PC_LAN_ACCEPTANCE     BLOCKED
```

`WINDOWS_LOCAL_ACCEPTANCE` is blocked because the Wingman tab was not clicked through and Steam was not running. The pytest process itself ran on this Windows 10 machine. `FOUR_PC_LAN_ACCEPTANCE` is blocked because no four-computer trial was run. A localhost HTTPS test does not change that.
