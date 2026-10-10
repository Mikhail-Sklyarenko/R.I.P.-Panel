# Windows deployment

This was not executed on four physical PCs. The steps below are the intended update order for a later operator run.

1. Install the same build on the coordinator PC and the three other PCs. Do not start CS2 or Steam for this phase.
2. Keep each PC's existing `data/vault.enc`, `data/accounts.index.json`, and `data/.vault_key`. Do not copy those files to the coordinator.
3. Choose the transport. `localhost_development` binds `127.0.0.1` and the status line must say that four real PCs were not checked. `secure_lan` needs `wingman_fleet_tls_cert`, `wingman_fleet_tls_key`, and `wingman_fleet_tls_ca`. Do not open plain HTTP on `0.0.0.0`. Do not point agents at a public address.
4. On each PC set `wingman_fleet_agent_id` to `pc1` … `pc4` matching the fixed slots, and set `wingman_fleet_url` to the coordinator. Start the agent. It creates `data/fleet_catalog.db` from the local index.
5. Bind each SteamID64 locally. The binding is manual until IdentityProbe sees that exact id. The coordinator list shows binding status, not a password.
6. On the coordinator press «Код» on that PC's card. The one-time code appears in the status box and is not written as a log line. On that PC paste the code and press «Подтвердить регистрацию». The token is stored with DPAPI. A second use of the same code fails. «Отозвать» marks that agent revoked.
7. Choose an account from each PC's menu. An empty or unknown id is an error and does not select a different account. Press «Подготовить 4 назначения». The status text must show the stored state. A validation error stays an error.
8. Press «Подтвердить состав» only after preparation is `prepared`. That still does not start the game.
9. «Старт цикла» stays blocked until the book reports four fresh identity matches. There is no button that deletes a SQLite row and calls the conflict solved.

Local checks performed on this Windows 10 machine were the automated pytest profile, not a live four-PC fleet and not a CustomTkinter click-through.
