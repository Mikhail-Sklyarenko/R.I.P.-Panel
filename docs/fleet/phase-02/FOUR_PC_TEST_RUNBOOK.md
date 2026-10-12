# Four-PC runbook

This was not executed. `four_pc_proven` must stay false until it is.

## Layout

```text
PC-01  Coordinator + agent pc1   Pair 1 leader
PC-02  Agent pc2                 Pair 1 follower
PC-03  Agent pc3                 Pair 2 leader
PC-04  Agent pc4                 Pair 2 follower
```

Install the same git SHA on all four. Protocol 4. Do not copy `vault.enc`, `.vault_key`, journals, or DPAPI token files between Windows profiles.

## TLS

1. Create a CA and a server certificate whose SAN matches the address in `wingman_fleet_url` (IP as iPAddress, DNS as dNSName).
2. Put cert and key only on PC-01. Put the CA file on all four.
3. Wingman tab: transport `secure_lan`, `https://<coordinator>:8790`, port 8790, CA/cert/key paths.
4. Confirm files exist. Do not switch to HTTP if HTTPS fails.

## Firewall

On PC-01, if agents cannot connect, add a rule for TCP 8790 limited to the three agent addresses. Do not disable Windows Defender Firewall. Do not forward the port to the internet.

Prove TCP with `Test-NetConnection -ComputerName <IP> -Port 8790`. That is not TLS proof.

Prove TLS with:

```powershell
curl.exe --cacert "C:\PATH\TO\ca.pem" "https://<COORDINATOR_IP>:8790/v1/health"
```

No `-k`. Then `/v1/status` without the operator token must be 403. Do not print the operator token.

## Enrollment

On PC-01 press `Код` for that slot. On the matching PC enter the code and press `Подтвердить регистрацию`. The local agent must restart, store the token with DPAPI, and send a protocol-4 HTTPS heartbeat. Enrollment HTTP 200 without that heartbeat is not success. Repeat for four different computers.

## After four heartbeats

Assign four different local accounts. `Подготовить 4 назначения` → `Подтвердить состав` → `Проверить SteamID64`. READY requires four fresh identity proofs. Do not start Steam or CS2 for the LAN trial. ONLINE without VERIFIED is `READY = False` and is not a LAN failure.

Record OS build, SHA, hostname, agent id, transport, and screen scale per PC in a local file. Do not copy tokens, vaults, or private keys into git.
