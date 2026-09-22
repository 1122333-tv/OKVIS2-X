"""Shared rigid transforms and canonical pose IO (integer ns, metres, wxyz)."""
import csv
import json
import math
from decimal import Decimal
from pathlib import Path


def mul(a, b):
    w,x,y,z=a; v,i,j,k=b
    return [w*v-x*i-y*j-z*k,w*i+x*v+y*k-z*j,w*j-x*k+y*v+z*i,w*k+x*j-y*i+z*v]


def rot(q,p):
    return mul(mul(q,[0]+list(p)),[q[0],-q[1],-q[2],-q[3]])[1:]


def unpack(t):
    return [t[k] for k in ('qw','qx','qy','qz')],[t[k] for k in ('px','py','pz')]


def compose(a,b):
    q,p=a; r,t=b
    return mul(q,r),[x+y for x,y in zip(p,rot(q,t))]


def inverse(a):
    q,p=a; q=[q[0],-q[1],-q[2],-q[3]]
    return q,rot(q,[-x for x in p])


def csv_rows(path):
    with Path(path).open(newline='') as f:
        return list(csv.reader(l for l in f if l.strip() and not l.lstrip().startswith('#')))


def write_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n');temp.replace(path)


def ns_seconds(value, allow_rounding=False):
    d=Decimal(str(value))*1_000_000_000
    if not d.is_finite() or (not allow_rounding and d!=d.to_integral_value()):
        raise ValueError('Time must be finite with at most nanosecond precision')
    return int(d.to_integral_value())


def tum_time(ns):
    sign='-' if ns<0 else '';sec,nano=divmod(abs(ns),1_000_000_000)
    return f'{sign}{sec}.{nano:09d}'


def read_poses(path, legacy=False, max_gap_ns=50_000_000):
    """Return (ns, xyz, wxyz, segment). Invalid rows break interpolation segments."""
    with Path(path).open(newline='') as f:
        raw=list(csv.reader(f))
    valid_col=None
    if legacy:
        meta=dict(zip(raw[0][::2],raw[0][1::2]))
        if meta.get('LengthUnits')!='mm' or meta.get('CoordinateSpace')!='World':
            raise ValueError('Expected legacy mm/World export')
        header=next(i for i,r in enumerate(raw) if r[:2]==['Frame','Time'])
        if raw[header][2:9]!=['X','Y','Z','W','X','Y','Z']:
            raise ValueError('Expected legacy xyzw + xyz columns')
        names=next(r for r in raw[:header] if len(r)>1 and r[1]=='Name')
        if len(set(names[2:])-{''})!=1:raise ValueError('Select exactly one mocap rigid body')
        raw=raw[header+1:]
    else:
        header=next((r for r in raw if r and r[0].lstrip().startswith('#')),None)
        if header and 'tracking_valid' in header:valid_col=header.index('tracking_valid')
        raw=[r for r in raw if r and not r[0].lstrip().startswith('#')]
    result=[];previous=None;segment=0;invalid=0
    for r in raw:
        if not r:continue
        # A malformed timestamp cannot be placed safely in the time series.
        t=ns_seconds(r[1]) if legacy else int(r[0])
        if previous is not None and t<=previous:raise ValueError('Pose timestamps must strictly increase')
        previous=t
        try:
            if valid_col is not None and int(r[valid_col])!=1:raise ValueError('tracking invalid')
            if legacy:
                v=list(map(float,r[2:9]));q=[v[3],*v[:3]];p=[x*.001 for x in v[4:]]
            else:
                p=list(map(float,r[1:4]));q=list(map(float,r[4:8]))
            norm=math.sqrt(sum(x*x for x in q))
            if len(p)!=3 or len(q)!=4 or not all(math.isfinite(x) for x in p+q) or abs(norm-1)>.01:
                raise ValueError('invalid pose')
        except (ValueError,IndexError):
            invalid+=1;segment+=1;continue
        q=[x/norm for x in q]
        if result and t-result[-1][0]>max_gap_ns:segment+=1
        if result and sum(x*y for x,y in zip(q,result[-1][2]))<0:q=[-x for x in q]
        result.append((t,p,q,segment))
    if len(result)<3:raise ValueError('Too few valid poses')
    return result,dict(valid_rows=len(result),invalid_rows=invalid,max_gap_ns=max_gap_ns)


def slerp(a,b,w):
    dot=sum(x*y for x,y in zip(a,b))
    if dot<0:b=[-x for x in b];dot=-dot
    dot=min(1.,max(-1.,dot))
    if dot>.9995:q=[(1-w)*x+w*y for x,y in zip(a,b)]
    else:
        theta=math.acos(dot);den=math.sin(theta)
        q=[(math.sin((1-w)*theta)*x+math.sin(w*theta)*y)/den for x,y in zip(a,b)]
    n=math.sqrt(sum(x*x for x in q));return [x/n for x in q]
