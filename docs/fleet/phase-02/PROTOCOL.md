# Phase 02 protocol

`PROTOCOL_VERSION` is 4. Protocol 3 and protocol 2 are rejected with HTTP 200, `ok: false`, `error: protocol_mismatch`, an empty command list, and no stored results. Those agents are not READY. Upgrade the coordinator first, then each agent. A mixed fleet cannot start. See `MESSAGE_FENCING.md`.

Assignment commands are additive on the existing `POST /v1/heartbeat` outbox:

- `prepare_assignment`
- `commit_assignment`
- `release_assignment`
- `verify_assignment`
- `reconcile_assignment`

Each command carries `command_id`, `run_id` (the preparation id when no gameplay run exists), `agent_id`, `params`, and `deadline_sec`. Params include `preparation_id`, `generation`, and the public account ids. The same command id is inserted with `INSERT OR IGNORE`, so a retry does not create a second command.

The heartbeat body may include `catalog` (public snapshot, plus a short `vault_status` code) and `agent_token`. The shared fleet token is still required. With an assignment book attached, the agent must also be `registered` and the agent token must match. A revoked row is rejected even when the shared token is correct. A token registered for one agent does not authenticate another. The operator token is not a fleet token and is not an agent token.

`GET /v1/status` and `POST /v1/operator` require the operator token. `POST /v1/enroll` accepts `agent_id` and a one-time `code`. It does not accept the fleet token, the operator token, or an agent token as a substitute. The response contains `agent_token` and `registration_generation` once.

A heartbeat that has a book must also carry `process_generation` and `registration_generation`. The admission rules are in `MESSAGE_FENCING.md`. They run before catalog, presence, and results.

A catalog snapshot is fenced by `registration_generation`, then by `catalog_generation`, then by the admitted `process_generation` and `boot_id` once a session exists, then by `sequence`. Inside one registration a lower catalog generation is ignored. A confirmed new registration is a new catalog context and may start again at generation 1. A snapshot that names the previous registration is ignored. A rejected re-registration does not delete the current catalog. An ordinary process restart, a network loss, or a new `boot_id` does not reset that registration context. Before any process generation is admitted, a different non-empty `boot_id` may publish the same catalog generation. After admission, a snapshot from another boot or another generation is ignored. An empty `boot_id` does not reset that fence.

The last accepted heartbeat `sequence` for the admitted registration, process generation, and `boot_id` is stored in `agent_presence.last_sequence`. The same session rejects a sequence that is not strictly greater, including after the coordinator process restarts. A strictly higher `process_generation` may start again at 1. A new registration clears the stored sequence with the old boot and process generation. Session, sequence, and the catalog snapshot commit before the in-memory link is updated. A SQLite error returns `store_failed`, acknowledges nothing, and leaves memory unchanged. A rejected heartbeat does not change READY, the catalog, or the command list.

VERIFY params carry `verification_id`, `verification_sequence` (`seq`), `generation`, and the expected account ids. They do not carry the observed SteamID64. The agent measures that and returns it in `evidence`, including `identity_status`, the measuring process's `boot_id`, and `process_generation`. `identity_status` is the IdentityProbe result (`steam_local`, `gsi`, `mismatch`, or `unconfirmed`). It is not inferred from `detail`, and `source` is not a substitute for it. `fresh: true` means a current measurement happened. It does not mean the identity matched. Protocol stays 4 because the field is additive and an old heartbeat still parses. A COMPLETED VERIFY that omits `identity_status` is not a proof and does not leave READY in place. Update the coordinator and the four agents together before the next VERIFY.

The sequence is allocated in SQLite and is not `clock * 1000`. A lower or equal positive sequence does not replace the stored one. Evidence whose boot or process generation is not the admitted session is not applied. A repeated terminal body is acknowledged once it is already stored. A different body for the same command id is a conflict and is not acknowledged.

Positive proof requires `ResultStatus.COMPLETED` together with `identity_status` of `steam_local` or `gsi`, evidence `status` `verified`, `fresh` exactly true, an allowed source, and an observed SteamID64 equal to the expected one. `FAILED`, `REJECTED`, `EXPIRED`, `UNCONFIRMED`, and `ACCEPTED` do not confirm an identity. `ALREADY_APPLIED` does not create a new proof. A newer unsuccessful VERIFY removes READY. Acknowledging a stored result only means the result was saved. An older COMPLETED result does not restore READY after that. If VERIFY is cancelled after the measurement, the local catalog is marked unconfirmed and the coordinator does not keep VERIFIED.

Results for these commands are stored against the preparation id even when no gameplay run is active. Recording the result and folding the book are one transaction. If that transaction raises, the result is not acknowledged. A failed or missing result does not move the group to READY. READY is calculated from the committed slots, the verification row, the age, registration, and `agent_presence`. A caller-supplied link map cannot keep an OFFLINE or SUSPECT agent READY. A stored status of `ready` is rewritten to `committed` when the proof no longer holds. It does not mean CS2 is running. Applying the expected SteamID64 on COMMIT is not verification.

`LOCALHOST_DEVELOPMENT` is HTTP on `127.0.0.1`. `SECURE_LAN` is HTTPS. `FleetHost.status()` reports `transport`, `lan_ready`, and `four_pc_proven`. Do not put the fleet token in a URL.
