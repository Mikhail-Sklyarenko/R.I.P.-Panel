# Minimap Navigator (PR-N0 – PR-N8)

> Runtime обновлён на измеренную визуальную навигацию. Текущий статус,
> обязательная подготовка профиля и ограничения описаны в [NAV_VISUAL.md](NAV_VISUAL.md).
> Ниже сохранена история прежних подходов; её заявления о готовности не являются
> результатами проверки нового контура в игре.

Goal-based navigation for CS2 DM farm bots. **Not a YOLO dataset** — config + code only.

## Product locomotion contract (corridor + Safe-W)

FermK visual failure (“runs into a wall forever”) came from **blind W** toward
map-norm hops while place XY was frozen/wrong.

Product contract now:

1. **Corridor scripts** — place label picks face→walk stages (`ct_spawn→short→mid`, …)
2. **Safe-W** — hold W only with radar flow or a short armed burst after place/step change
3. **Wall-stop** — no flow while W → release W + turn (never thrust into the same wall)
4. **Place lock clear** — reject-streak ~2.5s clears eternal `ct_spawn` hold
5. Graph **neighbors** are never treated as teleports

Expect:

```
nav: locomotion=corridor+Safe-W
nav: corridor ct_spawn_to_mid place=ct_spawn → mid
nav: Safe-W hold (no flow/burst) …
nav: wall-stop turn 95° (no radar flow while W)
nav: place-lock clear (reject-streak) was=ct_spawn
```

Not: minutes of `fwd=1` into one wall with frozen pose.

## Place-label navigation (product — no seed cosmetics)

Gate 0 on farm HUD: **centered rotating radar** (player icon fixed at disk
center). `radar.png` template match is **not** reliable (domain gap).

Product perception that **does** work objectively:

1. **Auto Hough circle** — live radar disk (large HUD ~r108 vs old calib ~r83)
2. **Yellow (T) + cyan (CT) center icon** — never lock chrome at 0.68
3. **CS2 location-name strip** under the radar → `PlaceLocalizer` → landmark `(x,y)`
4. **Waypoint graph** in pack — path hops (turn to next node before walls)
5. **Honest stuck** — no radar-flow while W held → escape (not virtual dist)
6. **No place read** → `wait_place` (no invented GPS / sector chaos)

Expect:

```
nav: place localizer loaded 9 templates map=de_dust2
nav: place-localized goal-seek …
nav: path tunnel>mid …
mode=world pose=(0.22,0.28) path=tunnel>mid fwd=1
```

`resources/nav/maps/*/hud_ref/` is **calibration**, never YOLO train (`never_train`).

Dust2 RU catalog (22 place labels, title-bar cropped → 1280×720) drives
`dust2_dm` v2.3.0 dense waypoint graph + corridor scripts. Expect `place_templates=22`.

Product locomotion unlock (post FermK soak):

1. **Place hold 4s** — label flicker keeps `mode=world` (perception + pose filter)
2. **Abort macro on world** — never stay in `generic_dm` after a place hit
3. **Macro off by default** — `CSGOBOT_NAV_ALLOW_MACRO=1` to re-enable short 8s safety
4. **Look muted** while `seek` / `wait_place` / brief pause
5. Log: `nav: place=<id> score=… margin=…`
6. **Multi-offset strip** + sticky bias + **3-frame switch hysteresis**
7. **Anti-teleport** — reject A↔tunnel jumps unless strong score/margin + 4 confirms
8. **Match-ready latch (12 frames)** — stop false `map_transition` pauses mid-DM
9. **Hop by place lock** — advance path when label matches a later waypoint (XY may freeze)
10. **Combat engage ≤130px** (or firing) — keep path while paused; do not clear route

Expect:

```
nav: place=mid score=0.81 margin=0.40 …
nav: place-localized goal-seek …
nav: path a_ramp>short>mid …
mode=world … fwd=1
nav: world pose — abort macro, resume path seek   # if macro was on
```

Not: long `macro_fallback` with `fwd=0` while place occasionally flashes world.

## Product locomotion (walk-to-goal)

Root cause of “spin then stand still” (Sep 8 farm soak `c5c8ad629481`):

1. **PCA yaw** on the player blob never matched `bearing_deg` → `|yaw_err|` ≫ 22° → **W never held**
2. **Combat pause** froze Nav on *any* distant detection (~50% of ticks in DM)
3. **Stuck escape** only strafed/rotated → more spinning, no progress

Product behavior now:

1. **Arrow-tip yaw** (centroid → bright tip) in the same frame as `bearing_deg`
2. **Crawl + fail-open**: after ~0.9s without pose progress, hold W while turning (hard walk by ~1.8s)
3. **Stuck escape = thrust + rotate** (W held during escape)
4. **DM combat gate**: pause Nav only for close engage (≤130px) or active fire — not every detection
5. Metrics: `forward_held_pct`, `fail_open_pct`, `avg_yaw_err_deg`; debug log includes `yaw_err` / `fwd` / pause reason
6. Log may show `nav: place-reject teleport …` when weak A↔tunnel NCC is blocked
7. Stuck timeout is longer while the same place label is frozen (discrete GPS)

Expect in stderr while seeking:

```
nav: state=seek_entry … yaw_err=.. fwd=1 fail_open=0 …
```

Not: endless `stuck escape` with frozen pose and `fwd=0`.

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
