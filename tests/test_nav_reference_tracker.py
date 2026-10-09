import importlib

import cv2
import numpy as np
import pytest


def image():
    rng = np.random.default_rng(84)
    rgb = np.full((280, 280, 3), 35, np.uint8)
    for _ in range(140):
        x, y = rng.integers(15, 255, 2)
        color = tuple(int(v) for v in rng.integers(70, 240, 3))
        cv2.rectangle(rgb, (int(x), int(y)), (int(x+8), int(y+8)), color, -1)
    return rgb


@pytest.fixture
def tracker(csgobot_module_path):
    return importlib.import_module('nav.reference_tracker').ReferenceTracker()


def test_fixed_anchor_measures_translation_and_rotation_without_chaining(tracker):
    rgb = image()
    mask = np.full(rgb.shape[:2], 255, np.uint8)
    to_map = np.array([[2., 0., 100.], [0., 2., 50.]])
    tracker.seed(rgb, mask, to_map, 1.)
    for t, angle in [(1.1, 3.), (1.2, 5.)]:
        transform = cv2.getRotationMatrix2D((140, 140), angle, 1.)
        transform[:, 2] += (8, -5)
        current = cv2.warpAffine(rgb, transform, (280, 280))
        result = tracker.track(current, mask, t)
        assert result is not None
        matrix, confidence, count, residual = result
        inv = cv2.invertAffineTransform(transform)
        expected = np.column_stack((to_map[:, :2] @ inv[:, :2], to_map[:, :2] @ inv[:, 2]+to_map[:, 2]))
        assert np.linalg.norm((matrix-expected) @ np.array([140, 140, 1])) < 1
        assert confidence > .75 and count >= 25
        assert tracker.anchor[-1] == 1.  # Same independent anchor for each frame.


def test_tracker_rejects_unrelated_blank_and_expired_images(tracker):
    rgb = image()
    mask = np.full(rgb.shape[:2], 255, np.uint8)
    tracker.seed(rgb, mask, np.eye(2, 3), 1.)
    assert tracker.track(np.zeros_like(rgb), mask, 1.1) is None
    noise = np.random.default_rng(91).integers(0, 255, rgb.shape, dtype=np.uint8)
    assert tracker.track(noise, mask, 1.2) is None
    assert tracker.track(rgb, mask, 10.) is None
    assert tracker.track(rgb, np.zeros_like(mask), 1.2) is None


def test_tracker_rejects_single_corner_support(tracker):
    rgb = image()
    mask = np.zeros(rgb.shape[:2], np.uint8)
    mask[:120, :120] = 255
    tracker.seed(rgb, mask, np.eye(2, 3), 1.)
    assert tracker.track(rgb, mask, 1.1) is None


def test_localizer_uses_fresh_tracking_but_never_reanchors_it(csgobot_module_path, tmp_path):
    from nav.visual_localizer import VisualLocalizer
    from nav.pose import PoseResult
    rgb = image()
    mask = np.full(rgb.shape[:2], 255, np.uint8)
    loc = VisualLocalizer('test', map_rgb=rgb, profile_dir=tmp_path)
    loc._tracker.seed(rgb, mask, np.eye(2, 3), 1.)
    def missing(*args):
        loc.reason = 'no_geometric_match'
        return None
    loc.register = missing
    transformed = cv2.warpAffine(rgb, np.array([[1., 0., 8.], [0., 1., -5.]]), (280, 280))
    icon = PoseResult(.5, .5, 0, .9, True, 30, 'classic')
    assert not loc.locate(transformed, mask, (140, 140), icon, now=1.1).valid
    p = loc.locate(transformed, mask, (140, 140), icon, now=1.2)
    assert p.valid and p.observed_at == 1.2
    assert abs(p.x_norm*279-132) < 1 and abs(p.y_norm*279-145) < 1
    assert loc.last_registration.source == 'fixed_frame_track'
    assert loc._tracker.anchor[-1] == 1.
    assert not loc.locate(transformed, mask, (140, 140), icon, now=10.).valid


def test_dense_tracking_handles_few_corners_without_chaining(csgobot_module_path):
    from nav.reference_tracker import DenseReferenceTracker
    rgb=np.full((256,256,3),25,np.uint8)
    for a,b in [((30,35),(100,95)),((150,35),(210,100)),((45,150),(115,215)),((155,150),(215,210))]:
        cv2.rectangle(rgb,a,b,(150,150,150),-1)
    mask=np.full((256,256),255,np.uint8)
    tracker=DenseReferenceTracker();tracker.seed(rgb,mask,np.eye(2,3),1.)
    transform=cv2.getRotationMatrix2D((128,128),2.,1.);transform[:,2]+=(4,-3)
    current=cv2.warpAffine(rgb,transform,(256,256))
    result=tracker.track(current,mask,1.1)
    assert result is not None
    expected=cv2.invertAffineTransform(transform)
    assert np.linalg.norm((result[0]-expected)@np.array([128,128,1]))<1
    assert tracker._image_anchor[-1]==1.
    assert tracker.track(np.zeros_like(rgb),mask,1.2) is None
    assert tracker.track(rgb,mask,10.) is None
