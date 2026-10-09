# Wingman Inferno fix 5

This update addresses aim latency, teammate filtering and turning locomotion. Short and apartments remain pending a new walkthrough, as agreed with the user. The existing mask is unchanged; no unverified passage is opened.

## Recording and log evidence

Input: `2026-09-21 14-36-27.mp4` (745.45 seconds), and the complete supplied text file (2558 split lines). The new run is 840 timestamped lines starting 14:35:47; older appended runs were separated before analysis. A contact sheet spans the recording at 30-second intervals; combat sequences around 24–28, 86–90, 116–120, 168–172, 232–236, 268–272, 568–572 and 708–712 seconds were additionally sampled. This is sampled visual inspection, not a frame-by-frame replay of the detector.

The current run reports 17 first-fire delays ranging from 47 to 1328 ms. Capture age is commonly 63–109 ms. Sparse navigation status logs contain 39 `align_measured_heading` entries and 89 `follow_verified_route` entries; these counts are not percentages of elapsed movement time. No traceback or ERROR entry was found in the supplied text. The final navigation metrics report three stuck events and 12 seconds blocked, so navigation remains imperfect.

Confirmed code causes:

- Fix 4 tightened firing permission but retained EMA alpha .45, smoothing 2.4, additional low-FPS adaptive smoothing, and .55 vertical damping. The resulting slow target following can lag behind a moving body even though the detector produces fresh boxes.
- Fixed Wingman missions did not enter the multidirectional movement branch used by DM free roaming. They stopped outside the forward-only heading threshold.
- Teammate labels were reduced to a cyan pixel count. That can accept scenery and miss compressed, nearly white cyan text. This does not establish that every `teammate_veto` in the log was erroneous.
- Next patrol destination selection ignored the incoming travel direction, allowing unnecessary immediate reversals.

## Changes and separation from DM

Wingman-only aim configuration: alpha .85, fixed smoothing 1.4 (no FPS-based extra smoothing), near-target Y factor .85. The central target-size fire gate and fresh-frame requirement remain; the update does not restore firing at a 24px offset beside small bodies. Model weights, detection confidence and class definitions are unchanged.

Wingman-only teammate filtering now requires a row of glyph-like components with cyan/near-white antialiased colour. A solid cyan patch is insufficient. Own-team body and associated-head vetoes remain. The log now includes raw and eligible detection counts when a veto is reported.

Adaptive fixed goals now use checked WASD directions while turning and look ahead along visible portions of the route. Swept movement rays, stale-pose stops and collision recovery remain enforced. Wingman camera turns use stronger acceleration and a faster final correction, with the same speed cap and fresh-pose deadline. The default camera response for DM is unchanged. Turning does not authorize running into blocked geometry.

Patrol/support/guard selection now penalizes unnecessary reversal when a reachable alternative exists. Plant and defuse priorities remain unchanged.

## Validation

323 tests passed: 266 Wingman/navigation/panel/DM regressions and 57 combat tests. The unchanged HTTP receiver socket lifecycle test was excluded in this restricted environment.

New regressions cover the recording's teammate at 90 seconds and enemy at 270 seconds with manually supplied boxes, cyan scenery rejection, moving-target EMA lag, fixed-goal movement through a turn, stale-pose release, faster camera settling without overshoot, and patrol direction continuity. The collision simulation now models strafing as well as forward/reverse movement, matching the controller's supported inputs.

In the synthetic 14 Hz / 200 px-per-second EMA test, steady lag decreases from over 15px to under 3px. This is a filter result, not measured live kill performance. The local environment lacks the Windows detector model, so full YOLO inference accuracy and end-to-end hit performance were not replayed. No live CS2 validation is claimed.

## Installation

Stop the panel and bot. Extract `wingman-inferno-fix-5.zip` into the existing `R.I.P.-Panel` directory with replacement of included files. Keep the existing Python environments, models, account data and GSI configuration. Launch using the same Wingman command.

Check for `wingman_fix_5` and `wingman-inferno-fix-5` in the new log. Startup defaults printed before Wingman initialization can still show the base DM configuration; the Wingman-specific line and mouse-thread configuration report the applied overrides.

Provide the short/apartments walkthrough in the next request. Those physical routes and height/interaction transitions are not part of this release.
