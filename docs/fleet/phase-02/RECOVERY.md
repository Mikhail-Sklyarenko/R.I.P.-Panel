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

A lost ACK leaves the coordinator at the last durable state. The result write and the book update are one transaction, so a crash between them does not acknowledge the result. The next delivery applies it. It does not mark the missing agent committed or released. The operator action is reconcile, then repeat the same command id. An older `assignment_generation` is ignored for release and rejected for commit.

A new `process_generation` or a new `boot_id` clears `verification_status`, `verification_seq`, `verification_id`, and `identity_at`. A VERIFY result that still carries the previous boot or the previous process generation is stored and not applied. READY returns only after a measurement from the admitted session. The admitted generation and `last_sequence` survive a coordinator restart. A heartbeat with a sequence less than or equal to the stored one is rejected and does not change READY, the catalog, or VERIFY. A wiped agent journal does not reset the generation; re-enrollment does. Re-enrollment also clears that agent's identity proof and `last_sequence`. The reservation stays. READY does not return until a new measurement. The previous catalog generation does not block the new registration's first snapshot, and a late snapshot from the old registration is ignored.

A crash during the result transaction rolls the result and the book change back together. The heartbeat is not acknowledged. The same terminal body can be delivered again and is applied once. `operator_stops` is a different table and is not cleared by a new process generation.

`FleetStore.transaction` records the owning thread. A nested call on that thread joins the open transaction and does not commit or roll it back. Another thread waits on the lock. It does not write into the open transaction. The owner's rollback discards only the owner's writes.

After a confirmed COMMIT, the agent applies the expected SteamID64 on its local backend and restores that expected id from the committed reservation after restart. The apply is refused while a gameplay lease is held. It does not mark the account verified and does not start Steam. A catalog snapshot from the new boot is accepted at the same generation when the sequence restarts.

## Active run

`release` and `begin_release` refuse a preparation whose run is the active run. Clearing the SQLite row by hand is not a supported recovery.
