"""Easing helpers for patrol look sweeps."""


def smoothstep(t: float) -> float:
    """Hermite ease-in-out on [0, 1]."""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def smootherstep(t: float) -> float:
    """Perlin smootherstep — softer start/stop than smoothstep."""
    t = max(0.0, min(1.0, t))
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
