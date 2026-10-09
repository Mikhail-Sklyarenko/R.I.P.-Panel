"""Match each current radar directly to one independently calibrated live frame.

No frame-to-frame integration: every tracked point retains its original map
anchor. Forward/backward flow, geometry, spatial coverage and image correlation
must all agree. A tracker result cannot become another tracking anchor.
"""
import cv2
import numpy as np


class ReferenceTracker:
    def __init__(self):
        self.anchor = None

    def seed(self, rgb, mask, to_map, now):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        points = cv2.goodFeaturesToTrack(gray, 250, .02, 5, mask=mask, blockSize=5)
        if points is not None and len(points) >= 30:
            self.anchor = (gray, mask.copy(), points, to_map.copy(), now)

    def track(self, rgb, mask, now):
        if self.anchor is None:
            return None
        gray, old_mask, points, to_map, stamp = self.anchor
        if not 0 < now-stamp <= 8 or rgb.shape[:2] != gray.shape:
            return None
        current = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        params = dict(winSize=(21, 21), maxLevel=3,
                      criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, .01))
        moved, ok, _ = cv2.calcOpticalFlowPyrLK(gray, current, points, None, **params)
        if moved is None:
            return None
        back, back_ok, _ = cv2.calcOpticalFlowPyrLK(current, gray, moved, None, **params)
        if back is None:
            return None
        src, dst = points.reshape(-1, 2), moved.reshape(-1, 2)
        good = ok.ravel().astype(bool) & back_ok.ravel().astype(bool)
        good &= np.linalg.norm(back.reshape(-1, 2)-src, axis=1) < .8
        h, w = gray.shape
        good &= np.isfinite(dst).all(axis=1)
        safe = np.rint(np.nan_to_num(dst, nan=-1, posinf=-1, neginf=-1)).astype(int)
        good &= (safe[:, 0] >= 0) & (safe[:, 0] < w) & (safe[:, 1] >= 0) & (safe[:, 1] < h)
        good &= mask[np.clip(safe[:, 1], 0, h-1), np.clip(safe[:, 0], 0, w-1)] > 0
        src, dst = src[good], dst[good]
        if len(src) < 25:
            return None
        transform, flags = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
            ransacReprojThreshold=1.5, maxIters=2000, confidence=.995)
        if transform is None or flags is None or not np.isfinite(transform).all():
            return None
        inliers = flags.ravel().astype(bool)
        count, ratio = int(inliers.sum()), float(inliers.mean())
        if count < 25 or ratio < .8 or not .8 <= np.linalg.norm(transform[:, 0]) <= 1.25:
            return None
        support = dst[inliers]
        if cv2.contourArea(cv2.convexHull(support)) < np.count_nonzero(mask)*.18:
            return None
        quadrants = (support[:, 0] >= w/2).astype(int) + 2*(support[:, 1] >= h/2).astype(int)
        covered = sum(np.count_nonzero(quadrants == q) >= 4 for q in range(4))
        broad = (np.ptp(support[:,0]) >= w*.35 and np.ptp(support[:,1]) >= h*.35
                 and cv2.contourArea(cv2.convexHull(support)) >= h*w*.12)
        if covered < 3 and not (covered >= 2 and broad):
            return None
        projected = cv2.warpAffine(gray, transform, (w, h))
        overlap = (cv2.warpAffine(old_mask, transform, (w, h), flags=cv2.INTER_NEAREST) > 0) & (mask > 0)
        if np.count_nonzero(overlap) < np.count_nonzero(mask)*.45:
            return None
        a, b = projected[overlap].astype(float), current[overlap].astype(float)
        if min(a.std(), b.std()) < 5:
            return None
        correlation = float(np.corrcoef(a, b)[0, 1])
        if not np.isfinite(correlation) or correlation < .85:
            return None
        inverse = cv2.invertAffineTransform(transform)
        matrix = np.column_stack((to_map[:, :2] @ inverse[:, :2],
                                  to_map[:, :2] @ inverse[:, 2] + to_map[:, 2]))
        residual = float(np.median(np.linalg.norm(src[inliers] @ transform[:, :2].T + transform[:, 2]-dst[inliers], axis=1)))
        return matrix, min(.95, ratio*correlation), count, residual


