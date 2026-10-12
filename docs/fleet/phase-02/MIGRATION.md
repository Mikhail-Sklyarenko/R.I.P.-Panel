# Phase 02 migration

No vault re-import is required. `vault.enc` and `accounts.index.json` are read, not rewritten, when the agent starts. The new catalog is created beside them.

1. Stop the coordinator and the agent on that PC.
2. Update the program. The coordinator database gains tables with `CREATE TABLE IF NOT EXISTS`. Existing runs and commands stay.
3. Start the coordinator before the agents. Protocol is 4. `AssignmentBook` sets `PRAGMA user_version` to 5 and adds `registration_generation`, `process_generation`, `verification_seq`, `agent_presence.last_sequence`, and `catalog_heads.registration_generation` if they are missing. A migrated `catalog_heads.registration_generation=0` is an unknown context, not proof that generation 150 belongs to the current agent. The agent journal stays at `user_version` 2. Repeating the open does not delete the journal, does not mark a pending command successful, does not clear `operator_stops`, and does not delete reservations. A schema newer than this program fails closed. Replace the four agents in the same update: a VERIFY result without `identity_status` is not a proof. Back up with the SQLite backup API, not a copy of a live WAL file.
4. On each agent, the first start creates `data/fleet_catalog.db` and copies logins from the index. A backup `catalog.db.v0.bak` is written once, through the SQLite backup API, if the file already had bytes and no version. Later opens add `vault_present` and `catalog_generation` without a new schema number. The agent start also compares index logins with vault logins and records a diagnostic. A missing or unreadable vault does not delete catalog rows.
5. Bind SteamID64 explicitly. Old roster slot values are not marked verified and are not turned into READY assignments.
6. Repeat the catalog open. The second open sees `schema_version` 1 and does not copy the backup again.

If the index JSON is unreadable, the catalog records `index_unreadable` and leaves existing rows in place. If the catalog schema is newer than the program, the catalog refuses to open.
