import json
from pathlib import Path

from PIL import Image
import numpy as np

READER_VERSION = '2026.10.20.1'
CALIBRATION_PATH = Path(__file__).with_name('calibration.json')

# Default calibration (original 7-segment red LED board), corners TL, TR, BR, BL in a 1920x1080 frame.
DEFAULT_QUADS = {
    'm1': [(1482,413),(1498,416),(1493,446),(1477,443)],
    'm2': [(1499,416),(1514,419),(1510,448),(1495,445)],
    's1': [(1520,421),(1535,424),(1532,454),(1517,451)],
    's2': [(1537,425),(1552,428),(1548,458),(1533,455)],
    'h1': [(1456,465),(1476,469),(1470,500),(1450,495)],
    'h2': [(1474,470),(1494,475),(1487,505),(1467,500)],
    'a1': [(1530,484),(1552,489),(1545,523),(1523,517)],
    'a2': [(1552,491),(1574,496),(1566,530),(1544,523)],
    'p': [(1499,490),(1517,494),(1512,518),(1494,514)],
}
DEFAULT_VIEW = (1360,350,1700,610)
GROUP_PREFIX = {'clock':'c','homeScore':'h','awayScore':'a','period':'p'}
DIGIT_LIMITS = {'clock':(4,4),'homeScore':(1,3),'awayScore':(1,3),'period':(1,1)}
COLORS = ('red','amber','green','white')

QUADS = dict(DEFAULT_QUADS)
GROUPS = {'clock':('m1','m2','s1','s2'),'homeScore':('h1','h2'),'awayScore':('a1','a2'),'period':('p',)}
VIEW = DEFAULT_VIEW
COLOR = 'red'
THRESHOLD = 180
CALIBRATED = False


def split_quad(quad,count):
    """Equal digit cells along a group's quad (keeps perspective)."""
    tl,tr,br,bl=[np.array(p,float) for p in quad]
    cells=[]
    for i in range(count):
        a,b=i/count,(i+1)/count
        cells.append([tuple(map(float,tl+(tr-tl)*a)),tuple(map(float,tl+(tr-tl)*b)),
                      tuple(map(float,bl+(br-bl)*b)),tuple(map(float,bl+(br-bl)*a))])
    return cells


def validate_calibration(data):
    if not isinstance(data,dict):raise ValueError('Calibracion invalida')
    groups=data.get('groups')
    if not isinstance(groups,dict) or set(groups)!=set(GROUP_PREFIX):raise ValueError('Marcar reloj, local, visita y periodo')
    clean={}
    for key,group in groups.items():
        quad=group.get('quad') if isinstance(group,dict) else None
        if not isinstance(quad,list) or len(quad)!=4:raise ValueError(f'Faltan las 4 esquinas de {key}')
        points=[]
        for point in quad:
            x,y=float(point[0]),float(point[1])
            if not (0<=x<=1920 and 0<=y<=1080):raise ValueError('Esquina fuera del cuadro')
            points.append([round(x,1),round(y,1)])
        low,high=DIGIT_LIMITS[key];digits=int(group.get('digits',low))
        if not low<=digits<=high:raise ValueError(f'Cantidad de digitos invalida en {key}')
        clean[key]={'quad':points,'digits':digits}
    color=data.get('color','red')
    if color not in COLORS:raise ValueError('Color de LED invalido')
    threshold=int(data.get('threshold',180))
    if not 60<=threshold<=250:raise ValueError('Sensibilidad invalida')
    view=data.get('view') or DEFAULT_VIEW
    x0,y0,x1,y1=[int(round(float(v))) for v in view]
    x0,x1=sorted((max(0,min(1920,x0)),max(0,min(1920,x1))));y0,y1=sorted((max(0,min(1080,y0)),max(0,min(1080,y1))))
    if x1-x0<20 or y1-y0<20:raise ValueError('Zona del tablero demasiado chica')
    return {'groups':clean,'color':color,'threshold':threshold,'view':[x0,y0,x1,y1]}


def apply_calibration(data):
    global QUADS,GROUPS,VIEW,COLOR,THRESHOLD,CALIBRATED
    if data is None:
        QUADS=dict(DEFAULT_QUADS);GROUPS={'clock':('m1','m2','s1','s2'),'homeScore':('h1','h2'),'awayScore':('a1','a2'),'period':('p',)}
        VIEW=DEFAULT_VIEW;COLOR='red';THRESHOLD=180;CALIBRATED=False;return
    data=validate_calibration(data);quads={};groups={}
    for key,group in data['groups'].items():
        names=tuple(f'{GROUP_PREFIX[key]}{i+1}' for i in range(group['digits']))
        if key=='clock':names=('m1','m2','s1','s2')
        if key=='period':names=('p',)
        for name,cell in zip(names,split_quad(group['quad'],group['digits'])):quads[name]=cell
        groups[key]=names
    QUADS,GROUPS=quads,groups
    VIEW=tuple(data['view']);COLOR=data['color'];THRESHOLD=data['threshold'];CALIBRATED=True


