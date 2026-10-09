"""Exclude the stationary HUD range circle from map-geometry evidence."""
import numpy as np


def exclude_range_ring(mask, cx, cy, radius):
    """Inferno recording's inner ring is 0.73 of the outer radar radius.

    Mask evidence only; never paint floor pixels or change map coordinates.
    A missing ring merely removes a narrow annulus from the available evidence.
    """
    yy, xx = np.ogrid[:mask.shape[0], :mask.shape[1]]
    distance = (xx-cx)**2 + (yy-cy)**2
    width = 4. * radius / 110.
    mask[(distance > (radius*.73-width)**2) &
         (distance < (radius*.73+width)**2)] = 0
    return mask
