import time
from types import SimpleNamespace
import numpy as np
from modules.wingman.telemetry import GameState
from modules.wingman.engine import RoundEngine
from tests.test_wingman_live import payload


def test_actual_gsi_over_counter_does_not_close_next_round():
    state=GameState();engine=RoundEngine()
    for n in range(5):
        for phase,raw_number in [('freezetime',n),('live',n),('over',n+1)]:
            assert state.accept(payload(map={'round':raw_number},round={'phase':phase}))
            o=state.snapshot().observation
            assert o.round_number==n
            decision=engine.update(o,now=time.monotonic())
            assert decision.state=={'freezetime':'buy','live':'live','over':'round_inactive'}[phase]


def test_model_metadata_reorders_classes_and_rejects_unknown(csgobot_path):
    from aiming.wingman_teams import filter_detections
    frame=np.zeros((720,1280,3),np.uint8)
    boxes={'c':[{'cls':0,'conf':.9,'xyxy':[400,200,450,400]}],
           't':[{'cls':1,'conf':.9,'xyxy':[600,200,650,400]}]}
    result,_=filter_detections(boxes,frame,{0:'t',1:'c'},'T')
    assert list(result)==['c'] and result['c'][0]['cls']==1
    assert not filter_detections(boxes,frame,{0:'person'},'T')[0]


def test_friendly_body_vetoes_misclassified_enemy_head(csgobot_path):
    from aiming.wingman_teams import filter_detections
    frame=np.zeros((720,1280,3),np.uint8)
    boxes={'t':[{'cls':2,'xyxy':[400,200,500,450]}],
           'ch':[{'cls':1,'xyxy':[425,190,470,240]}]}
    assert not filter_detections(boxes,frame,{0:'c',1:'ch',2:'t',3:'th'},'T')[0]


def test_visible_teammate_name_vetoes_wrong_body_class(csgobot_path):
    from aiming.wingman_teams import filter_detections
    frame=np.zeros((720,1280,3),np.uint8)
    import cv2
    cv2.putText(frame,'TEAM',(430,180),cv2.FONT_HERSHEY_SIMPLEX,.4,(90,220,240),1)
    boxes={'c':[{'cls':0,'xyxy':[400,200,500,450]}]}
    assert not filter_detections(boxes,frame,{0:'c',1:'ch',2:'t',3:'th'},'T')[0]


def test_unlabelled_enemy_remains_eligible(csgobot_path):
    from aiming.wingman_teams import filter_detections
    boxes={'c':[{'cls':0,'xyxy':[400,200,500,450]}]}
    assert filter_detections(boxes,np.zeros((720,1280,3),np.uint8),{0:'c',1:'ch',2:'t',3:'th'},'T')[0]


def test_video_competitive_icon_and_occluded_marker(csgobot_path):
    from pathlib import Path
    from PIL import Image
    from nav.minimap_reader import MinimapReader
    from nav.calibration import load_calibration
    from nav.paths import resolve_calibration_path
    root=Path(__file__).parent/'fixtures/wingman/regression_v2'
    reader=MinimapReader(load_calibration(resolve_calibration_path()))
    frame=np.array(Image.open(root/'170.png'))
    assert not reader.read(frame).valid
    reader.competitive_markers=True
    assert reader.read(frame).valid
    assert not reader.read(np.array(Image.open(root/'120.png'))).valid


def test_recorded_teammate_veto(csgobot_path):
    from pathlib import Path
    from PIL import Image
    from aiming.wingman_teams import filter_detections
    frame=np.array(Image.open(Path(__file__).parent/'fixtures/wingman/regression_v2/65.png'))
    result,reason=filter_detections({'c':[{'cls':0,'xyxy':[480,302,760,715]}]},frame,
                                  {0:'c',1:'ch',2:'t',3:'th'},'T')
    assert not result and reason=='teammate_veto'
