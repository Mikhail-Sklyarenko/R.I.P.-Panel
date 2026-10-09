#!/usr/bin/env python3
"""Audit stock HUD observations against the experimental ground, without input."""
import json
from pathlib import Path
from nav_acceptance import check, ROOT
from nav.walkable import WalkableMap
import cv2
import numpy as np

def audit():
    base=check()
    ground=WalkableMap.load('de_dust2',ROOT/'resources/nav/experimental/de_dust2')
    _,labels=cv2.connectedComponents(np.uint8(ground.free),connectivity=4)
    for row in base['frames']:
        point=(row['x'],row['y'])
        row['inside_expanded_ground']=bool(row['accepted'] and ground.contains(point))
        if row['inside_expanded_ground']:
            x,y=ground.pixel(point);row['component']=int(labels[round(y),round(x)])
    return {'experimental':True,'full_map_ready':False,'live_validated':False,
            'reason':'Stock calibration frames are not independent random-spawn validation',
            'frames_total':len(base['frames']),'localized':base['frames_accepted'],
            'localized_inside_ground':sum(r['inside_expanded_ground'] for r in base['frames']),
            'frames':base['frames']}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'data/dust2_expanded_audit.json')
    args=p.parse_args();report=audit();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='frames'},indent=2))
