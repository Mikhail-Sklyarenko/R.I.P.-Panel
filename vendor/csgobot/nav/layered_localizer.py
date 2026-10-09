"""Vertigo floor selection from current pixels, never from route or spawn hints."""
from dataclasses import replace
import cv2
import numpy as np
from nav.dense_localizer import DenseMapMatcher
from nav.paths import resolve_map_radar_path


def appearance_score(rgb, mask, radar, matrix):
    h,w = mask.shape
    valid = mask > 0
    if valid.sum() < 500:
        return 0.
    projected = cv2.warpAffine(radar,matrix,(w,h),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP)
    # Broad appearance is low-frequency evidence. A regular 3-pixel sampling
    # grid preserves spatial coverage while avoiding large BLAS least-squares
    # jobs on the control thread (geometry still uses full-resolution edges).
    step = max(1,round(max(h,w)/80))
    yy,xx = np.mgrid[:h:step,:w:step]
    valid = valid[::step,::step]
    if valid.sum() < 100:
        return 0.
    nuisance = np.column_stack((np.ones(valid.sum()),xx[valid]/w,yy[valid]/h))
    observed = rgb[::step,::step][valid].astype(float)
    expected = projected[::step,::step][valid].astype(float)
    # Fit out a smooth scene/background gradient under the translucent HUD.
    observed -= nuisance @ np.linalg.lstsq(nuisance,observed,rcond=None)[0]
    expected -= nuisance @ np.linalg.lstsq(nuisance,expected,rcond=None)[0]
    energy, base = float((expected*expected).sum()), float((observed*observed).sum())
    if energy < 1 or base < 1:
        return 0.
    alpha = float((observed*expected).sum())/energy
    if not .05 < alpha <= 2:
        return 0.
    return float(1-((observed-alpha*expected)**2).sum()/base)


def select_layer(rgb, mask, candidates, radars):
    verified = {}
    for name, registration in candidates.items():
        if registration is None or registration.inliers < 10:
            continue
        other = 'lower' if name == 'upper' else 'upper'
        own = appearance_score(rgb,mask,radars[name],registration.matrix)
        competing = appearance_score(rgb,mask,radars[other],registration.matrix)
        margin = own-competing
        # SIFT confidence penalises small inlier counts even when broad current
        # map appearance independently verifies their transform. Require both
        # channels before promoting a sparse (>=10 RANSAC inlier) match.
        corroborated = (registration.confidence >= .20 and registration.residual_px <= 2.
                        and own >= .60 and margin >= .20)
        normal = registration.confidence >= .70 and own >= .40 and margin >= .10
        glare = registration.confidence >= .85 and own >= .20 and margin >= .15
        if corroborated or normal or glare:
            verified[name] = replace(registration, layer_id=name,
                confidence=max(registration.confidence,.85) if corroborated else registration.confidence)
    if not verified:
        return None
    if len(verified) == 1:
        return next(iter(verified.values()))
    center = np.array([rgb.shape[1]/2,rgb.shape[0]/2,1.])
    upper,lower = verified['upper'],verified['lower']
    if np.linalg.norm((upper.matrix-lower.matrix)@center) > 20:
        return None
    # Each floor must beat the other at its own measured location. If both
    # explanations survive, do not turn a confidence tie into a floor guess.
    return None


class LayeredLocalizer:
    def __init__(self, upper, lower_map_id="de_vertigo_lower"):
        from nav.visual_localizer import VisualLocalizer
        self.scanners = {'upper':upper, 'lower':VisualLocalizer(lower_map_id)}
        self.radars = {name:scanner.map_rgb for name,scanner in self.scanners.items()}
        self.fast = LayeredDenseMatcher(upper.map_rgb, lower_map_id=lower_map_id)

    def register(self, rgb, mask):
        from nav.visual_localizer import Registration
        fast = self.fast.match_at_scale(rgb,mask,.355)
        if fast is not None:
            matrix,confidence,support = fast
            return Registration(matrix,confidence,support,0.,'global_contours',self.fast.last_layer)
        candidates = {name:scanner._register_single(rgb,mask) for name,scanner in self.scanners.items()}
        return select_layer(rgb,mask,candidates,self.radars)


class LayeredDenseMatcher:
    def __init__(self, upper, lower_map_id='de_vertigo_lower'):
        bgr = cv2.imdecode(np.frombuffer(resolve_map_radar_path(lower_map_id).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError('Lower radar is missing: '+lower_map_id)
        self.radars = {'upper':upper,'lower':cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)}
        self.matchers = {k:DenseMapMatcher(v,translucent=True,
            corroborate=lambda rgb,mask,matrix,layer=k:self.corroborates(rgb,mask,matrix,layer))
            for k,v in self.radars.items()}
        self.last_layer = None

    def match_at_scale(self,rgb,mask,scale):
        from nav.visual_localizer import Registration
        candidates = {}
        for name,matcher in self.matchers.items():
            result = matcher.match_at_scale(rgb,mask,scale)
            if result is not None:
                matrix,confidence,support = result
                candidates[name] = Registration(matrix,confidence,support,0.,'global_contours',name)
        result = select_layer(rgb,mask,candidates,self.radars)
        if result is None and len(candidates)==2:
            # Sky glare corrupts colour while leaving the floor outlines clear.
            # Both floor searches must agree on XY; require a large geometric
            # advantage, not a confidence tie or an assumed spawn floor.
            evidence={k:self.matchers[k].last_evidence for k in candidates}
            if all(evidence.values()):
                name=max(evidence,key=lambda k:evidence[k]['score'])
                other='lower' if name=='upper' else 'upper'
                e=evidence[name]
                center=np.array([rgb.shape[1]/2,rgb.shape[0]/2,1.])
                agreement=np.linalg.norm((candidates[name].matrix-candidates[other].matrix)@center)
                if (agreement<=10 and e['score']>=.72 and e['uniqueness']>=.22
                        and e['score']-evidence[other]['score']>=.12
                        and e['recall']>=.94 and e['precision']>=.80
                        and e['area']>=.30 and e['support']>=500):
                    result=candidates[name]
        self.last_layer = result.layer_id if result else None
        return (result.matrix,result.confidence,result.inliers) if result else None

    def corroborates(self,rgb,mask,matrix,layer):
        other = 'lower' if layer == 'upper' else 'upper'
        own = appearance_score(rgb,mask,self.radars[layer],matrix)
        return own >= .60 and own-appearance_score(rgb,mask,self.radars[other],matrix) >= .20

    def confirms_layer(self,rgb,mask,matrix,layer):
        if layer not in self.radars:
            return False
        scores = {name:appearance_score(rgb,mask,radar,matrix) for name,radar in self.radars.items()}
        other = 'lower' if layer == 'upper' else 'upper'
        return scores[layer] >= .40 and scores[layer]-scores[other] >= .10
