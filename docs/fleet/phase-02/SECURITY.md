# Phase 02 security

Secrets remain on the PC that owns the vault. The catalog snapshot and `catalog_cache` have no login, password, shared secret, or maFile body. Binding history stores SteamID64 and a source string only. Agent tokens are stored as SHA-256. Logs written by these paths do not include the fleet token or the agent token.

The shared fleet token still authenticates a heartbeat. Per-agent tokens are enforced only after `register_agent`. Until an operator registers an agent, another holder of the shared token can speak as that agent id. Registration of a different token for an existing agent is rejected. Revocation blocks that agent token.

HTTP has no TLS. Certificate checks are not disabled because TLS is not turned on. `lan_ready` is false. Simulation and localhost are the supported modes in this phase. Do not expose port 8790 on a real LAN and treat that as a finished deployment.

A manual SteamID64 and `loginusers.vdf` do not produce `verified`. Verification is an IdentityProbe observation whose SteamID64 equals the binding and whose age is inside the catalog TTL (default 120 seconds). Applying `WindowsBackend.apply_identity_assignment` only changes the expected id. It does not set a verified flag.

Assignment commands do not call the game backend and do not grant a gameplay lease.
