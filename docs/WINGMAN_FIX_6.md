# Wingman Inferno fix 6

This update uses the supplied `2026-09-20 20-01-41.mp4` walkthrough (484 seconds) to add T-side approaches through long, short and apartments. It extends fix 5; shooting configuration and detector weights are unchanged.

## Evidence and geometry

The full recording was surveyed at 10-second intervals. Short/long segments and the apartment stair/corridor/balcony transitions were sampled more densely, including 214–226 seconds. `ingress_evidence.json` preserves sampled registration results and the later centered-radar review. This is not a frame-by-frame validation or a replay of live movement physics.

The previous short exclusion was too broad. Only the recorded southern corridor is reopened; the previously failing direct link from (730,730) to (802,726) remains blocked. Apartment stairs, interior and balcony use a separate outbound corridor. This corridor is enabled after a measured T-side entry, remains committed until a measured A-side exit, and is never advertised as general ground connectivity or an inbound CT route.

At 218 seconds the icon reader mistook the cyan teammate above the center for the player because the player's own direction tip was obscured. Competitive centered-radar selection now rejects distant candidates. It reports uncertainty instead of substituting a teammate; it does not fabricate a live pose from the radar center. Apartment calibration was revised using center projection on the visually inspected centered-radar recording. Sparse intervals still require interpolation.

## Behavior

- T approach selection balances long, short and apartments across rounds and avoids immediately repeating the last route when another is reachable.
- The chosen approach remains committed while traversing its corridor, then returns to ordinary plant/support missions on A.
- The apartment balcony has a direction-specific short jump without forced crouching. Attempts are bounded; loss of input permission releases the keys.
- A new round cancels the commitment and restores normal ground geometry. Apartment collision hypotheses do not leak into ground routes next round.
- CT missions and the DM route resources are unchanged. Shared traversal code gains an explicit jump-only action; existing crouch/jump actions retain their behavior.

## Validation and limits

The regression suite covers Wingman round transitions, route selection, all three approaches in a 2D movement simulation, directional jumping, the recorded wrong-marker frame, DM and existing map navigation. Each simulated step is checked against the route mask. This verifies controller/mask consistency; it cannot prove that a drawn mask matches all physical collisions or height changes in CS2.

No live Windows/CS2 traversal is claimed. Stair and balcony physics, localization continuity under occlusion, and real obstacle recovery still require an in-game run. The unchanged HTTP receiver socket lifecycle test is excluded in the restricted environment. The release manifest records the completed test count.

## Installation

Close the panel and bot. Extract `wingman-inferno-fix-6.zip` into the existing `R.I.P.-Panel` directory, replacing included files. Keep existing environments, model weights, accounts and GSI configuration. Launch Wingman using the same command as before.

The log must show `wingman_fix_6`, profile `wingman-inferno-fix-6`, and `ingress_routes` containing `apartments`, `long`, `short`. During T rounds, `ingress=<route> status=started` and `status=finished` report actual route transitions. Record several T rounds to cover all branches and retain the log if a transition does not finish.
