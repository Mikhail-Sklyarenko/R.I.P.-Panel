"""Finite control permission through a brief localization dropout.

This is a conservative motion envelope, NOT a measured or predicted PoseResult.
It requires live heading evidence and a previously checked straight route.
"""
from dataclasses import dataclass
import math
from nav.coords import normalize_angle_deg


@dataclass(frozen=True)
class HeadingObservation:
    yaw: float
    observed_at: float
    map_id: str


@dataclass(frozen=True)
class CorridorPermit:
    origin: tuple
    yaw: float
    observed_at: float
    expires_at: float
    ground: object
    endpoint: tuple

    @classmethod
    def create(cls,pose,ground,endpoint):
        if (not pose.valid or pose.observed_at is None or pose.confidence<.75
                or not all(math.isfinite(v) for v in (pose.x_norm,pose.y_norm,pose.yaw_deg,pose.observed_at))):
            return None
        point=(pose.x_norm,pose.y_norm)
        if not ground.contains(point):return None
        px,py=ground.pixel(point);ex,ey=ground.pixel(endpoint)
        bearing=math.degrees(math.atan2(ey-py,ex-px))
        if abs(normalize_angle_deg(bearing-pose.yaw_deg))>8:return None
        ahead=math.hypot(ex-px,ey-py)
        # 120 radar px/s is a deliberately generous control bound for Dust2.
        # The entire swept envelope is checked from the ORIGINAL observation,
        # including capture age. No permit can extend itself during a dropout.
        for duration in (.75,.6,.45,.3):
            length=120.*duration+4.
            if length>=ahead:continue  # Never run through the next route corner.
            clear=True
            for delta in (-16.,-12.,-8.,-4.,0.,4.,8.,12.,16.):
                angle=math.radians(pose.yaw_deg+delta)
                end=ground.norm((px+length*math.cos(angle),py+length*math.sin(angle)))
                if not ground.visible(point,end):clear=False;break
            if clear:return cls(point,pose.yaw_deg,pose.observed_at,pose.observed_at+duration,ground,tuple(endpoint))
        return None

    def allows(self,hint,now,ground):
        return (isinstance(hint,HeadingObservation) and hint.map_id=='de_dust2'
                and ground is self.ground
                and all(math.isfinite(v) for v in (now,hint.yaw,hint.observed_at))
                and self.observed_at<=hint.observed_at<=now<self.expires_at
                and 0<=now-hint.observed_at<=.2
                and abs(normalize_angle_deg(hint.yaw-self.yaw))<=8.)
