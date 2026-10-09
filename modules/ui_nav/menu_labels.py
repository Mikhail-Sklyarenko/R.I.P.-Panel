"""Recognize menu lettering, independent of the animated/disabled background.

Uses Pillow already shipped with the panel; no detector-model dependencies.
Coordinates are normalized to the 1280x720 client area, excluding window chrome.
"""
from functools import lru_cache
from PIL import Image, ImageChops
from config.paths import get_app_root

_BOXES={'play':(633,12,685,30),'loadout':(529,12,604,30),'news':(789,12,841,30),
        'matchmaking':(488,52,561,64),'deathmatch':(622,82,692,96)}

# Wingman fleet (RU 1280×720). Ink-ratio fallback until live templates exist.
WINGMAN_BOXES={
    'play':(633,12,685,30),'wingman':(720,78,820,102),'inferno':(470,290,580,330),
    'searching':(560,240,720,290),'confirm':(500,330,780,380),'invite':(520,300,760,360),
    'result':(540,200,740,280),'lobby':(40,80,240,200),
}


def _ink(image,threshold=140):
    return image.convert('L').point(lambda p:255 if p>=threshold else 0,mode='1')


def _count(image):
    return image.histogram()[-1]


@lru_cache(maxsize=8)
def _template(path):
    try:
        with Image.open(path) as image:return _ink(image)
    except OSError as exc:
        from modules.ui_nav.errors import UiNavError
        raise UiNavError(f'Menu label resource unavailable: {path}; install the complete update') from exc


def match_label(frame,name):
    box=_BOXES[name];template=_template(str(get_app_root()/'resources/ui_nav/menu_labels'/f'{name}.png'))
    ink=_count(template);best=(0.,None)
    if ink<10:return best
    for threshold in (140,185):
        binary=_ink(frame,threshold)
        for dy in range(-3,4):
            for dx in range(-5,6):
                shifted=(box[0]+dx,box[1]+dy,box[2]+dx,box[3]+dy)
                crop=binary.crop(shifted);total=_count(crop)
                score=2*_count(ImageChops.logical_and(crop,template))/max(1,ink+total)
                if score>best[0]:best=(score,((shifted[0]+shifted[2])/2,(shifted[1]+shifted[3])/2))
    return best


def _normalized(image):
    return image.convert('RGB').resize((1280,720),Image.Resampling.BILINEAR)


def play_button(image):
    frame=_normalized(image)
    score,point=match_label(frame,'play')
    if score<.72:return None
    # A second word establishes the menu bar, not one bright HUD pixel.
    if max(match_label(frame,'loadout')[0],match_label(frame,'news')[0])<.70:return None
    return round(point[0]*image.width/1280),round(point[1]*image.height/720)


def play_page(image):
    frame=_normalized(image)
    return match_label(frame,'matchmaking')[0]>=.70 and match_label(frame,'deathmatch')[0]>=.70


def deathmatch_selected(image):
    frame=_normalized(image)
    if not play_page(image):return False
    data=frame.crop((618,80,698,101)).tobytes()
    pixels=zip(data[0::3],data[1::3],data[2::3])
    return sum(b-r>12 and g-r>6 for r,g,b in pixels)/(len(data)//3)>.15


def start_button_available(image):
    data=_normalized(image).crop((1022,667,1222,703)).tobytes()
    pixels=zip(data[0::3],data[1::3],data[2::3])
    return sum(g-r>25 and g-b>10 for r,g,b in pixels)/(len(data)//3)>.35


def _flat(image):
    getter=getattr(image,'get_flattened_data',None)
    return list(getter()) if callable(getter) else list(image.getdata())


def wingman_ink(frame,name,threshold=160):
    box=WINGMAN_BOXES[name]
    crop=_normalized(frame).convert('L').crop(box)
    pixels=_flat(crop)
    return sum(1 for p in pixels if p>=threshold)/max(1,len(pixels))


def wingman_label_present(frame,name,min_ratio=0.08):
    if name not in WINGMAN_BOXES:
        return False
    return wingman_ink(frame,name)>=min_ratio
