"""Real optimizer geometry and production frame scheduling regressions."""
import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import threading
import cv2
import numpy as np
import pytest


@pytest.mark.parametrize('angle',[-3.,0.,3.])
def test_reduced_optimizer_keeps_full_resolution_geometry(csgobot_module_path,angle):
    from nav.reference_tracker import DenseReferenceTracker
    rgb=np.full((256,256,3),25,np.uint8)
    for a,b in [((30,35),(100,95)),((150,35),(210,100)),((45,150),(115,215)),((155,150),(215,210))]:
        cv2.rectangle(rgb,a,b,(150,150,150),-1)
    mask=np.full((256,256),255,np.uint8)
    tracker=DenseReferenceTracker(reduced_alignment=True)
    tracker.seed(rgb,mask,np.eye(2,3),1.)
    transform=cv2.getRotationMatrix2D((128,128),angle,1.)
    transform[:,2]+=(4,-3)
    result=tracker.track(cv2.warpAffine(rgb,transform,(256,256)),mask,1.1)
    assert result is not None
    probes=np.array([[64,64,1],[192,64,1],[128,192,1]])
    error=probes@(result[0]-cv2.invertAffineTransform(transform)).T
    assert np.max(np.linalg.norm(error,axis=1))<.5
    assert tracker._image_anchor[-1]==1.
    assert tracker.track(np.zeros_like(rgb),mask,1.2) is None
    assert tracker.track(rgb,mask,10.) is None


def test_production_frame_nav_overlaps_detection_without_retimestamping():
    tree=ast.parse((Path(__file__).resolve().parents[1]/'vendor/csgobot/main.py').read_text())
    fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='detection_process')
    nodes=list(ast.walk(fn))
    assignments={x.targets[0].id:x for x in nodes if isinstance(x,ast.Assign)
                 and isinstance(x.targets[0],ast.Name) and x.targets[0].id in ('nav_job','nav_result')}
    initialize=next(x for x in nodes if isinstance(x,ast.Assign) and isinstance(x.targets[0],ast.Name)
                    and x.targets[0].id=='nav_job' and isinstance(x.value,ast.Constant))
    submit=next(x for x in nodes if isinstance(x,ast.If) and any(isinstance(y,ast.Call)
                and isinstance(y.func,ast.Attribute) and y.func.attr=='submit' for y in ast.walk(x)))
    detect=next(x for x in nodes if isinstance(x,ast.Assign) and isinstance(x.value,ast.Call)
                and isinstance(x.value.func,ast.Name) and x.value.func.id=='run_combat_detection')
    consume=assignments['nav_result']
    assert initialize.lineno<submit.lineno<detect.lineno<consume.lineno
    entered,detected=threading.Event(),threading.Event()
    frame=np.zeros((8,8,3),np.uint8)
    def update(image,**kwargs):
        assert image is not frame and np.array_equal(image,frame)
        assert kwargs['now']==42.25
        entered.set()
        assert detected.wait(2), 'Nav blocked detection instead of overlapping it'
        return SimpleNamespace(pose=SimpleNamespace(observed_at=kwargs['now']))
    def detection(*args):
        assert entered.wait(2), 'Navigation did not start while detection was running'
        detected.set()
        return [],False
    with ThreadPoolExecutor(max_workers=1) as executor:
        env=dict(nav_executor=executor,nav_perception=SimpleNamespace(update=update),
            nav_reader=object(),nav_pose_filter=object(),activated=SimpleNamespace(is_set=lambda:True),
            config=SimpleNamespace(nav=SimpleNamespace(enabled=True),detector=object(),aim=object()),
            img=frame,captured_at=42.25,previous_nav_combat_hold=False,detector=object(),
            run_combat_detection=detection)
        exec(compile(ast.Module(body=[initialize,submit,detect,consume],type_ignores=[]),'<production>','exec'),env)
        assert env['nav_result'].pose.observed_at==42.25
        assert env['nav_job'].done()
