from pathlib import Path
import cv2,numpy as np,json,hashlib
import argparse
parser=argparse.ArgumentParser(description='Rebuild calibrated Mirage underpass mask and Russian HUD labels')
parser.add_argument('--video',type=Path,required=True)
args=parser.parse_args()
r=Path(__file__).resolve().parents[1];p=r/'resources/nav/profiles/de_mirage';(p/'level_labels').mkdir(exist_ok=True)
expected=json.loads((p/'atlas.json').read_text())['source_sha256']
if hashlib.sha256(args.video.read_bytes()).hexdigest()!=expected:
 raise ValueError('Expected the original calibrated Mirage recording')
c=cv2.VideoCapture(str(args.video))
def mask(rgb):
 gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY).astype(np.float32)
 color=(rgb[:,:,0].astype(float)>130)&(rgb[:,:,1]>100)&(rgb[:,:,2]<195)&(rgb[:,:,1].astype(float)>rgb[:,:,2].astype(float)*1.18)
 detail=gray-cv2.GaussianBlur(gray,(0,0),2)
 return np.uint8(color&(detail>5))*255
refs=[]
for name,t,layer in [('underpass',196,'lower'),('ledge',164,'upper'),('ladder',154,'upper'),('house',192,'upper'),('alley',194,'upper'),('mid',202,'upper')]:
 c.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,f=c.read();assert ok
 band=cv2.cvtColor(f[254:283,:240],cv2.COLOR_BGR2RGB);binary=mask(band)
 # Text is centered under the radar. Ignore unrelated bright screen edges.
 bounds={'underpass':(48,152),'ledge':(80,120),'ladder':(70,131),'house':(84,117),'alley':(64,137),'mid':(78,123)}
 left,right=bounds[name]
 binary[:,:left]=0;binary[:,right:]=0;binary[:7]=0;binary[23:]=0
 ys,xs=np.nonzero(binary);assert len(xs)>50
 a,b=max(0,xs.min()-2),min(240,xs.max()+3);top,bottom=max(0,ys.min()-2),min(29,ys.max()+3)
 target=binary[top:bottom,a:b]
 cv2.imwrite(str(p/'level_labels'/f'{name}.png'),target)
 refs.append({'image':f'level_labels/{name}.png','layer':layer,'source_second':t})
route=[(570,254),(454,258),(440,281),(443,395),(447,444),(461,463),(503,469)]
image=np.zeros((1024,1024),np.uint8);cv2.polylines(image,[np.array(route,np.int32)],False,255,28,lineType=cv2.LINE_8)
for point in route:cv2.circle(image,point,14,255,-1)
cv2.imwrite(str(p/'underpass_walkable.png'),image)
upper=cv2.imread(str(p/'walkable.png'),cv2.IMREAD_GRAYSCALE)
entry=np.array([(595,237),(585,246),(574,252),(562,255),(537,258),(504,258)],np.int32)
cv2.polylines(upper,[entry],False,255,28,lineType=cv2.LINE_8)
cv2.imwrite(str(p/'upper_entry_walkable.png'),upper)
data={'map_id':'de_mirage','version':1,'coordinate_system':'radar_pixels','layers':{'upper':'upper_entry_walkable.png','lower':'underpass_walkable.png'},'clearance_px':6,'grid_step':2,'label_roi':[0,254,240,283],'labels':refs,'language':'ru','underpass_route':route,'lower_exits':[{'id':'alley','point':[558,255]},{'id':'mid','point':[493,467]}],'upper_entries':[{'id':'alley','point':[504,258]},{'id':'mid','point':[447,436]}],'source_video':'2026-09-13 16-49-19.mp4','source_seconds':[194,202],'live_validated':False,'limitations':['Lower floor identified by Russian HUD location labels inside the overlapping corridor; unknown labels cannot authorize an ambiguous spawn.','The lower mask is a corridor around the measured traversal, not a full 3D navmesh.']}
(p/'layers.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
print([(x['image'],cv2.imread(str(p/x['image']),0).shape) for x in refs])
