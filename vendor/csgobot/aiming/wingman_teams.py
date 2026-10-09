"""Wingman-only class mapping and visible teammate veto before target selection."""
import numpy as np
import cv2

ALIASES = {'c':'c','ct':'c','counter-terrorist':'c','counter_terrorist':'c',
           'ch':'ch','ct_head':'ch','t':'t','terrorist':'t','th':'th','t_head':'th'}


def class_mapping(names):
    if isinstance(names,list):names=dict(enumerate(names))
    if not isinstance(names,dict):return None
    result={int(k):ALIASES.get(str(v).strip().lower()) for k,v in names.items()}
    # Unknown labels cannot be interpreted using the old fixed class order.
    if not result or any(v is None for v in result.values()):return None
    if not {'c','t'}.issubset(result.values()):return None
    return result


def teammate_label(image,box):
    x1,y1,x2,y2=map(float,box['xyxy']);h=y2-y1;w=x2-x1
    if h<28 or w<8:return False
    # Name/arrow above this body, not a whole-screen colour lookup.
    left=max(0,int((x1+x2)/2-min(100,w*.8)))
    right=min(image.shape[1],int((x1+x2)/2+min(100,w*.8)))
    top=max(60,int(y1-min(85,h*.4)));bottom=max(top,int(y1))
    crop=image[top:bottom,left:right].astype(np.int16)
    if crop.size==0:return False
    r,g,b=crop[:,:,0],crop[:,:,1],crop[:,:,2]
    # Anti-aliased / compressed names can be nearly white. Shape below is
    # mandatory, so colour need not demand saturated cyan glyphs.
    cyan=(g>150)&(b>150)&(r<240)&(g-r>12)&(b-r>12)&(abs(g-b)<65)
    # Colour alone also matches scenery (notably blue objects). Require a
    # horizontal row of small glyph-like components instead of a cyan blob.
    count, labels, stats, centers = cv2.connectedComponentsWithStats(cyan.astype(np.uint8),8)
    glyphs=[]
    for x,y,w,h,area in stats[1:]:
        if 1<=w<=60 and 2<=h<=16 and area>=2 and area/(w*h)<.85:
            glyphs.append((x,y,w,h,area))
    for _,y,_,h,_ in glyphs:
        row=[g for g in glyphs if abs((g[1]+g[3]/2)-(y+h/2))<=3]
        if len(row)<3:continue
        left=min(g[0] for g in row);right=max(g[0]+g[2] for g in row)
        top=min(g[1] for g in row);bottom=max(g[1]+g[3] for g in row)
        if right-left>=12 and right-left>1.8*(bottom-top) and sum(g[4] for g in row)>=12:
            return True
    return False


def filter_detections(detections,image,names,team):
    mapping=class_mapping(names)
    if mapping is None or team not in ('T','CT'):return {},'unverified_model_classes'
    own={'t','th'} if team=='T' else {'c','ch'}
    bodies=[];mapped=[]
    for boxes in detections.values():
        for box in boxes:
            label=mapping.get(int(box.get('cls',-1)))
            if label is None:continue
            mapped.append((label,box))
            if label in ('c','t') and (label in own or teammate_label(image,box)):
                bodies.append(box['xyxy'])
    result={};blocked=0
    for label,box in mapped:
        if label in own:continue
        x1,y1,x2,y2=box['xyxy'];cx=(x1+x2)/2;cy=(y1+y2)/2
        # Also veto a misclassified head attached to a recognised friendly body.
        if any(a<=cx<=c and b-(d-b)*.2<=cy<=d for a,b,c,d in bodies):
            blocked+=1;continue
        result.setdefault(label,[]).append(box)
    return result,('teammate_veto' if blocked else 'verified_classes')
