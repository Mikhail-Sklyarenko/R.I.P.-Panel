# Phase 02 protocol

`PROTOCOL_VERSION` is 3. Protocol 2 is rejected with HTTP 200, `ok: false`, `error: protocol_mismatch`, and an empty command list. Those agents are not READY. Upgrade the coordinator first, then each agent. A mixed fleet cannot start.

Assignment commands are additive on the existing `POST /v1/heartbeat` outbox:

- `prepare_assignment`
- `commit_assignment`
- `release_assignment`
- `verify_assignment`
- `reconcile_assignment`

Each command carries `command_id`, `run_id` (the preparation id when no gameplay run exists), `agent_id`, `params`, and `deadline_sec`. Params include `preparation_id`, `generation`, and the public account ids. The same command id is inserted with `INSERT OR IGNORE`, so a retry does not create a second command.

The heartbeat body may include `catalog` (public snapshot) and `agent_token`. The shared fleet token is still required. If that agent has a row in `agent_credentials`, the agent token must match too. A token registered for one agent does not authenticate another.

Results for these commands are stored against the preparation id even when no gameplay run is active. A failed or missing result does not move the group to READY. READY is a coordinator state after four committed slots and four fresh matching identity observations. It does not mean CS2 is running.

Real LAN transport is HTTP without TLS. `FleetHost.status()` reports `lan_ready: false`. Do not put the fleet token in a URL.
