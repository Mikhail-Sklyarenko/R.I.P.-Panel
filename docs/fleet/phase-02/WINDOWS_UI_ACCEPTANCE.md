# Windows UI acceptance

Environment: Windows 10 10.0.19045, 1280×720 at 100% scale (measured `GetScaleFactorForDevice=100`). Isolated profile via `FARM_PANEL_DATA_DIR`. Steam and CS2 were not started. `Рестарт CS2`, `Рестарт Steam`, and `Пересоздать лобби` were not pressed.

## Map

```text
Wingman tab
  → PanelView buttons (real CustomTkinter widgets)
  → PanelController.fleet_account_action / start_fleet_run / bind_local_steam / claim_agent
  → FleetDesk / FleetHost
  → AssignmentBook / Coordinator / AccountCatalog
```

Roster SteamID64 fields are not a local catalog bind. The new control `Привязать SteamID64` calls `AccountCatalog.bind()`.

## What the real window did

`tests/test_fleet_windows_ui.py::test_wingman_click_through_prepare_gate_and_window` opened `Farm Panel`, selected the Wingman tab, found the assignment buttons by their Russian labels, generated pointer events, and invoked them.

Clicked:

- `Подтвердить состав` before PREPARE
- `Проверить SteamID64` without an assignment
- `Подготовить 4 назначения` with no accounts chosen
- `Старт цикла` while not READY

`Старт цикла` stayed blocked. Screenshots: `docs/fleet/phase-02/evidence/wingman_*.png`. The token field uses `show="*"`. No operator or agent token is in the image files.

| Resolution | Scale | Status |
|---|---|---|
| 1280×720 | 100% | PASSED (this machine) |
| 1920×1080 | 100% | PASSED (resized window screenshot) |
| 1920×1080 | 125% | NOT_TESTED (OS scale was not changed) |
| 1366×768 | 100% | NOT_TESTED |
| 1280×720 | 125% | NOT_TESTED |

## Fixes in the panel

- `FleetDesk.rows()` uses `AssignmentBook.connection_state()` when no link map is passed, so cards are not stuck on OFFLINE.
- Presence labels: `ONLINE / HEALTHY`, `SUSPECT`, `OFFLINE`, `UNREGISTERED`, `REVOKED`, `PROTOCOL MISMATCH`.
- Stale catalogs are omitted from the account menu and shown in diagnostics as `устаревший снимок`.
- `FleetHost.claim_agent()` restarts the local `AgentService` after DPAPI enrollment so a process that was started with no token does not keep an unauthorized session.
- Local SteamID64 bind is a Wingman control, not a roster edit.
- Transport mode and TLS file paths are on the Wingman tab. SECURE_LAN refuses `http://` and missing cert/key/CA files. The private key is a path, not file contents.
- A PREPARE that fails after `draft()` discards an unstarted draft so the operator is not stuck.

## Four-agent assignment

The four-agent PREPARE → COMMIT → VERIFY → READY path with real handlers is `tests/test_fleet_identity_integrity.py::test_four_agents_lose_ready_on_conflict_and_recover_only_after_fresh_proof` and `tests/test_fleet_acceptance.py::test_four_simulated_agents_commit_and_freeze_a_run_plan`. Those agents are in-process, not four GUI processes. The window test did not fill four dropdowns and complete that path by clicks alone.
