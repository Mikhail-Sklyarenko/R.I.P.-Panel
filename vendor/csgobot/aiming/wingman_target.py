"""Wingman target continuity: prefer a stable body, retain visible opponents.

Only current detections authorize a target. History resolves selection ties;
it never creates a target on a missed frame or overrides teammate filtering.
"""


def overlap(a,b):
    x1=max(a[0],b[0]);y1=max(a[1],b[1]);x2=min(a[2],b[2]);y2=min(a[3],b[3])
    inter=max(0,x2-x1)*max(0,y2-y1)
    union=max(0,a[2]-a[0])*max(0,a[3]-a[1])+max(0,b[2]-b[0])*max(0,b[3]-b[1])-inter
    return inter/max(1.,union)


class WingmanTargetLock:
    def __init__(self):self.reset()

    def reset(self):
        self.previous=None
        self.observed_at=None

    def select(self,selector,detections,*,now,project=None):
        targets=[t for t in selector.filter_enemies(detections)
                 if t.distance<=selector.config.max_assist_distance]
        # A visible body is a stable reference; do not oscillate between its
        # chest and a head whose confidence crosses the priority threshold.
        candidates=[]
        for t in targets:
            if t.is_head and any(not b.is_head and b.x1<=t.aim_x<=b.x2 and
                b.y1-b.height*.15<=t.aim_y<=b.y1+b.height*.45 for b in targets):continue
            candidates.append(t)
        if not candidates:return None
        chosen=None
        if self.previous is not None and 0<=now-self.observed_at<=.18:
            box=self.previous.xyxy
            if project is not None:
                a=project(*box[:2],self.observed_at,now);b=project(*box[2:],self.observed_at,now);box=(*a,*b)
            matches=[(overlap(box,t.xyxy),t) for t in candidates
                     if t.class_name==self.previous.class_name]
            if matches:
                score,t=max(matches,key=lambda pair:pair[0])
                if score>=.20:chosen=t
        if chosen is None:chosen=min(candidates,key=lambda t:t.distance)
        self.previous=chosen;self.observed_at=now
        return chosen
