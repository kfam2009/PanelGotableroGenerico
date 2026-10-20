import json
from pathlib import Path

from PIL import Image
import numpy as np

READER_VERSION = '2026.10.20.2'
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
COLORS = ('auto','red','amber','green','white')

QUADS = dict(DEFAULT_QUADS)
GROUPS = {'clock':('m1','m2','s1','s2'),'homeScore':('h1','h2'),'awayScore':('a1','a2'),'period':('p',)}
VIEW = DEFAULT_VIEW
COLOR = 'red'
THRESHOLD = 180
CALIBRATED = False
GROUP_QUADS = {}
SEGMENTS = 'auto'
SEGMENT_MODES = ('auto','segments','solid')


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
        low,high=DIGIT_LIMITS[key];digits=min(high,max(low,int(group.get('digits',high))))
        clean[key]={'quad':points,'digits':digits}
    color=data.get('color','auto')
    if color not in COLORS:raise ValueError('Color de LED invalido')
    threshold=int(data.get('threshold',180))
    if not 60<=threshold<=250:raise ValueError('Sensibilidad invalida')
    view=data.get('view') or DEFAULT_VIEW
    x0,y0,x1,y1=[int(round(float(v))) for v in view]
    x0,x1=sorted((max(0,min(1920,x0)),max(0,min(1920,x1))));y0,y1=sorted((max(0,min(1080,y0)),max(0,min(1080,y1))))
    if x1-x0<20 or y1-y0<20:raise ValueError('Zona del tablero demasiado chica')
    points=[pt for group in clean.values() for pt in group['quad']]
    if any(not (x0<=x<=x1 and y0<=y<=y1) for x,y in points):
        # The zone must contain every marked group; otherwise frame them with a margin.
        xs=[x for x,_ in points];ys=[y for _,y in points];mx=(max(xs)-min(xs))*.12+10;my=(max(ys)-min(ys))*.12+10
        x0,y0=int(max(0,min(xs)-mx)),int(max(0,min(ys)-my));x1,y1=int(min(1920,max(xs)+mx)),int(min(1080,max(ys)+my))
    segments=data.get('segments','auto')
    if segments not in SEGMENT_MODES:raise ValueError('Tipo de digitos invalido')
    return {'groups':clean,'color':color,'threshold':threshold,'view':[x0,y0,x1,y1],'segments':segments}


def apply_calibration(data):
    global QUADS,GROUPS,GROUP_QUADS,VIEW,COLOR,THRESHOLD,CALIBRATED,SEGMENTS
    if data is None:
        QUADS=dict(DEFAULT_QUADS);GROUPS={'clock':('m1','m2','s1','s2'),'homeScore':('h1','h2'),'awayScore':('a1','a2'),'period':('p',)}
        VIEW=DEFAULT_VIEW;COLOR='red';THRESHOLD=180;CALIBRATED=False;SEGMENTS='auto';return
    data=validate_calibration(data);quads={};groups={}
    for key,group in data['groups'].items():
        names=tuple(f'{GROUP_PREFIX[key]}{i+1}' for i in range(group['digits']))
        if key=='clock':names=('m1','m2','s1','s2')
        if key=='period':names=('p',)
        for name,cell in zip(names,split_quad(group['quad'],group['digits'])):quads[name]=cell
        groups[key]=names
    QUADS,GROUPS=quads,groups;GROUP_QUADS=data['groups']
    VIEW=tuple(data['view']);COLOR=data['color'];THRESHOLD=data['threshold'];SEGMENTS=data['segments'];CALIBRATED=True


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
            'color':'red','threshold':180,'view':list(DEFAULT_VIEW),'segments':'auto'}


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
    if COLOR=='auto':return (r>t)|(g>t)|(b>t)
    if COLOR=='amber':return (r>t)&(g>t*.45)&(r>b*1.4)&(g>b*1.1)
    if COLOR=='green':return (g>t)&(g>r*1.1)&(g>b*1.05)
    if COLOR=='white':return (r>t)&(g>t)&(b>t)
    return (r>t)&(r>g*1.03)&(r>b*1.08)


def board_power_state(im,digits=None):
    """A visible board with all LEDs dark differs from an unreadable/black feed."""
    if im.size!=(1920,1080):return 'unknown'
    if digits and any(value is not None for value in digits.values()):return 'on'
    if not CALIBRATED and any(int(mask(warp(im,points)).sum())>=50 for points in QUADS.values()):return 'on'
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

