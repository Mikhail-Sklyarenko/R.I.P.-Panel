# Inferno boundary regression fixtures

Radar-only crops at 30 and 140 seconds of user recording `2026-09-14 12-52-14.mp4` (1280×720, 60 fps). Masks exclude HUD chrome, player icon, saturated markers and the range ring exactly as the runtime does.

Both crops were rejected by v7 despite unique, bidirectionally supported geometry: the map fills a narrow horizontal or vertical strip rather than 35% of both radar axes. Map transforms in the regression test were inspected by overlaying radar contours on the crops; they are image registrations, not independently measured game coordinates.

These two images are regression evidence, not runtime atlas anchors. The original atlas and walkable mask are unchanged. The remaining video frames are a same-recording check; they are not an independent live trial after the fix.
