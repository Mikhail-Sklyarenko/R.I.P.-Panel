# Phase 02 protocol

`PROTOCOL_VERSION` is 3. Protocol 2 is rejected with HTTP 200, `ok: false`, `error: protocol_mismatch`, and an empty command list. Those agents are not READY. Upgrade the coordinator first, then each agent. A mixed fleet cannot start.

Assignment commands are additive on the existing `POST /v1/heartbeat` outbox:

- `prepare_assignment`
- `commit_assignment`
- `release_assignment`
- `verify_assignment`
- `reconcile_assignment`

Each command carries `command_id`, `run_id` (the preparation id when no gameplay run exists), `agent_id`, `params`, and `deadline_sec`. Params include `preparation_id`, `generation`, and the public account ids. The same command id is inserted with `INSERT OR IGNORE`, so a retry does not create a second command.

The heartbeat body may include `catalog` (public snapshot, plus a short `vault_status` code) and `agent_token`. The shared fleet token is still required. With an assignment book attached, the agent must also be `registered` and the agent token must match. A revoked row is rejected even when the shared token is correct. A token registered for one agent does not authenticate another. The operator token is not a fleet token and is not an agent token.

`GET /v1/status` and `POST /v1/operator` require the operator token. `POST /v1/enroll` accepts `agent_id` and a one-time `code`. It does not accept the fleet token, the operator token, or an agent token as a substitute. The response contains `agent_token` once.

A catalog snapshot is fenced by `catalog_generation`, then by `boot_id` and `sequence`. A lower generation is ignored. The same boot with a lower sequence is ignored. A different non-empty `boot_id` may publish the same generation even when its sequence restarted at 1. An empty `boot_id` does not reset that fence.

VERIFY params carry `verification_id`, `generation`, and the expected account ids. They do not carry the observed SteamID64. The agent measures that and returns it in `evidence`, including the measuring process's `boot_id`. The coordinator stores the result with its own clock. A lower `verification_seq` does not replace a higher one. Evidence whose `boot_id` is not the agent's current boot is ignored, so a late result from the previous process cannot restore READY.

Results for these commands are stored against the preparation id even when no gameplay run is active. Recording the result and folding the book are one transaction. If that transaction raises, the result is not acknowledged. A failed or missing result does not move the group to READY. READY is calculated from the committed slots, the verification row, the age, registration, and `agent_presence`. A caller-supplied link map cannot keep an OFFLINE or SUSPECT agent READY. A stored status of `ready` is rewritten to `committed` when the proof no longer holds. It does not mean CS2 is running. Applying the expected SteamID64 on COMMIT is not verification.

`LOCALHOST_DEVELOPMENT` is HTTP on `127.0.0.1`. `SECURE_LAN` is HTTPS. `FleetHost.status()` reports `transport`, `lan_ready`, and `four_pc_proven`. Do not put the fleet token in a URL.
