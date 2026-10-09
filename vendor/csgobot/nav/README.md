# Navigation module map

Active farm: run.py -> main.py -> farm_runtime.create_navigation ->
VisualNavController + VisualPerception/VisualLocalizer + WalkableMap/RoamingPlanner.
CameraOwnership arbitrates navigation and combat.

Current engine: visual-nav-dm-3. Expanded Dust2 ground lives in
resources/nav/experimental/de_dust2; localization in profiles/de_dust2.
The Mid-only profile is still used by route replay and calibration tools.

controller.py, locomotion and corridor-era helpers are compatibility/research
code. They are not the farm movement controller. Some types and resource
loaders are shared with current code; do not delete modules by filename alone.
Standalone tools in tools/navigation are for diagnostics, never a second farm.