def load_calibration(path=None):
    path=path or CALIBRATION_PATH
    try:return validate_calibration(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError,ValueError,TypeError,KeyError,IndexError):return None


def save_calibration(data,path=None):
    data=validate_calibration(data);path=Path(path or CALIBRATION_PATH)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,indent=1),encoding='utf-8');temporary.replace(path)
    apply_calibration(data)
    return data


def default_calibration():
    """The built-in calibration expressed as editable group quads."""
    def group(first,last,count):
        a,b=DEFAULT_QUADS[first],DEFAULT_QUADS[last]
        return {'quad':[list(a[0]),list(b[1]),list(b[2]),list(a[3])],'digits':count}
    return {'groups':{'clock':group('m1','s2',4),'homeScore':group('h1','h2',2),'awayScore':group('a1','a2',2),'period':group('p','p',1)},
            'color':'red','threshold':180,'view':list(DEFAULT_VIEW)}


def current_calibration():
    return (load_calibration() if CALIBRATED else None) or default_calibration()


def reset_calibration(path=None):
    try:Path(path or CALIBRATION_PATH).unlink()
    except FileNotFoundError:pass
    apply_calibration(None)
    return default_calibration()


def warp(im, pts):
    # PIL QUAD expects TL, BL, BR, TR.
    return im.transform((48,80),Image.Transform.QUAD,tuple(c for i in [0,3,2,1] for c in pts[i]),Image.Resampling.BICUBIC)


def mask(im):
    a=np.asarray(im.convert('RGB')).astype(float)
    r,g,b=a[:,:,0],a[:,:,1],a[:,:,2];t=THRESHOLD
    if COLOR=='amber':return (r>t)&(g>t*.45)&(r>b*1.4)&(g>b*1.1)
    if COLOR=='green':return (g>t)&(g>r*1.1)&(g>b*1.05)
    if COLOR=='white':return (r>t)&(g>t)&(b>t)
    return (r>t)&(r>g*1.03)&(r>b*1.08)


def board_power_state(im,digits=None):
    """A visible board with all LEDs dark differs from an unreadable/black feed."""
    if im.size!=(1920,1080):return 'unknown'
    if digits and any(value is not None for value in digits.values()):return 'on'
    if any(int(mask(warp(im,points)).sum())>=50 for points in QUADS.values()):return 'on'
    board=np.asarray(im.crop(VIEW).convert('L'))
    if float(board.mean())<10 or float(board.std())<8:return 'unknown'
    return 'off'

PROBES = {
    'a': (.43,.04,.60,.17),
    'b': (.72,.19,.94,.42),
    'c': (.72,.59,.94,.83),
    'd': (.43,.85,.60,.97),
    'e': (.18,.59,.36,.83),
    'f': (.18,.19,.36,.42),
    'g': (.40,.44,.60,.56),
}

def probes(m):
    ys,xs=np.where(m)
    if len(xs):
        m=m[ys.min():ys.max()+1,xs.min():xs.max()+1]
    h,w=m.shape
    return {k:round(float(m[int(y*h):int(v*h),int(x*w):int(u*w)].mean()),3) for k,(x,y,u,v) in PROBES.items()}

PATTERNS = {'ab cdef'.replace(' ',''):'0','bc':'1','abdeg':'2','abcdg':'3','bcfg':'4','acdfg':'5','acdefg':'6','abc':'7','abcdefg':'8','abcdfg':'9','cdefg':'6','abcfg':'9'}

def recognize(im,key):
    """Returns (digit, scores). An unlit cell returns (None, {}); a lit unknown shape (None, scores)."""
    m=mask(warp(im,QUADS[key]));ys,xs=np.where(m)
    if len(xs)<50: return None,{}
    if xs.max()-xs.min()+1 < m.shape[1]*.40:
        return '1',{'narrow':True}
    scores=probes(m)
    active=''.join(k for k in sorted(scores) if scores[k]>(.45 if k=='g' else .30))
    return PATTERNS.get(active),scores


apply_calibration(load_calibration())