PATTERNS = {'abcd':'7','ab cdef'.replace(' ',''):'0','bc':'1','abdeg':'2','abcdg':'3','bcfg':'4','acdfg':'5','acdefg':'6','abc':'7','abcdefg':'8','abcdfg':'9','cdefg':'6','abcfg':'9'}

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


# ---- Calibrated boards: each group is read as a row of lit shapes (any color or font size) ----
GROUP_HEIGHT=80


def warp_group(im,quad):
    q=[tuple(map(float,p)) for p in quad]
    w=float(np.hypot(q[1][0]-q[0][0],q[1][1]-q[0][1]));h=float(np.hypot(q[3][0]-q[0][0],q[3][1]-q[0][1]))
    width=max(8,min(600,int(round(GROUP_HEIGHT*w/max(h,1)))))
    return im.transform((width,GROUP_HEIGHT),Image.Transform.QUAD,tuple(c for i in [0,3,2,1] for c in q[i]),Image.Resampling.BICUBIC)


def otsu(values):
    hist=np.bincount(values.ravel().astype(int),minlength=256).astype(float);levels=np.arange(256)
    w0=np.cumsum(hist);w1=w0[-1]-w0;m0=np.cumsum(hist*levels)
    with np.errstate(divide='ignore',invalid='ignore'):
        var=(m0[-1]*w0/w0[-1]-m0)**2/(w0*w1)
    var[~np.isfinite(var)]=0
    return int(np.argmax(var))


def group_mask(group_image):
    a=np.asarray(group_image.convert('RGB')).astype(float)
    if COLOR!='auto':return mask(group_image)
    value=a.max(axis=2);t=max(otsu(value),60)
    lit=value>t
    if not lit.any() or lit.all():return np.zeros_like(lit)
    # A dark board with no lit digits must not be split into fake shapes.
    if value[lit].mean()-value[~lit].mean()<45 or lit.mean()>.6:return np.zeros_like(lit)
    return lit


def components(m):
    h,w=m.shape;labels=np.zeros((h,w),np.int32);found=[]
    for y0,x0 in zip(*np.nonzero(m)):
        if labels[y0,x0]:continue
        n=len(found)+1;labels[y0,x0]=n;stack=[(y0,x0)];ys=[];xs=[]
        while stack:
            y,x=stack.pop();ys.append(y);xs.append(x)
            for dy in (-1,0,1):
                for dx in (-1,0,1):
                    yy,xx=y+dy,x+dx
                    if 0<=yy<h and 0<=xx<w and m[yy,xx] and not labels[yy,xx]:labels[yy,xx]=n;stack.append((yy,xx))
        found.append({'ids':[n],'x0':min(xs),'x1':max(xs)+1,'y0':min(ys),'y1':max(ys)+1,'n':len(ys)})
    return labels,found


SHAPE_ZONES={'a':(.3,0,.7,.16),'b':(.7,.14,1,.44),'c':(.7,.56,1,.86),'d':(.3,.84,.7,1),'e':(0,.56,.3,.86),'f':(0,.14,.3,.44),'g':(.3,.43,.7,.57)}


def classify_shape(m):
    ys,xs=np.nonzero(m)
    if len(xs)<12:return None
    m=m[ys.min():ys.max()+1,xs.min():xs.max()+1];h,w=m.shape
    if w<h*.32:return '1'
    # Segment zones over the shape's own box: wide enough for thin LED segments and slanted fonts.
    scores={k:float(m[int(y0*h):max(int(y0*h)+1,int(y1*h)),int(x0*w):max(int(x0*w)+1,int(x1*w))].mean()) for k,(x0,y0,x1,y1) in SHAPE_ZONES.items()}
    active=''.join(k for k in sorted(scores) if scores[k]>(.35 if k=='g' else .25))
    return PATTERNS.get(active)


