# Phase 02 recovery

## Coordinator crash after SAFE_STOP

The command, the idempotency key, and `operator_stops` commit in one `BEGIN IMMEDIATE` transaction. After restart, `RunMachine` reloads the stop before a heartbeat can admit a lease. If the transaction fails, `agent_command` raises and the in-memory stop is not set.

## Coordinator crash during assignment

- Before `decide_commit`: status is `draft`, `preparing`, `prepared`, or `aborting`. Restart the process and read `preparations`. Do not create a run.
- After `decide_commit`: status is `committed` even if agent ACKs are missing. Slots still say `prepared` until `note_commit`. This is not READY. Send the commit commands again; the command id is stable.
- One agent rejection moves the preparation to `aborting`. The SteamID64 stays reserved until `release` or a completed `begin_release` with four release ACKs.
- Unknown agent state is `reconcile_required`. Do not start a run.

## Agent crash

`agent_session` restores the SAFE_STOP latch for the same non-empty `run_id`. An empty run id does not clear it. A new non-empty run id does. A damaged session row fails closed and accepts no further commands. Open catalog reservations remain in `fleet_catalog.db` and are not doubled: `prepare` with the same `preparation_id` returns the stored status.

## Split network

A lost ACK leaves the coordinator at the last durable state. It does not mark the missing agent committed or released. The operator action is reconcile, then repeat the same command id. An older `assignment_generation` is rejected.

## Active run

`release` and `begin_release` refuse a preparation whose run is the active run. Clearing the SQLite row by hand is not a supported recovery.
