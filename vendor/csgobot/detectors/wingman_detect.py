"""Retry the central crop after Wingman eligibility filtering, not before it."""
import numpy as np
from types import SimpleNamespace
from aiming.wingman_teams import filter_detections
from detectors.roi_detect import apply_class_conf_thresholds,detect_roi_pass,merge_detections


def detect_wingman(detector,image,config,team):
    names=getattr(detector.model,'names',None)
    # OBS supplies RGB, whereas Ultralytics predict(ndarray) consumes BGR.
    # Keep the original RGB image for teammate-label inspection.
    rgb_detector=SimpleNamespace(detect=lambda rgb:detector.detect(
        np.ascontiguousarray(rgb[:,:,::-1])))
    thresholds=config.class_confidence_thresholds
    raw=apply_class_conf_thresholds(rgb_detector.detect(image),thresholds)
    eligible,reason=filter_detections(raw,image,names,team)
    roi=False
    if not eligible and reason!='unverified_model_classes' and config.roi_enabled:
        extra=apply_class_conf_thresholds(detect_roi_pass(rgb_detector,image,config.roi_fraction),thresholds)
        # Retain full-frame friendly bodies so a cropped misclassified head
        # cannot bypass the same teammate veto.
        raw=merge_detections(raw,extra)
        eligible,reason=filter_detections(raw,image,names,team)
        roi=True
    counts={name:len(boxes) for name,boxes in raw.items() if boxes}
    return eligible,roi,reason,counts
