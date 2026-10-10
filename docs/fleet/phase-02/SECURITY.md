# Phase 02 security

Secrets remain on the PC that owns the vault. The catalog snapshot and `catalog_cache` have no login, password, shared secret, or maFile body. Binding history stores SteamID64 and a source string only. Agent tokens are stored as SHA-256. Logs written by these paths do not include the fleet token or the agent token.

When the coordinator has an assignment book, which `FleetHost` always attaches, a heartbeat must be `registered` and must present that agent's own token. `unregistered` and `revoked` are rejected. A revoked agent is not accepted with the shared fleet token. The shared token still identifies the fleet, and it still authorizes `POST /v1/operator`. It does not replace an agent token.

Enrollment is a one-time code stored as a SHA-256 hash with a five-minute expiry. `POST /v1/enroll` returns the new agent token once. The panel shows the code in the status text and does not write it to the log line. The agent PC stores the token with Windows DPAPI under `data/fleet/credentials/`. The Steam vault is not used for this token. The token is not written into ordinary logs.

`SIMULATION` does not open a socket. `LOCALHOST_DEVELOPMENT` binds `127.0.0.1` without TLS and logs that this is not a LAN deployment. `SECURE_LAN` requires a certificate, a private key, and a CA file, then binds with TLS 1.2 or newer. Cleartext HTTP on any other address is refused. `HttpTransport` builds the SSL context with `ssl.create_default_context` and rejects HTTPS that has no CA file. Certificate verification is not a switch that can be turned off.

`lan_ready` is true only when the mode is `secure_lan`, the listener is TLS, the certificate and CA files exist, and all four roster agents are `registered`. `four_pc_proven` is always false. A passing localhost HTTPS test is not a LAN trial.

A manual SteamID64 and `loginusers.vdf` do not produce `verified`. Verification is an IdentityProbe observation whose SteamID64 equals the binding and whose age is inside the catalog TTL (default 120 seconds). Applying `WindowsBackend.apply_identity_assignment` only changes the expected id. It does not set a verified flag.

Assignment commands do not call the game backend and do not grant a gameplay lease.
