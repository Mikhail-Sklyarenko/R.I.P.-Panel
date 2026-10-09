"""Read the visible own direction tip separately from a planted-C4 overlay.

Requires the live Wingman/planted context and a centered radar. The display
rectangle is removed from the heading pixels; it is never used as a direction.
No previous yaw or mouse command is substituted for a visible tip.
"""
import math
import numpy as np


def c4_displays(white,cx,cy):
    choices=[]
    for y in range(max(0,int(cy)-18),min(white.shape[0]-7,int(cy)+14)):
        for x in range(max(0,int(cx)-18),min(white.shape[1]-10,int(cx)+14)):
            if white[y,x:x+10].sum()<9:continue
            for height in (6,7):
                roi=white[y:y+height,x:x+10]
                if roi.shape!=(height,10):continue
                if (roi[0].sum()<9 or roi[-1].sum()<9 or
                        roi[:,0].sum()<height-1 or roi[:,-1].sum()<height-1):continue
                if not 3<=np.count_nonzero(~roi[1:-1,1:-1])<=22:continue
                if math.hypot(x+4.5-cx,y+(height-1)/2-cy)>18:continue
                choices.append((int(roi.sum()),x,y,height))
    return [(x,y,10,h) for _,x,y,h in sorted(choices,reverse=True)]


def c4_display(white,cx,cy):
    boxes=c4_displays(white,cx,cy)
    return next((box for box in boxes if math.hypot(
        box[0]+4.5-cx,box[1]+(box[3]-1)/2-cy)<=4),None)


def observe_objective_tip(rgb,cx,cy,colored):
    values=rgb.astype(np.int16)
    minimum=values.min(2);chroma=values.max(2)-minimum
    white=(minimum>=200)&(chroma<=65)
    displays=c4_displays(white,cx,cy)
    display=next((box for box in displays if math.hypot(
        box[0]+4.5-cx,box[1]+(box[3]-1)/2-cy)<=4),None)
    yy,xx=np.ogrid[:rgb.shape[0],:rgb.shape[1]]
    radius2=(xx-cx)**2+(yy-cy)**2
    body=colored & (radius2<=6**2)
    # Without the distinctive C4 display require a substantial own colored
    # body, not a tiny fragment plus a pale map edge/nearby teammate.
    if display is None and np.count_nonzero(body)<20:return None,None
    # The marker center is a measured, stabilized HUD center. A fragmented
    # colored body beside C4 must not shift world XY or the heading origin.
    for threshold,color_range in ((210,45),(175,80),(165,90)):
        pale=(minimum>=threshold)&(chroma<=color_range)
        # After moving away, C4 slides across our arrow instead of staying
        # centered. Remove its full glyph (including antialiasing), but only
        # a centered C4 may stand in for an occluded own body.
        for x,y,w,h in displays:
            pale[max(0,y-1):y+h+1,max(0,x-1):x+w+1]=False
        ty,tx=np.where(pale & (radius2>=5**2)&(radius2<=10**2))
        if not 3<=len(tx)<=35:continue
        dx=float(tx.mean())-cx;dy=float(ty.mean())-cy
        coherence=math.hypot(dx,dy)/float(np.mean(np.hypot(tx-cx,ty-cy)))
        if coherence>=.92:
            return (math.degrees(math.atan2(dy,dx)),min(.9,coherence)),display
    return None,display
