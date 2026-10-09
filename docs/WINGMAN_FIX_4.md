# Wingman Inferno — fix 4

Evidence: `2026-09-21 13-24-50.mp4` and the appended 13:21–13:30 log session. Older sessions in that same text file were not treated as this run. Contact sheets and focused combat frames were inspected; detector inference was not replayed locally because the Windows model weights are not present here.

## Problems confirmed

- T initially selected the fixed (820,710) plant point every round.
- CT cycled through nearby A-site grid cells and deliberately dwelled for two seconds. This was not broad patrol or exploration.
- A new round erased all temporary collision hypotheses.
- Aim settled at 12px and used a much wider firing permission; the recording's log reports firing with corrected errors up to approximately 18–22px. Those tolerances can cover empty space beside a small body.
- Selecting multiple candidate routes synchronously consumed around 0.9s in a local sample. Repeating that work in the capture/input loop adds pauses.

## Changes

- A separate mission planner chooses reachable candidates, remembers visits across rounds within the match, avoids repeating the previous plant if another reachable candidate exists, and keeps its choice until completion or a state change. Four A-floor plant candidates and bounded approach detours replace the single initial plant point.
- CT patrol spans seven A-side/approach destinations. T support and post-plant guard use separate candidate sets. This is exploration of accessible regions; no hidden enemy coordinates are inferred.
- A planted bomb immediately cancels CT patrol and any obsolete background result. Search visits nearby reachable A candidates without repeating them until the search pass is exhausted. Confirmed defuse progress survives a missed HUD frame; death, state changes and input leases still release E.
- Mission and path preparation run on one background worker with isolated planner state. Patrol/approach successors are prepared during travel. The controller accepts the prepared path only when it still matches the goal and the current walkable geometry, joining it from the measured position.
- Passage goals advance at 14 map pixels without the old two-second dwell. Plant/defuse still stop at the interaction location. Fresh-pose and obstacle checks remain active.
- Same-match round resets preserve only unexpired collision hypotheses; all pose, input and route-progress state resets. A new match clears the memory. Confirmed prolonged route failures try another mission candidate.
- Wingman aim now settles at 1.5px (movement hysteresis 1/2px; unlock 3px). The firing gate scales with the detected target size around its measured aim point, caps at 8px for bodies/5px for heads, and accounts for camera commands since capture. Invalid/stale boxes cannot authorize firing. Leaving that region releases fire immediately. Fixed the shared fire controller's extra-frame delay when configured with zero release grace; positive DM grace is unchanged.

## Limits that remain

The walkable mask is unchanged. The previously excluded west-side shortcut is still excluded. Different destinations/staging points do **not** create a second certified physical entrance through that blocked area. Additional passages, height transitions and every new plant candidate require live traversal/plant validation. Unsuccessful planting tries another candidate.

Own-player GSI provides planted state, not an exact bomb position. CT therefore searches A; reliable defuse at every possible bomb location is not proven. A detection rectangle is not a player silhouette and this update cannot verify model accuracy or mouse sensitivity on the Windows PC. HUD/pose loss can still require a stop. Do not describe this build as perfect or live-validated.

## Install and verify

Stop the panel and bot. Extract `wingman-inferno-fix-4.zip` into the existing `R.I.P.-Panel` folder, replacing included files. The archive does not contain accounts, tokens, model weights or Python environments. Do not delete or reinstall the existing environments.

Use the same Wingman test launch as before. The startup navigation identity must contain `wingman_missions_v4` and `wingman-inferno-fix-4`. Logs now include `mission=... target=... side=...` and `mission_unreachable` when a destination is rejected.

For live acceptance, record several T and CT rounds, at least two successful plants at different candidates, a CT round with a planted bomb, and small/distant enemy encounters. Check that CT leaves the previous three-point A loop, the plant remains within the actual plant zone, fire waits for central alignment, and no stale patrol resumes after the bomb event. Local tests do not establish those live outcomes.
