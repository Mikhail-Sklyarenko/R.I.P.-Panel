Radar crop at 100 seconds of the user-provided Dust2 bot test
`2026-09-15 17-54-09.mp4` (1280x720, 60 FPS).

`100_mask.png` excludes the range annulus for overview contour registration.
`100_hud_mask.png` retains it for matching against the original calibrated HUD
appearance. Both exclude the player marker, saturated annotations and crop rim.

This regression fixture is NOT added to the runtime atlas. Its map position is
approximately (700,637) in the existing 1024px radar coordinate system, consistent
with the previously calibrated Long doors HUD reference. Tests verify measurement
and map rejection, not live traversal or independent full-map accuracy.
