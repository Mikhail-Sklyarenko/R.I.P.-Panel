# Secure LAN acceptance

Protocol stays 4. `four_pc_proven` stays false.

## Distinctions

| Check | What it proves | Status |
|---|---|---|
| In-process heartbeat | Assignment handlers | PASSED (existing Fleet tests) |
| HTTPS loopback on 127.0.0.1 | TLS 1.2+, CA check, hostname/IP SAN, operator vs fleet token | PASSED (`tests/test_fleet_secure_lan.py`) |
| Two physical PCs | Cross-machine heartbeat | BLOCKED — only this Windows host was available |
| Four physical PCs | Four independent HTTPS agents | BLOCKED |
| Real Steam identity | Signed-in Steam / GSI | BLOCKED — Steam was not started |

## Loopback

Coordinator listened on `127.0.0.1` with an ephemeral certificate whose SAN is the IP address. `curl.exe --cacert` (no `-k`) received `/v1/health`. `ssl.create_default_context` received the same. `/v1/status` without an operator token, with the fleet token as `X-Operator-Token`, and with `X-Fleet-Token` returned 403. The matching operator token returned 200. A foreign CA was rejected. Certificates were created only under pytest `tmp_path` and are not in git.

## UI configuration

The Wingman tab now has `wingman_fleet_transport`, coordinator URL, port, CA path, certificate path, and key path. Saving SECURE_LAN without `https://` or without the required files is refused. The fleet token is not placed in the URL.

## Firewall and other hosts

Windows Firewall was not changed. No extra PC was present for `Test-NetConnection`. See `FOUR_PC_TEST_RUNBOOK.md`.
