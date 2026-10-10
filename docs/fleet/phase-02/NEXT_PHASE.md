# Phase 03

Phase 02 is a simulated assignment layer. It is not a finished four-PC deployment.

1. Put TLS in front of the fleet listener, with certificate checks left on, and only then set `lan_ready`.
2. Add an operator form for `register_agent` and for storing each agent's token. Until that exists, unregistered agents still authenticate with the shared token only.
3. Run the assignment flow on four Windows PCs with real local vaults and a manual Steam login. Do not automate the login in that phase either.
4. Fold a fresh IdentityProbe from the agent heartbeat into `note_identity` on a timer, so READY expires in the UI without a separate verify command.
5. Replace the single local-account field with a list populated only from `catalog_cache` for that agent.
6. Do not start matchmaking, lobby creation, or gameplay until those checks have been seen on the real machines.
