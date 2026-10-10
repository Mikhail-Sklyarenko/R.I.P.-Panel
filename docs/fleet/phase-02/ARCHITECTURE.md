# Phase 02 architecture

Phase 02 adds a local account catalog and a four-slot assignment protocol on top of the existing fleet. It does not start Steam, CS2, or gameplay. An assignment is metadata plus an identity expectation.

## Sources of truth

- Account secrets stay in `data/vault.enc`. The public index stays `data/accounts.index.json`. Phase 02 does not create a second password store and does not decrypt the vault on heartbeat.
- Fleet-only metadata (stable local id, SteamID64 binding, binding status, availability) lives in a sidecar SQLite catalog next to the vault index. The login is the join key. The coordinator never receives the login, password, shared secret, or maFile.
- Coordinator SQLite (`FleetStore`) is the source of truth for operator stops, the single active run, assignment preparations, and commit decisions.
- `data/wingman_fleet.json` remains the slot layout (token, port, retry, four fixed slots). Confirmed assignments are projected into it. A hand-edited roster is not treated as READY.
- `RunPlan` stays an immutable snapshot. Production `FleetHost.start_run` builds it from the assignment book inside one transaction, then projects those four slots into the roster. A hand-edited roster is not a second way to start.
- The agent `CommandJournal` is the source of truth for the SAFE_STOP latch (`agent_session`). Restart does not replay a command that was left `running`.

## Reused without rewrite

`Coordinator` heartbeat and outbox, `RunMachine` / `PairMachine`, `CommandJournal` command rows, `IdentityProbe`, vault crypto and index, `FleetHost` single `AgentService`, and the existing Wingman tab controls.

## 02.0 reliability

`FleetStore` uses `isolation_level=None`, so separate executes are not one transaction. `transaction()` takes the store lock, runs `BEGIN IMMEDIATE`, and records the calling thread as the owner. The same thread may nest. Another thread blocks until the owner commits or rolls back. Operator SAFE_STOP uses that transaction to insert the command, the idempotency row, and `operator_stops` together. A failed transaction rolls back and the method raises; memory is updated only after the commit. Resume loads `operator_stops` before any heartbeat can admit a gameplay lease. One agent stop does not stop the other three. Lock order stays coordinator lock, then store lock. A heartbeat is authenticated and fenced, including protocol and `process_generation`, before it updates the link, the catalog, presence, or results. The assignment result and the book transition commit in that same store transaction. `process_generation` lives on the agent journal and is separate from the SAFE_STOP latch.

Agent restart restores `(run_id, stopped, generation)` from `agent_session`. A corrupt row fails closed: no new commands and no lease. An empty `run_id` does not clear the latch. A new non-empty run id does.

`set_gameplay` takes a monotonic generation. A late call with an older generation does not overwrite a newer one. `AgentService` also pushes the latest desired lease again if the call it just made was superseded while the backend was still inside `set_gameplay`. The agent lock is not held across that call.

Operator command ids are UUIDs. The same `request_key` returns the original command. `runs(active) WHERE active=1` is unique, and activating a run is one transaction.

## Assignment (02.1–02.3)

Binding (`unbound`, `manually_bound`, `verified`, `unconfirmed`, `mismatch`) is independent of availability (`available`, `prepared`, `committed`, `active`, `reconcile_required`, `released`, `disabled`). Manual SteamID64 entry is never `verified`. `loginusers.vdf` is remembered history, not proof of the active account.

Four slots stay fixed: slot-1/pair-1/leader, slot-2/pair-1/follower, slot-3/pair-2/leader, slot-4/pair-2/follower. A missing computer is not replaced.

Prepare is idempotent per `preparation_id`. Commit is a durable coordinator decision and is not rolled back because an ACK was lost. Unknown agent state is `reconcile_required`, not success. READY requires four fresh IdentityProbe matches. Old `assignment_generation` values are rejected. Partial unique indexes prevent two active assignments for one agent or one SteamID64.

Protocol becomes 3 when assignment command types are added. A version-2 agent gets `protocol_mismatch` and no commands. It is not READY. Gameplay command semantics from protocol 2 are unchanged.

## Boundaries

No automatic Steam login, no matchmaking, no lobby creation, no aim or movement. Real LAN without TLS is not a supported deployment; simulation and localhost are. Four physical PCs are not part of the automated suite.
