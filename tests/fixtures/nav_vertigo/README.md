# Vertigo floor/appearance regressions

Radar crops at 77 s (upper) and 109 s (lower) from user recording `2026-09-13 16-56-44.mp4`. They were not included in the even-second runtime atlas; neighbouring video frames were used for calibration, so these are same-recording checks, not independent live validation.

The tests verify current-frame localization and floor selection, plus rejection of blank/noisy views and unrelated map HUDs. The original recordings are not required to run them. The production matcher checks full-resolution edges; scene-gradient-compensated appearance uses spatially distributed samples.
