"""Exclusive, bounded camera preparation for close-range use interaction."""
import math


class ObjectiveLook:
    def __init__(self,counts_per_degree):
        self.scale=counts_per_degree
        self.reset()

    def reset(self):
        self.yaw_left=0.
        self.pitch_left=0.
        self.pitch_sent=0
        self.last_at=None
        self.restoring=False
        self.active=False

    def begin(self,yaw_error,*,now):
        self.reset()
        self.active=True
        self.yaw_left=max(-180.,min(180.,yaw_error))*self.scale
        # Relative look-down; only accepted pitch deltas are later undone.
        self.pitch_left=65*self.scale
        self.last_at=now

    def restore(self):
        self.active=False
        self.restoring=self.pitch_sent!=0
        self.yaw_left=self.pitch_left=0.

    def tick(self,emit,*,now,confirmed=False):
        dt=min(.1,max(0.,now-(self.last_at if self.last_at is not None else now)))
        self.last_at=now
        if dt<=0:return False
        if self.restoring:
            dx=0;dy=-int(math.copysign(min(abs(self.pitch_sent),200*self.scale*dt),self.pitch_sent))
        elif self.active and not confirmed:
            dx=int(math.copysign(min(abs(self.yaw_left),240*self.scale*dt),self.yaw_left))
            dy=int(min(self.pitch_left,170*self.scale*dt))
        else:return False
        if not dx and not dy:return False
        if not emit(dx,dy):return False
        self.pitch_sent+=dy
        if self.restoring:
            if self.pitch_sent==0:self.reset()
        else:
            self.yaw_left-=dx;self.pitch_left-=dy
        return True
