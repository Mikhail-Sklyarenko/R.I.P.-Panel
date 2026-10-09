# Wingman Inferno fix 7

Fix 7 addresses the supplied `2026-09-22 12-48-18.mp4` and complete text log. It replaces the failed short-side apartment entrance with the second-mid entrance visible in the earlier walkthrough.

## Evidence

The video lasts 581.63 seconds. The whole duration was surveyed at 15-second intervals, with additional samples around combat and apartment-entry failures. The log contains 565 lines, no ERROR or traceback, and 24 first-fire measurements: 16–2468 ms, median 281.5 ms. These are contact-to-first-fire observations, not kill time or detector recall. Final telemetry reports 5 stuck events, 4.7 seconds blocked and 39.6 seconds waiting for pose. Three apartment approaches started; none logged completion, though death also prevents completion.

Navigation is already paused when an eligible enemy is selected. Of 53 logged navigation waits, 52 are zero and one is 15 ms. Thus this recording does not support attributing the long acquisition delays primarily to waiting for localization. Nonetheless the old ordering unnecessarily placed aim dispatch after the navigation future; that dependency is removed.

Confirmed problems in the code:

1. The 320px target-selection radius rejects opponents visible near the screen edges. At 44 seconds the visible CT's body is approximately x=90–172 in a 1280px frame, over 500px from the crosshair. A manually annotated regression demonstrates the selection failure; it is not a replay of YOLO inference.
2. OBS supplies RGB, but `model.predict(source=np.ndarray)` expects BGR. The concrete YOLO wrapper forwarded the array unchanged. The Wingman adapter now converts both full-frame and ROI inputs while preserving RGB for teammate-name inspection. See [Ultralytics inference sources](https://docs.ultralytics.com/modes/predict/#inference-sources).
3. Aim projection accounted for combat mouse commands only. Navigation could turn the camera between capture and target acquisition, and those accepted commands were omitted. Wingman aim now uses a shared, serialized command history without double-counting its own commands.
4. Head/body selection and nearest-player selection could change between frames. Wingman now prefers the associated body when it is visible and retains a matching current target through camera-compensated box overlap. Missing detections do not authorize aiming or firing.
5. ROI fallback was decided before teammate filtering. A false enemy subsequently vetoed as friendly could suppress the enlarged crop pass. Wingman retries after eligibility filtering and keeps full-frame friendly evidence when evaluating the crop.
6. The short-side apartment entrance repeatedly reaches blocked/outside-ground states in the supplied log. It is removed from the apartment route.

## Changes

Wingman acquires eligible opponents across the visible frame. Camera step caps increase from 32/8 to 48/16 counts (far/near), with vertical scale 1 instead of .85; current-pose and input-permission deadlines remain. Smoothing stays at 1.4 and EMA alpha .85. Body-first continuity replaces head/chest priority oscillation. Head-only detections remain usable. The target-sized central firing gate and teammate veto remain enforced.

Combat dispatch now precedes waiting for navigation. A brief .18s Wingman contact grace avoids immediately returning the camera to navigation after one missing detection; no firing or stale target tracking is authorized during that gap. A new round or noncombat phase clears target continuity. `wingman_detect` logs raw class counts, eligible counts and whether the enlarged crop ran.

The apartment path is now T spawn → second mid → garage stairs → apartments → A balcony. Entry coordinates come from 94–107 seconds of `2026-09-20 20-01-41.mp4`, joined to the previously reviewed balcony exit. The separate, outbound-only apartment mask excludes the rejected short-side stair. Long and short remain independent choices. Round reset and measured exit restore ordinary A missions.

## Scope and validation

416 tests passed: 350 Wingman/navigation/panel/map regressions and 66 combat tests. The unchanged HTTP socket lifecycle test remains excluded in the restricted environment. The first standalone combat test invocation encountered the repository's existing panel/worker `config` import collision; rerunning with the worker configuration loaded explicitly passed all 66 tests.

New checks cover the recorded edge enemy with supplied boxes, body/head flicker, two-player continuity, camera-motion compensation, rejected mouse writes, RGB/BGR preservation, ROI retry after teammate veto, unknown model classes, the second-mid geometry, all three routes in the existing 2D controller simulation, and faster bounded acquisition without a vertical reversal in a deterministic mouse simulation.

The local environment has no `cs2_yolov8m_640_augmented_v4.pt`. End-to-end detector recall, friendly-fire rate, kill/death ratio and live CS2 stair/balcony physics are NOT validated. Sampling a video and testing a drawn mask cannot establish perfect navigation. Sparse route calibration includes interpolated segments. Existing pose uncertainty stops remain intentional.

Wingman-specific target selection, input color conversion, speed settings and route data do not change DM configuration. Shared code changes are combat-before-navigation ordering and accepted camera-command bookkeeping; the new shared-history aim mode is enabled for Wingman only. Existing DM combat regressions pass.

## Installation

Stop the bot and panel. Extract `wingman-inferno-fix-7.zip` into the existing `R.I.P.-Panel` root with replacement. This cumulative archive includes the combat dependencies together so an older mouse-controller module is not left beside the new worker. Do not remove environments, weights, accounts or GSI settings. Use the same Wingman launch command.

Verify `wingman_fix_7`, `wingman_missions_v7`, and profile `wingman-inferno-fix-7` in the log. During an apartment round, the first turn must lead into second mid; it must not approach the previous short-side stair. The test still needs several T rounds, CT combat, and the new apartment traversal recorded together with the log.
