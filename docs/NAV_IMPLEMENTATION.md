# Minimap Navigator (PR-N0 – PR-N8)

Goal-based navigation for CS2 DM farm bots. **Not a YOLO dataset** — config + code only.

## Product map re-detect (Dust2 ↔ Mirage mid-session)

Root cause of “map changed but nav stayed old”: soft-lock after first confirm
never reopened (`lock_after_confirm` + hard ignore).

Product behavior now:

1. **match_ready** popup → `map: unlock` (clears soft-lock)
2. Soft-lock still reduces flicker, but a **different** map for N frames
   reconfirms → `map: auto patrol …` + `nav: auto pack … (map hot-swap)`
3. During match-ready, **Nav is paused** (no walking with wrong pack)

Expect in stderr on map change:

```
map: unlock (match_ready) was=dust2 — awaiting reconfirm
map: auto patrol mirage via match_ready (3/3 frames)
nav: auto pack mirage_dm … (map hot-swap)
```

## Product nav hardening (post farm soak)

Root-cause fix after Sep 1 Dust2 soak (`generic_dm` + Look fight):

1. **Auto start pack** = `dust2_dm` when patrol is still `generic_dm` (placeholder)
2. **Fail-open** after 8s if still on `generic_dm` without map lock
3. **map_detect status** logged every 5s (`map: detect=…`)
4. **Combat > Nav > Look** — Look suppressed while seeking / stuck_escape
5. **Stuck grace** 10s after start/reload; pack stuck timeout 4.5s

Expect in stderr on Dust2 farm:

```
nav: movement enabled pack=dust2_dm …
map: detect=… script=…
```

Not: endless `stuck escape` in the first 10s, not `pack=generic_dm` on Dust2.

## PR-N9 (radar overlay editor + HTTP fleet collector)

### Visual radar editor

**Nav Packs** tab — click radar map to set `goal1` / `goal2` coordinates (normalized 0–1).

- Green = primary goal, orange = second goal, blue = entries, gray = landmarks
- Syncs with numeric fields; **Save override** writes `data/nav_packs/<pack_id>.yaml`

### HTTP fleet collector (master PC)

Central collector merges metrics from all farm PCs over HTTP (no manual JSONL copy).

**Master PC:**

1. Config #3 → set `nav_fleet_collector_port` (default 8765) and optional `nav_fleet_collector_token`
2. **Nav Fleet** tab → **Start collector (master)**  
   Or CLI: `python scripts\nav_fleet_collector.py`

Endpoints:

- `POST /api/v1/nav_metrics` — ingest one record or `{"records": [...]}`
- `GET /api/v1/health` — collector status
- `GET /api/v1/fleet/summary` — 24h rollup JSON

Auth: `Authorization: Bearer <token>` or header `X-Fleet-Token` (if token set).

**Farm PC:**

1. Config #3 → `nav_fleet_push_url` = `http://<master-ip>:8765/api/v1/nav_metrics`
2. Same `nav_fleet_collector_token` if master uses auth
3. Metrics auto-push on each `nav_metrics` stderr line (fail-open; local JSONL always kept)

Test push: `python scripts\nav_fleet_push.py`

## PR-N8 (multi-host aggregator + pack editor)

### Fleet inbox (multi-PC)

Drop `nav_metrics.jsonl` from each farm PC into:

```
data/fleet_inbox/pc01.jsonl
data/fleet_inbox/pc02.jsonl
```

**Nav Fleet** tab shows merged 24h rollup (local + inbox live).

**Import** merges inbox into `data/logs/nav_metrics.jsonl` and archives to `fleet_inbox/processed/`.

```bat
python scripts\nav_fleet_import.py
python scripts\nav_fleet_report.py --import-inbox
python scripts\nav_fleet_report.py --json
```

### Pack editor (panel)

**Nav Packs** tab — tune goal coordinates without editing YAML by hand.

- Loads bundled pack from `resources/nav/packs/`
- **Save override** → `data/nav_packs/<pack_id>.yaml` (farm-safe, not in git)
- csgobot resolves override automatically (`nav/paths.py`)
- **Reset** removes override, back to bundled
- **Validate preflight** runs `tools/nav_preflight.py` for selected pack

Typical use: nudge `goal_x` / `goal_y` after soak on your HUD calibration.

## PR-N7 (fleet metrics dashboard)

- `data/logs/nav_metrics.jsonl` — per-PC telemetry
- Panel **Nav Fleet** tab — live 24h dashboard

## PR-N6 (Mirage + auto pack)

- `mirage_dm`, `dust2_dm`, `generic_dm` with `csgobot_nav_pack=auto`

## Tests

```bat
pytest tests/test_nav_pr_n8.py tests/test_nav_pr_n9.py tests/test_nav_metrics_fleet.py tests/test_csgobot_nav_*.py -q
```

## Next: PR-N10

Auto-tune goals from fleet metrics, pack diff/rollback UI
