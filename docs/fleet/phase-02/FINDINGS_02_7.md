# Phase 02.7 findings

Branch `fix/fleet-phase02-final-hardening`, started from `1807d697fb12f08d9e512620a98a77d662b2e4dd`. This is a corrective pass on Phase 02. It does not add a new architecture and it does not start Phase 03.

Profile after the fixes: `146 passed`. The command is the 02.6 profile plus `tests/test_fleet_phase027.py`. `four_pc_proven` stays false. Localhost HTTPS is not a LAN trial. No Steam, CS2, or gameplay process is started.

| # | Defect | Cause | Fix | Test |
| --- | --- | --- | --- | --- |
| 1 | One fleet token authorized agents and `/v1/operator` | `GET /v1/status` and `POST /v1/operator` compared the header with `coordinator.token` | Distinct `operator_token`. Those routes read `X-Operator-Token` or `Bearer` only. Heartbeat still needs the fleet token plus a registered agent token. Enrollment stays a one-time code. The operator secret is DPAPI-stored and is not returned or logged | `tests/test_fleet_phase027.py::test_operator_authority_is_not_granted_by_agent_or_fleet_tokens` |
| 2 | A second thread could join an open SQLite transaction | `AssignmentBook._tx` yielded the shared connection when `in_transaction` was set, without taking the lock | `FleetStore.transaction` records the owner thread and depth. Nested calls on that thread join. Other threads wait. Nested calls do not commit or roll back | `test_transaction_owner_does_not_adopt_another_thread`, `test_heartbeat_and_revoke_do_not_deadlock` |
| 3 | A late VERIFY from the previous process restored READY | `note_boot` cleared the status but a later `note_identity` could write the old evidence again | Boot change clears status, sequence, verification id, and identity time. Evidence whose `boot_id` is not the current boot is ignored | `test_old_verify_after_restart_does_not_restore_ready` |
| 4 | Expected SteamID64 was applied only on the coordinator PC | `FleetHost.start_run` called `apply_identity_assignment` for the local backend. Agent COMMIT updated the catalog only | After a successful COMMIT, and only when no gameplay lease is held, the agent applies the expected id on its own backend. Restart restores it from the committed reservation. A lower generation does not replace it. Apply does not set verified | `test_commit_applies_expected_steam_without_verifying_it` |
| 5 | A new agent boot could not publish the same catalog generation | `remember_catalog` rejected a lower sequence even when `boot_id` changed | A different non-empty boot is accepted when the generation is not lower. The same boot still rejects a lower sequence. An empty boot id does not reset the fence | `test_new_boot_publishes_catalog_when_sequence_restarts` |
| 6 | An empty vault looked like an unread vault | `vault_logins or index_logins` treated `[]` as missing | `None` means unread and does not mark index rows absent. `[]` means a successful empty read. Rows are not deleted | `test_empty_vault_does_not_mark_index_accounts_present` |
| 7 | A missing agent still passed selection | The link check ignored a missing key, and `begin_prepare` passed `{}` | Every selected agent must be `healthy` in the supplied map and must be registered, on the current protocol, with a fresh heartbeat and a fresh catalog snapshot. A stale cache row may still be read. It does not authorize prepare | `test_prepare_requires_registered_fresh_agents` |
| 8 | `current_ready()` and `start_run` could disagree | Empty `link_state` counted as proven, and `current_ready()` did not read live presence | Both paths use registration, `agent_presence`, and the identity proof. OFFLINE and SUSPECT revoke READY even when the caller passes a healthy link map | `test_ready_follows_presence_not_a_caller_supplied_link_map` |

The restart lifecycle is `test_restarted_coordinator_and_agents_keep_the_committed_identity`: prepare, commit, verify, coordinator reopen, agent reboot, new verify, then `RunPlan`. The expected SteamID64 on each simulated backend matches the plan. `execute` is not called.

## Limits

- `SIMULATION_ACCEPTANCE` can be marked passed only for this simulated profile.
- `WINDOWS_LOCAL_ACCEPTANCE` stays blocked: the CustomTkinter window was not click-tested, and Steam was not running.
- `FOUR_PC_LAN_ACCEPTANCE` stays blocked. `four_pc_proven` is false.
