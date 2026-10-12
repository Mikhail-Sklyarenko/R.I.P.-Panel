# Phase 03

Phase 02 software on `fix/fleet-phase02-catalog-ui-lan-acceptance` closed the inherited-catalog and previous-registration PREPARE holes. HTTPS loopback and a real Wingman window were checked on one Windows host. It did not start this phase. Four physical PCs and a live Steam identity are still outstanding. See `FOUR_PC_TEST_RUNBOOK.md`.

1. Run `SECURE_LAN` on four Windows PCs. `lan_ready` may become true from the configuration. `four_pc_proven` must stay false until that trial is recorded.
2. Confirm DPAPI enrollment on each PC: the coordinator shows a one-time code, the agent PC claims it, and the next heartbeat is `registered`. Revoke one PC and confirm it stays rejected.
3. Point IdentityProbe at a real signed-in Steam client. The simulator's GSI probe is not that check.
4. Click through the Wingman tab: four menus, a missing account, prepare, commit, verify, release, and a restarted panel that still shows the preparation.
5. Do not start matchmaking, lobby creation, or gameplay until those checks have been seen on the real machines.
