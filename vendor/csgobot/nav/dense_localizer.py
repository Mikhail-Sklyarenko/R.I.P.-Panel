"""Global contour search for north-up radar views with few distinctive keypoints.

The candidate must beat other map locations, explain almost all observed wall
edges and cover a broad two-dimensional region. SIFT remains the general path
for rotating radar. This matcher never uses the route goal or last player XY.
"""
import cv2
import numpy as np


class DenseMapMatcher:
    def __init__(self, map_rgb, *, translucent=False, corroborate=None, rich_hud=False, inferno_hud=False):
        self.translucent = translucent
        self.rich_hud = rich_hud
        self.inferno_hud = inferno_hud
        self.corroborate = corroborate
        self.map_rgb = map_rgb
        self._cache = {}
        self._preferred_scale = None
        self.last_evidence = None

    def _expected(self, scale):
        key = round(float(scale),4)
        if key not in self._cache:
            rgb = cv2.resize(self.map_rgb,None,fx=key,fy=key,interpolation=cv2.INTER_AREA)
            rgb = cv2.copyMakeBorder(rgb,128,128,128,128,cv2.BORDER_CONSTANT)
            edge = cv2.Canny(rgb,25,80).astype(np.float32)/255
            self._cache[key] = cv2.GaussianBlur(edge,(3,3),0)
        return self._cache[key]

    def match(self, rgb, mask):
        # Zoom is a HUD property. Reuse a validated scale, but still search ALL
        # map positions and check competing locations on every frame.
        if self._preferred_scale is not None:
            result = self._measure(rgb,mask,(self._preferred_scale,))
            if result is not None:return result
        return self._measure(rgb,mask)

    def match_at_scale(self,rgb,mask,scale):
        if not np.isfinite(scale) or not .15<=scale<=.50:return None
        return self._measure(rgb,mask,(float(scale),))

    def _measure(self,rgb,mask,scales=None):
        self.last_evidence = None
        result=self._match(rgb,mask,scales)
        if result is None and self.inferno_hud:
            result=self._match(rgb,mask,scales,adapt_contrast=True)
        return result

    def _match(self, rgb, mask, scales=None, *, adapt_contrast=False):
        h,w = rgb.shape[:2]
        if min(self.map_rgb.shape[:2]) < 500 or max(h,w)>256:
            return None
        interior = cv2.erode(mask,np.ones((5,5),np.uint8))>0
        # The translucent Inferno radar can lose contrast over a bright sky.
        # Change edge extraction only; uniqueness and geometric gates still apply.
        low_contrast = False
        if adapt_contrast and self.inferno_hud and np.count_nonzero(interior) >= 1000:
            gray = cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)[interior]
            lo,hi = np.percentile(gray,(5,95))
            low_contrast = 8 <= hi-lo < 40
        if adapt_contrast and not low_contrast:return None
        observed = cv2.Canny(rgb,12,40) if low_contrast else cv2.Canny(rgb,25,80)
        visible = (observed>0)&interior
        if visible.sum()<120:
            return None
        edge = cv2.GaussianBlur(observed.astype(np.float32)/255,(3,3),0)
        edge[mask==0]=0
        candidates=[]
        binary_mask=np.float32(mask>0)
        edge_energy=float(np.sum(edge*edge))
        center=np.array([w/2,h/2,1.])
        def search(scales):
            for scale in scales:
                expected=self._expected(scale)
                if expected.shape[0]<h or expected.shape[1]<w:continue
                numerator=cv2.matchTemplate(expected,edge,cv2.TM_CCORR)
                energy=cv2.matchTemplate(expected*expected,binary_mask,cv2.TM_CCORR)
                denominator=np.sqrt(np.maximum(0.,energy)*edge_energy)
                scores=np.divide(numerator,denominator,out=np.zeros_like(numerator),where=denominator>1e-4)
                scores[~np.isfinite(scores)]=0
                for _ in range(3):
                    _,score,_,xy=cv2.minMaxLoc(scores)
                    matrix=np.array([[1/scale,0.,(xy[0]-128)/scale],
                                     [0.,1/scale,(xy[1]-128)/scale]])
                    candidates.append((score,matrix,scale))
                    cv2.circle(scores,xy,max(6,round(28*scale)),0,-1)
        search(scales if scales is not None else np.arange(.20,.451,.025))
        if not candidates:return None
        coarse=max(candidates,key=lambda c:c[0])[2]
        if scales is None:
            search(np.arange(max(.15,coarse-.025),min(.501,coarse+.026),.005))
        score,matrix,scale=max(candidates,key=lambda c:c[0])
        second=max((c[0] for c in candidates if np.linalg.norm((c[1]-matrix)@center)>28),default=0.)
        appearance_fit = (self.corroborate is not None and score >= .35
            and score-second >= .12 and self.corroborate(rgb,mask,matrix))
        if (score<.50 or score-second<.10) and not appearance_fit:
            return None
        projected=cv2.warpAffine(self.map_rgb,matrix,(w,h),flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP)
        expected=cv2.Canny(projected,25,80)
        dt=cv2.distanceTransform(255-expected,cv2.DIST_L2,3)
        back=cv2.distanceTransform(255-observed,cv2.DIST_L2,3)
        expected_visible=(expected>0)&interior
        if expected_visible.sum()<120:return None
        recall=float(np.mean(dt[visible]<2.))
        precision=float(np.mean(back[expected_visible]<2.))
        support=visible&(dt<2.)
        ys,xs=np.nonzero(support)
        hull=cv2.contourArea(cv2.convexHull(np.float32(np.column_stack((xs,ys))))) if len(xs)>=3 else 0.
        # HUD omits details present in radar.png; unmatched expected detail is
        # allowed only with very high observed recall AND global uniqueness.
        # Transparent Inferno HUD adds scene edges outside the radar geometry.
        # Require stronger uniqueness, bidirectional agreement and broad support
        # before tolerating those unmatched edges. Other profiles keep their gate.
        opaque_fit = recall >= .90 and precision >= .33
        overlay_fit = (self.translucent and score >= .52 and score-second >= .14
                       and recall >= .68 and precision >= .55 and hull >= h*w*.18)
        broad_support = (hull >= h*w*.10 and len(xs) >= 3
                         and np.ptp(xs) >= w*.35 and np.ptp(ys) >= h*.35)
        # Near the map boundary the HUD legitimately contains a narrow strip
        # of floor. A disk-relative span gate rejects even an almost exact
        # match indefinitely. Accept such strips only with stronger global
        # uniqueness and agreement in BOTH directions, and measurable spread
        # across the minor axis; a single wall/line is still insufficient.
        strip_support = False
        if (self.translucent and len(xs) >= 180 and hull >= h*w*.10
                and score >= .68 and score-second >= .20
                and recall >= .90 and precision >= .65
                and np.ptp(xs) >= w*.18 and np.ptp(ys) >= h*.18):
            points = np.column_stack((xs, ys)).astype(np.float64)
            minor_variance = float(np.linalg.eigvalsh(np.cov(points.T))[0])
            strip_support = minor_variance >= (min(h,w)*.035)**2
        # Optional second sensor: a layer-specific photometric verification.
        # Only Vertigo enables this; the other maps retain their original gates.
        corroborated_support = (appearance_fit and recall >= .55 and precision >= .50
            and hull >= h*w*.10 and len(xs) >= 120
            and np.ptp(xs) >= w*.18 and np.ptp(ys) >= h*.18)
        # Dust2's HUD contains details absent from the overview radar. Accept
        # extra observed edges only when almost every EXPECTED edge agrees,
        # across a broad region, and the global candidate is strongly unique.
        rich_support = (self.rich_hud and score >= .50 and score-second >= .18
            and recall >= .50 and precision >= .90 and hull >= h*w*.30
            and len(xs) >= 300 and np.ptp(xs) >= w*.45 and np.ptp(ys) >= h*.45)
        # A red door masks much of the translucent disk as scene colour.
        # Judge the remaining evidence with stricter uniqueness/agreement and
        # two-dimensional spread, not with the area of the unobservable disk.
        masked_support = False
        if (self.inferno_hud and .15*h*w <= np.count_nonzero(mask) < .55*h*w
                and score >= .65 and score-second >= .22
                and recall >= .80 and precision >= .70 and len(xs) >= 180
                and hull >= h*w*.12 and np.ptp(xs)>=w*.25 and np.ptp(ys)>=h*.25):
            points = np.column_stack((xs,ys)).astype(np.float64)
            masked_support = float(np.linalg.eigvalsh(np.cov(points.T))[0]) >= (min(h,w)*.035)**2
        if not (masked_support or rich_support or (opaque_fit or overlay_fit) and broad_support or strip_support or corroborated_support):
            return None
        self._preferred_scale = scale
        self.last_evidence = dict(score=score, uniqueness=score-second,
            recall=recall, precision=precision, area=hull/(h*w), support=len(xs))
        return matrix,min(.90,.65+.2*recall+.05*min(1.,(score-second)/.2)),int(support.sum())
