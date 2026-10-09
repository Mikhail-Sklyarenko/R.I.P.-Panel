"""Nuke floor identity from separate geometric hypotheses on the current HUD.

Wingman rendering omits much of the full-map background. A broad photometric
score alone is therefore not a veto against otherwise unique floor geometry.
Conflicting accepted floor hypotheses remain unknown; no goal/spawn hint votes.
"""
from dataclasses import replace
import cv2
import numpy as np
from nav.dense_localizer import DenseMapMatcher
from nav.layered_localizer import select_layer, appearance_score
from nav.paths import resolve_map_radar_path


def choose_floor(rgb,mask,candidates,radars):
    photometric=select_layer(rgb,mask,candidates,radars)
    if photometric is not None:return photometric
    accepted={name:r for name,r in candidates.items() if r is not None and
              r.confidence>=.80 and r.inliers>=10 and r.residual_px<=2.}
    if len(accepted)!=1:return None
    name,result=next(iter(accepted.items()))
    other=candidates.get('upper' if name=='lower' else 'lower')
    if other is not None and other.confidence>=.60:return None
    return replace(result,layer_id=name)


class NukeDenseMatcher:
    def __init__(self,upper):
        lower=cv2.imdecode(np.frombuffer(resolve_map_radar_path('de_nuke_lower').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        if lower is None:raise ValueError('Nuke lower radar missing')
        self.radars={'upper':upper,'lower':cv2.cvtColor(lower,cv2.COLOR_BGR2RGB)}
        self.matchers={name:DenseMapMatcher(rgb,translucent=True) for name,rgb in self.radars.items()}
        from nav.hud_atlas_matcher import HudAtlasMatcher
        self.hud={name:HudAtlasMatcher(mid,upper.shape[:2]) for name,mid in
                  (("upper","de_nuke"),("lower","de_nuke_lower"))}
        self.ramp=HudAtlasMatcher("de_nuke_ramp",upper.shape[:2])
        self.last_layer=None
        self.player_xy=None

    def match_at_scale(self,rgb,mask,scale):
        from nav.visual_localizer import Registration
        candidates={}
        images={"upper":self.radars["upper"],"lower":self.hud["lower"].rgb}
        # Wingman's lower HUD differs from the stock overview. Start with its
        # calibrated rendering and the upper stock overview: two searches in
        # the common path, not four full-map searches per captured frame.
        sources=(("upper",self.matchers["upper"]),("lower",self.hud["lower"]))
        for name,matcher in sources:
            hit=matcher.match_at_scale(rgb,mask,scale)
            if hit is None:continue
            m,c,n=hit
            center=m@np.r_[self.player_xy if self.player_xy is not None else (rgb.shape[1]/2,rgb.shape[0]/2),1.]
            if name=="lower" and center[1]<390 and not self.on_ramp(center):continue
            candidates[name]=Registration(m,c,n,0.,"global_contours",name)
        result=choose_floor(rgb,mask,candidates,images)
        if result is None and not candidates:
            for name,matcher in (("lower",self.matchers["lower"]),("upper",self.hud["upper"])):
                hit=matcher.match_at_scale(rgb,mask,scale)
                if hit is None:continue
                m,c,n=hit
                center=m@np.r_[self.player_xy if self.player_xy is not None else (rgb.shape[1]/2,rgb.shape[0]/2),1.]
                if name=="lower" and center[1]<390 and not self.on_ramp(center):continue
                candidates[name]=Registration(m,c,n,0.,"global_contours",name)
            result=choose_floor(rgb,mask,candidates,
                {"upper":self.hud["upper"].rgb,"lower":self.radars["lower"]})
        if result is None:
            hit=self.ramp.match_at_scale(rgb,mask,scale)
            if hit is not None:
                m,c,n=hit
                center=m@np.r_[self.player_xy if self.player_xy is not None else (rgb.shape[1]/2,rgb.shape[0]/2),1.]
                if self.on_ramp(center):result=Registration(m,c,n,0.,"ramp_atlas","ramp")
        if result is not None:
            center=result.matrix@np.r_[self.player_xy if self.player_xy is not None else (rgb.shape[1]/2,rgb.shape[0]/2),1.]
            if self.on_ramp(center) and (result.layer_id=="lower" or center[1]<370):
                result=replace(result,layer_id="ramp")
        self.last_layer=result.layer_id if result else None
        return (result.matrix,result.confidence,result.inliers) if result else None

    @staticmethod
    def on_ramp(center):
        return 577<=center[0]<=606 and 309<=center[1]<395

    def confirms_layer(self,rgb,mask,matrix,layer):
        center=matrix@np.r_[self.player_xy if self.player_xy is not None else (rgb.shape[1]/2,rgb.shape[0]/2),1.]
        if layer=="ramp":
            # The caller has just matched current geometry against a fixed
            # calibrated anchor. This bounded shaft is a single physical slope,
            # while its HUD fades between upper/lower drawings mid-descent.
            # Requiring either drawing's colour to win here rejects valid XY.
            if not self.on_ramp(center):return False
            if center[1]<370:return True
            # The bottom overlaps the upper bridge in XY; retain an appearance
            # check there, unlike the unique interior of the slope.
            return max(appearance_score(rgb,mask,image,matrix)
                for image in (self.ramp.rgb,self.radars['lower'],self.hud['lower'].rgb))>=.40
        if layer not in self.radars:return False
        if self.on_ramp(center) and (layer=='lower' or center[1]<370):return False
        if layer=="lower" and center[1]<390:return False
        other="lower" if layer=="upper" else "upper"
        # XY was independently tracked against a fixed measured anchor. Check
        # today's floor appearance at that transform, without another global
        # search or carrying a floor purely on elapsed time.
        for images in (self.radars,{n:h.rgb for n,h in self.hud.items()}):
            own=appearance_score(rgb,mask,images[layer],matrix)
            competing=appearance_score(rgb,mask,images[other],matrix)
            if own>=.40 and own-competing>=.10:return True
        return False



class NukeLocalizer:
    def __init__(self,upper):
        from nav.visual_localizer import VisualLocalizer
        self.scanners={'upper':upper,'lower':VisualLocalizer('de_nuke_lower')}
        self.radars={name:s.map_rgb for name,s in self.scanners.items()}
        self.fast=NukeDenseMatcher(upper.map_rgb)
        self.ramp_scanner=VisualLocalizer('de_nuke_ramp')

    def register(self,rgb,mask):
        from nav.visual_localizer import Registration
        hit=self.fast.match_at_scale(rgb,mask,.355)
        if hit is not None:
            m,c,n=hit;return Registration(m,c,n,0.,'global_contours',self.fast.last_layer)
        candidates={name:s._register_single(rgb,mask) for name,s in self.scanners.items()}
        result=choose_floor(rgb,mask,candidates,self.radars)
        if result is not None:
            center=result.matrix@np.array([rgb.shape[1]/2,rgb.shape[0]/2,1.])
            if self.fast.on_ramp(center) and (result.layer_id=="lower" or center[1]<370):
                return replace(result,layer_id="ramp")
            if result.layer_id=="lower" and center[1]<390:return None
            return result
        ramp=self.ramp_scanner._register_single(rgb,mask)
        if ramp is not None and ramp.confidence>=.70 and ramp.source.startswith("ramp_") and ramp.inliers>=10 and ramp.residual_px<=2.:
            center=ramp.matrix@np.array([rgb.shape[1]/2,rgb.shape[0]/2,1.])
            if self.fast.on_ramp(center):return replace(ramp,layer_id="ramp")
        return None
