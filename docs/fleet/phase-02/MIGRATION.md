# Phase 02 migration

No vault re-import is required. `vault.enc` and `accounts.index.json` are read, not rewritten, when the agent starts. The new catalog is created beside them.

1. Stop the coordinator and the agent on that PC.
2. Update the program. The coordinator database gains tables with `CREATE TABLE IF NOT EXISTS`. Existing runs and commands stay.
3. Start the coordinator before the agents so protocol 3 is what agents speak.
4. On each agent, the first start creates `data/fleet_catalog.db` and copies logins from the index. A backup `catalog.db.v0.bak` is written once if the file already had bytes and no version.
5. Bind SteamID64 explicitly. Old roster slot values are not marked verified and are not turned into READY assignments.
6. Repeat the catalog open. The second open sees `schema_version` 1 and does not copy the backup again.

If the index JSON is unreadable, the catalog records `index_unreadable` and leaves existing rows in place. If the catalog schema is newer than the program, the catalog refuses to open.
