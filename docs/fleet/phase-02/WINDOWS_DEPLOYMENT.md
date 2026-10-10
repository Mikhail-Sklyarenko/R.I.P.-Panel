# Windows deployment

This was not executed on four physical PCs. The steps below are the intended update order for a later operator run.

1. Install the same build on the coordinator PC and the three other PCs. Do not start CS2 or Steam for this phase.
2. Keep each PC's existing `data/vault.enc`, `data/accounts.index.json`, and `data/.vault_key`. Do not copy those files to the coordinator.
3. Start the coordinator from the Wingman tab. The status line must say that HTTP has no TLS and that the LAN is not ready. Leave it that way until a separate TLS terminator exists. Do not point agents at a public address.
4. On each PC set `wingman_fleet_agent_id` to `pc1` … `pc4` matching the fixed slots, and set `wingman_fleet_url` to the coordinator. Start the agent. It creates `data/fleet_catalog.db` from the local index.
5. Bind each SteamID64 locally. The binding is manual until IdentityProbe sees that exact id. The coordinator list shows binding status, not a password.
6. On the coordinator, register a distinct agent token per PC before any real use. The same token must be configured as that agent's `agent_token`. This build's panel does not yet have a registration form; registration is `AssignmentBook.register_agent`.
7. Choose four different local account ids (the slot field `local_account_id`, or the first bound account in that agent's cache). Press «Подготовить 4 назначения». The status text must show the stored state. A validation error stays an error.
8. Press «Подтвердить состав» only after preparation is `prepared`. That still does not start the game.
9. «Старт цикла» stays blocked until the book reports four fresh identity matches. There is no button that deletes a SQLite row and calls the conflict solved.

Local checks performed on this Windows 10 machine were the automated pytest profile, not a live four-PC fleet and not a CustomTkinter click-through.