class DenseReferenceTracker(ReferenceTracker):
    """Dense image alignment for verified anchors with too few corner features."""
    def __init__(self, *, reduced_alignment=False):
        super().__init__()
        self.reduced_alignment = reduced_alignment
        self._image_anchor = None

    def seed(self,rgb,mask,to_map,now):
        self.anchor = None
        super().seed(rgb,mask,to_map,now)
        self._image_anchor = (cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY),mask.copy(),to_map.copy(),now)

    def _align(self, template, current, initial, mask, criteria):
        # Solve only the iterative optimizer at half resolution. All spatial,
        # round-trip and bidirectional edge checks below retain full resolution.
        # This does not relax evidence gates or turn old poses into fresh ones.
        if not self.reduced_alignment:
            return cv2.findTransformECC(template,current,initial,cv2.MOTION_AFFINE,
                criteria,inputMask=mask,gaussFiltSize=5)
        shape=(template.shape[1]//2,template.shape[0]//2)
        small_old=cv2.resize(template,shape,interpolation=cv2.INTER_AREA)
        small_new=cv2.resize(current,shape,interpolation=cv2.INTER_AREA)
        small_mask=cv2.resize(mask,shape,interpolation=cv2.INTER_NEAREST)
        transform=initial.copy()
        transform[:,2]*=.5
        corr,transform=cv2.findTransformECC(small_old,small_new,transform,
            cv2.MOTION_AFFINE,criteria,inputMask=small_mask,gaussFiltSize=3)
        transform[:,2]*=2.
        return corr,transform

    def track(self,rgb,mask,now):
        sparse = super().track(rgb,mask,now)
        if sparse is not None:return sparse
        if self._image_anchor is None:return None
        old,old_mask,to_map,stamp = self._image_anchor
        if not 0<now-stamp<=8 or rgb.shape[:2]!=old.shape:return None
        current=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
        if min(float(old.std()),float(current.std()))<5:return None
        criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,40,1e-4)
        initial=np.eye(2,3,dtype=np.float32)
        old_detail=old.astype(np.float32)-cv2.GaussianBlur(old.astype(np.float32),(0,0),5)
        new_detail=current.astype(np.float32)-cv2.GaussianBlur(current.astype(np.float32),(0,0),5)
        shift,response=cv2.phaseCorrelate(old_detail,new_detail,np.float32((old_mask>0)&(mask>0)))
        if response>.2 and np.isfinite(shift).all() and np.linalg.norm(shift)<min(old.shape)*.25:
            initial[:,2]=shift
        try:
            corr,transform=self._align(old,current,initial,mask,criteria)
            if corr<.90 or not np.isfinite(transform).all():return None
            scales=np.linalg.norm(transform[:,:2],axis=0)
            skew=abs(float(np.dot(transform[:,0],transform[:,1])))/max(1e-9,float(np.prod(scales)))
            if (min(scales)<.8 or max(scales)>1.25 or abs(scales[0]-scales[1])>.02
                    or skew>.02 or np.linalg.det(transform[:,:2])<=0):return None
            inverse=cv2.invertAffineTransform(transform)
            back_corr,back=self._align(current,old,inverse.astype(np.float32),old_mask,criteria)
        except cv2.error:
            return None
        h,w=old.shape
        probes=np.array([[w*.2,h*.2],[w*.8,h*.2],[w*.5,h*.8]])
        roundtrip=(probes@transform[:,:2].T+transform[:,2])@back[:,:2].T+back[:,2]
        if back_corr<.90 or np.max(np.linalg.norm(roundtrip-probes,axis=1))>1.:
            return None
        projected=cv2.warpAffine(old,transform,(w,h))
        overlap=(cv2.warpAffine(old_mask,transform,(w,h),flags=cv2.INTER_NEAREST)>0)&(mask>0)
        overlap=cv2.erode(np.uint8(overlap),np.ones((5,5),np.uint8))>0
        if overlap.sum()<np.count_nonzero(mask)*.50:return None
        a,b=cv2.Canny(projected,25,80),cv2.Canny(current,25,80)
        va,vb=(a>0)&overlap,(b>0)&overlap
        if min(va.sum(),vb.sum())<120:return None
        da=cv2.distanceTransform(255-a,cv2.DIST_L2,3)
        db=cv2.distanceTransform(255-b,cv2.DIST_L2,3)
        if np.mean(da[vb]<2)<.85 or np.mean(db[va]<2)<.85:return None
        ys,xs=np.nonzero(vb&(da<2))
        support=np.float32(np.column_stack((xs,ys)))
        if (cv2.contourArea(cv2.convexHull(support))<w*h*.10
                or np.ptp(xs)<w*.35 or np.ptp(ys)<h*.35):return None
        matrix=np.column_stack((to_map[:,:2]@inverse[:,:2],to_map[:,:2]@inverse[:,2]+to_map[:,2]))
        return matrix,min(.95,corr,back_corr),len(xs),0.
