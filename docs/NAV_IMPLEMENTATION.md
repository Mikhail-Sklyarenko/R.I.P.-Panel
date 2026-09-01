# Minimap Navigator (PR-N0 – PR-N8)

Goal-based navigation for CS2 DM farm bots. **Not a YOLO dataset** — config + code only.

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
