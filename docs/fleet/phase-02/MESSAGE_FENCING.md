# Message fencing

Protocol 4. An agent that omits `process_generation` or `registration_generation`, or that still speaks protocol 3, receives no commands when an assignment book is attached. There is no production fallback.

## Identifiers

| Field | Where it lives | Meaning |
|---|---|---|
| `boot_id` | Random per `AgentService` process | Names one process. It does not order processes |
| `process_generation` | `agent_session.process_generation` in the local `CommandJournal`, copied to `agent_presence` once admitted | Monotonic start counter. Each new `AgentService` on that journal increments it inside `BEGIN IMMEDIATE`. If the write fails, the agent fail-closes and does not advertise itself |
| `registration_generation` | `agent_credentials`, and the same column on `agent_session` after enrollment | Starts at 1. It increases only when the token is new, replaced, or the row was revoked. Re-registering the same token does not increase it |
| `verification_id` | Allocated by `enqueue` and stored on the command | The agent must echo this exact id. An id the agent invents is rejected |
| `verification_sequence` | `verification_seq(preparation_id, agent_id, next_seq)` | Durable per slot. The first VERIFY is 1. A repeated command id does not allocate another value because `INSERT OR IGNORE` keeps the original command |

`process_generation` is not the SAFE_STOP / lease `generation` column. `save_session` updates the latch and leaves the process counter alone.

## Heartbeat admission

With a book attached, and before any write:

1. Fleet token.
2. Registered agent token. Revoked is rejected here, whatever the generation is.
3. `observation.protocol == 4`. A mismatch returns `protocol_mismatch`, an empty command list, and an empty `accepted_results`. The result in that body is not stored.
4. `process_generation >= 1`, a non-empty `boot_id`, and `registration_generation` equal to the credential row. Missing or invalid generation is HTTP 400 `session_rejected`.
5. Generation lower than the admitted one is HTTP 409 `stale_process`.
6. The same generation with a different `boot_id` is HTTP 409 `boot_conflict`.
7. The same boot with a sequence that is not greater than the last one is HTTP 409.

Only then does the coordinator update `AgentLinkState`, call `note_boot` when the boot or the generation changed, write `agent_presence`, accept the catalog, and fold results. A rejected heartbeat does not change the catalog, presence, READY, or the command list.

A coordinator with no assignment book still rejects a protocol mismatch before writes. It does not require `process_generation`. That path is the lab FSM. `FleetHost` always attaches a book.

## Catalog

Once `agent_presence.process_generation` is greater than zero, a snapshot is stored only when its `process_generation` and `boot_id` are the admitted session. An older boot cannot replace the snapshot by arriving later, by using a higher sequence, or by reusing a token that has not been revoked. When no generation has been admitted yet, the phase 02.7 rule remains: a different non-empty boot may publish the same catalog generation.

## Restart and reinstall

The admitted generation is in `agent_presence`. Restarting the coordinator does not clear it. Restarting the agent increments the journal counter; the next heartbeat is a new session and drops the previous identity proof.

A new Windows install with an empty journal starts again at generation 1. The coordinator still holds the old generation, so those heartbeats are `stale_process`. The reset is an explicit re-enrollment: revoking or replacing the credential clears `process_generation` and `boot_id` on that agent. The next heartbeat installs the new baseline. This does not happen by itself.

## VERIFY

Each new VERIFY command gets a new `verification_id` and the next `verification_sequence`. The sequence survives a coordinator restart. A clock step backward does not reuse a number.

The newest stored sequence wins. An older result is kept when its id matches the command and its body matches the stored result, and it does not change the slot. Evidence must also carry the admitted `boot_id` and `process_generation` or the identity is not applied. A result created by the previous process stays bound to that process. It is not treated as a measurement of the new one.

`ACCEPTED` confirms delivery only. The terminal statuses are `COMPLETED`, `FAILED`, `EXPIRED`, `UNCONFIRMED`, `REJECTED`, and `ALREADY_APPLIED`.

## Identity

`WindowsBackend.measure_identity` reads `gsi.view()` once per call. `observe`, `verify_active_identity`, and the agent's measurement use that path. Expected SteamID64 is the committed assignment. It is not an observation.

| Local Steam | GSI | Result |
|---|---|---|
| A | A, fresh | verified for A (`Identity.GSI`) |
| A | B, fresh | `MISMATCH` |
| A | B, stale | B is ignored; the local id stands |
| A | absent | local id (`Identity.STEAM_LOCAL`) |
| absent | A, fresh | `Identity.GSI` for A. GSI is acceptable only when no local id is present |
| absent | absent | `UNCONFIRMED` |
| B | B, fresh, expected A | `MISMATCH` |
| B | A, fresh, expected A | `MISMATCH`. The matching GSI id is not a proof |

A conflict between two current sources is never resolved by picking the convenient one. The probe status is stored as `identity_status` and is not rewritten from the detail text. VERIFY does not start Steam or CS2.

## Upgrade order

1. Replace the coordinator. `PRAGMA user_version` moves to 5. Old rows stay. Unfinished commands stay unfinished. `operator_stops` stays. `last_sequence` starts at 0 until the next accepted heartbeat.
2. Replace the four agents. Each journal moves to `user_version` 2 and claims a new `process_generation` on start. A journal newer than this program refuses to open.
3. Enroll again only where the credential changed or the local journal was wiped. `POST /v1/enroll` returns `agent_token` and `registration_generation`. The agent stores the generation next to the DPAPI token.
4. Confirm each heartbeat is HTTP 200 and that presence shows the new generation.
5. READY returns only after four new VERIFY observations from those sessions.

An agent that was not upgraded gets no gameplay command and no assignment command.