def read_group(im,quad):
    """Text of one group: digits left to right, '.' for a decimal point, '?' for an unknown shape, '' if unlit."""
    m=group_mask(warp_group(im,quad))
    if not m.any():return ''
    labels,found=components(m)
    # Short marks touching the top or bottom edge are board decorations, not digits.
    found=[c for c in found if not ((c['y0']==0 or c['y1']==GROUP_HEIGHT) and c['y1']-c['y0']<GROUP_HEIGHT*.3)]
    if not found:return ''
    def join(a,b):
        a['ids']+=b['ids'];a['n']+=b['n']
        for k,f in (('x0',min),('y0',min),('x1',max),('y1',max)):a[k]=f(a[k],b[k])
    def gaps(a,b):return max(a['x0'],b['x0'])-min(a['x1'],b['x1']),max(a['y0'],b['y0'])-min(a['y1'],b['y1'])
    def merge(items,test):
        items=[dict(c,ids=list(c['ids'])) for c in items];changed=True
        while changed:
            changed=False
            for i in range(len(items)):
                for j in range(i+1,len(items)):
                    if test(items[i],items[j]):join(items[i],items[j]);del items[j];changed=True;break
                if changed:break
        return items
    # Pieces stacked in the same column belong to one digit (e.g. two vertical LED segments).
    def stacked(a,b):
        xgap,ygap=gaps(a,b);return -xgap>.5*min(a['x1']-a['x0'],b['x1']-b['x0']) and ygap<=GROUP_HEIGHT*.15
    clusters=merge(found,stacked)
    total=sum(c['n'] for c in clusters)
    body=[c for c in clusters if c['n']>=total*.03]
    top=min(c['y0'] for c in body);bottom=max(c['y1'] for c in body);D=bottom-top
    if D<GROUP_HEIGHT*.3:return ''
    def small(c):
        w,h=c['x1']-c['x0'],c['y1']-c['y0'];return w<=D*.25 and h<=D*.25 and w<=h*1.8 and c['n']>=6
    # LED digits are drawn with separate horizontal bars (segments a, g, d); solid digits are single shapes.
    bars=sum(c['n'] for c in found if c['x1']-c['x0']>(c['y1']-c['y0'])*1.8 and c['y1']-c['y0']<D*.3)
    half=any(c['y1']-c['y0']>(c['x1']-c['x0'])*1.5 and D*.25<=c['y1']-c['y0']<D*.6 and c['n']>=total*.03 for c in clusters)
    segmented=SEGMENTS=='segments' or (SEGMENTS=='auto' and (bars>=total*.18 or half))
    dots=[c for c in clusters if small(c)]
    clusters=[c for c in clusters if not small(c)]
    if segmented:
        # LED digits: horizontal and vertical segments are separate shapes with small gaps.
        gx,gy=D*.12+1,D*.25
        def near(a,b):
            xgap,ygap=gaps(a,b);return xgap<=gx and ygap<=gy
        clusters=merge(clusters,near)
    tall=max(c['y1']-c['y0'] for c in clusters) if clusters else 0
    if tall<GROUP_HEIGHT*.3:return ''
    merged=sorted((c for c in clusters if c['y1']-c['y0']>=tall*.6),key=lambda c:c['x0'])
    if not merged:return ''
    top=min(c['y0'] for c in merged);bottom=max(c['y1'] for c in merged);D=bottom-top
    dots=[c for c in dots if c['y0']>=top+D*.6 and c['y1']<=bottom+D*.1]
    dots=[c for c in dots if merged[0]['x1']<=c['x0'] and c['x1']<=merged[-1]['x0']]
    items=[(c['x0'],classify_shape(np.isin(labels,c['ids'])) or '?') for c in merged]+[(c['x0'],'.') for c in dots]
    return ''.join(t for _,t in sorted(items))


def interpret(key,text):
    """Board value from a group's text, or None when it is not a valid reading."""
    if not text or '?' in text:return None
    digits=text.replace('.','')
    if not digits:return None
    if key=='clock':
        if len(digits)==4:
            minutes,seconds=int(digits[:2]),int(digits[2:])
            return f'{minutes:02d}:{seconds:02d}' if minutes<=20 and seconds<=59 else None
        if len(digits)==3:
            if '.' in text and text.index('.')==2:  # SS.T in the last minute
                return f'{int(digits[:2]):02d}.{digits[2]}' if int(digits[:2])<60 else None
            return f'0{digits[0]}:{digits[1:]}' if int(digits[1:])<=59 else None
        if len(digits)==2 and '.' in text and text.index('.')==1:  # S.T
            return f'0{digits[0]}.{digits[1]}'
        return None
    if key=='period':return digits if len(digits)==1 and digits!='0' else None
    return str(int(digits)) if len(digits)<=3 else None


def read_calibrated(im):
    texts={key:read_group(im,group['quad']) for key,group in GROUP_QUADS.items()}
    values={key:value for key,text in texts.items() if (value:=interpret(key,text)) is not None}
    return values,{key:(text or None) for key,text in texts.items()}
