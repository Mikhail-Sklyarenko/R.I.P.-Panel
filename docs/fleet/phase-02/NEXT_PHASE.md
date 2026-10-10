# Phase 03

Phase 02.8 closed the message-fencing defects in `FINDINGS_02_8.md`. The identity-integrity patch on `fix/fleet-phase02-identity-integrity` closed the false VERIFIED, result-status, heartbeat-sequence, and registration-catalog defects in `FINAL_IDENTITY_INTEGRITY.md`. It did not start this phase. Phase 02 is still a simulated assignment layer with a TLS mode and an enrollment form. It is not a finished four-PC deployment.

1. Run `SECURE_LAN` on four Windows PCs. `lan_ready` may become true from the configuration. `four_pc_proven` must stay false until that trial is recorded.
2. Confirm DPAPI enrollment on each PC: the coordinator shows a one-time code, the agent PC claims it, and the next heartbeat is `registered`. Revoke one PC and confirm it stays rejected.
3. Point IdentityProbe at a real signed-in Steam client. The simulator's GSI probe is not that check.
4. Click through the Wingman tab: four menus, a missing account, prepare, commit, verify, release, and a restarted panel that still shows the preparation.
5. Do not start matchmaking, lobby creation, or gameplay until those checks have been seen on the real machines.
