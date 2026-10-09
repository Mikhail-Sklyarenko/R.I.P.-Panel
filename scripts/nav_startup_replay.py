#!/usr/bin/env python3
"""Stationary-video startup integration check with intercepted mouse and keys."""
from pathlib import Path
import sys,time,json,cv2
from types import SimpleNamespace
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'vendor/csgobot'))
from nav.map_selector import AsyncVisualMapSelector
from nav.calibration import load_calibration
from nav.paths import resolve_calibration_path,resolve_nav_pack_path
from nav.minimap_reader import MinimapReader
from nav.place_localizer import PlaceLocalizer
from nav.async_perception import AsyncVisualPerception
from nav.pose_filter import PoseFilter
from nav.pack import load_nav_pack
from nav.pack_resolve import nav_pack_for_script,measured_runtime_pack
from nav.farm_runtime import create_navigation,CameraOwnership
import argparse
parser=argparse.ArgumentParser(description='Replay map discovery through first navigation command; never sends game input')
parser.add_argument('--video',type=Path,required=True)
parser.add_argument('--start',type=float,default=44.)
parser.add_argument('--timeout',type=float,default=30.)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
if args.start<0 or not 1<=args.timeout<=120:parser.error('Invalid start or timeout')
cv2.setNumThreads(1)
video=cv2.VideoCapture(str(args.video));video.set(cv2.CAP_PROP_POS_MSEC,args.start*1000);ok,bgr=video.read();video.release();assert ok
frame=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB);cal=load_calibration(resolve_calibration_path());selector=AsyncVisualMapSelector(cal);perception=AsyncVisualPerception(MinimapReader(cal),PlaceLocalizer('de_dust2'));filt=PoseFilter(cal.pose)
keys=set();events=[];ticks=[];owner=CameraOwnership(lambda *args:None,lambda:True);owner.select('combat')
controller=create_navigation(load_nav_pack(resolve_nav_pack_path('dust2_visual_mvp')),SimpleNamespace(fov=SimpleNamespace(x360=7792)),keys.add,keys.discard,owner,expanded=True,watchdog=False)
start=time.monotonic();confirmed=False;first_pose=None;durations=[]
try:
 while time.monotonic()-start<args.timeout:
  now=time.monotonic();t=time.perf_counter()
  if not confirmed:
   candidate=selector.update(frame,now=now)
   durations.append(time.perf_counter()-t)
   if candidate:
    assert candidate=='de_inferno',candidate
    events.append({'event':'map_confirmed','seconds':now-start,'map':candidate})
    pack=load_nav_pack(resolve_nav_pack_path(measured_runtime_pack(nav_pack_for_script('inferno'),'auto')));controller.reload_pack(pack);perception.localizer=PlaceLocalizer(candidate);perception.reload_map(candidate);filt.reset();selector.reset();confirmed=True;owner.select('nav')
  if confirmed:
   result=perception.update(frame,now=now)
   pose=filt.update(result.pose,now=time.monotonic())
   if pose.valid and first_pose is None:first_pose=time.monotonic()-start
   tick_start=time.perf_counter()
   state=controller.tick(pose,now=time.monotonic(),paused=False)
   ticks.append(dict(seconds=time.monotonic()-start,reason=state.reason,perception=perception.reason,valid=pose.valid,tick_ms=(time.perf_counter()-tick_start)*1000))
   if keys:
    events.append({'event':'movement','seconds':time.monotonic()-start,'keys':sorted(keys),'reason':state.reason});break
  time.sleep(.05)
finally:
 selector.close();perception.close();controller.close()
report={'scenario':'stationary Inferno video frame, unknown map/Dust2 bootstrap, discovery during combat ownership then combat release; fake input only','events':events,'ticks':ticks,'first_valid_pose_sec':first_pose,'max_discovery_poll_ms':max(durations)*1000,'passed':any(e['event']=='movement' for e in events)}
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='ticks'},indent=2));assert report['passed']
