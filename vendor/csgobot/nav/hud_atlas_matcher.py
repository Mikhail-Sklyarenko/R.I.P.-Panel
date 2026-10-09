"""Independent whole-map measurements in the calibrated HUD rendering style."""
import json
import cv2
import numpy as np
from nav.dense_localizer import DenseMapMatcher
from nav.layered_localizer import appearance_score
from nav.paths import resolve_visual_profile_file


class HudAtlasMatcher:
    def __init__(self, map_id, shape, profile_dir=None):
        manifest = (profile_dir/'atlas.json' if profile_dir is not None else
                    resolve_visual_profile_file(map_id,'atlas.json'))
        height,width=shape
        accumulated=np.zeros((height,width,3),np.float32)
        weight=np.zeros((height,width),np.float32)
        data=json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('map_id') != map_id:
            raise ValueError('HUD atlas map_id mismatch')
        for reference in data.get('references',[]):
            path=(manifest.parent/reference['image']).resolve()
            if not path.is_relative_to(manifest.parent.resolve()):
                raise ValueError('HUD atlas image outside profile')
            bgr=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
            if bgr is None:raise ValueError('Unreadable HUD atlas image')
            rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
            matrix=np.asarray(reference['to_map'],float)
            if matrix.shape!=(2,3) or not np.isfinite(matrix).all():
                raise ValueError('Invalid HUD atlas transform')
            valid=cv2.erode(np.float32(np.any(rgb>8,axis=2)),np.ones((5,5),np.uint8))
            accumulated+=cv2.warpAffine(rgb.astype(np.float32)*valid[:,:,None],matrix,(width,height))
            weight+=cv2.warpAffine(valid,matrix,(width,height))
        self.rgb=np.uint8(accumulated/np.maximum(weight[:,:,None],1e-5))
        self.known=np.float32(weight>.1)
        self.matcher=DenseMapMatcher(self.rgb,translucent=True,
            corroborate=lambda rgb,mask,m:appearance_score(rgb,mask,self.rgb,m)>=.65)

    def match_at_scale(self,rgb,mask,scale):
        result=self.matcher.match_at_scale(rgb,mask,scale)
        if result is None:return None
        # Unknown atlas pixels and patch borders cannot supply a position.
        projected=cv2.warpAffine(self.known,result[0],(rgb.shape[1],rgb.shape[0]),
            flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP)
        if not np.any(mask) or np.mean(projected[mask>0]>.9)<.75:return None
        return result
