# Phase 02.8 findings

Branch `fix/fleet-phase02-message-fencing`, cut from `cce921064cb4871cc6a4ed10e59c9c5c1a1a20f0`. The profile on that commit was `146 passed`. The three defects below were reproduced by `tests/test_fleet_phase028.py` before the fix (`4 failed, 1 passed`). The one pass was the distinct-sequence case that the old book already ignored; the hole was an equal sequence plus a second fold.

## Defects

| # | What failed | Cause | Fix |
|---|---|---|---|
| 1 | A second delivery of a terminal VERIFY changed the book again | `handle_heartbeat` called `_fold_assignment_result` even when `record_result` returned false | Fold only when the result is newly stored and terminal, inside the same `FleetStore` transaction. An identical terminal body is acknowledged and not applied again. A different body for the same `command_id` is a conflict: no ACK and no book change |
| 2 | Two VERIFY commands issued in one millisecond shared `seq` | `seq` was `int(clock() * 1000)` | `verification_seq` allocates the next integer inside the enqueue transaction. Order is that integer, not the clock and not the UUID |
| 3 | A later heartbeat from an older process replaced the newer session | `boot_id` is random. Any different value was accepted | `process_generation` is a durable counter in the agent journal. The coordinator admits a session only when the generation is newer, or equal with the same `boot_id`. The check happens before catalog, presence, boot, results, and commands |
| 4 | VERIFY ignored a fresh GSI that disagreed with local Steam | `verify_active_identity` called `IdentityProbe.probe` with only the expected id | `measure_identity` takes one `gsi.view()` and passes that snapshot's id and `fresh` flag into the same probe `observe` uses |

`ACCEPTED` is not terminal. It can be stored and it is not acknowledged, so the journal can still deliver the real result. It does not move `AssignmentBook`.

A forged `verification_id`, or an `assignment_generation` that is not the slot's current generation, raises inside the transaction. The result is rolled back and is not acknowledged.

## What an old message can still do

A VERIFY whose `verification_id` matches the command but whose `boot_id` or `process_generation` is not the admitted session is stored and acknowledged so the old process does not retry forever. It is not applied to the slot. Only the latest issued sequence can change identity. An older sequence, including one delivered for the first time after a newer one, does not restore `verified`.

## Limits that remain

- The coordinator trusts the evidence the current process reports. Fencing stops an old process from supplying that evidence. It does not prove the Steam client cryptographically.
- A fresh GSI with no local Steam id is accepted as `Identity.GSI`. A stale GSI is not used. Two fresh sources that disagree are `MISMATCH`.
- There is no production flag that turns fencing off.
- This pass did not run on four physical PCs and did not click the Wingman tab. `four_pc_proven` stays false.
- Phase 03 was not started.
