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
