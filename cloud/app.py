"""Forme cloud account, design and order service. Private files never use public paths."""
import hashlib, hmac, json, os, re, secrets, shutil, time, uuid
import httpx
from urllib.parse import quote
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from sqlalchemy import create_engine, Column, Integer, String, Text, BigInteger, ForeignKey, Numeric, UniqueConstraint, select, func, update, or_
from sqlalchemy.orm import declarative_base, sessionmaker, Session as DBSession
from sqlalchemy.exc import IntegrityError

config_path = os.getenv('FORME_CONFIG')
config = json.loads(Path(config_path).read_text()) if config_path else {}
WORKER_KEY = os.getenv('FORME_WORKER_KEY', config.get('worker_key', ''))
LOCAL_OPERATOR_TOKEN = os.getenv('FORME_LOCAL_OPERATOR_TOKEN', config.get('local_operator_token', ''))
LOCAL_OPERATOR_URL = config.get('local_operator_url', 'http://127.0.0.1:18001').rstrip('/')
if not re.fullmatch(r'http://(?:127\.0\.0\.1|localhost):[0-9]{2,5}',LOCAL_OPERATOR_URL):
    raise RuntimeError('LOCAL_OPERATOR_URL_MUST_BE_LOOPBACK')
DB_URL = os.getenv('FORME_DATABASE_URL', config.get('database_url', 'sqlite:///./forme-test.db'))
DATA = Path(os.getenv('FORME_DATA_DIR', config.get('data_dir', './private-data')))
DATA.mkdir(parents=True, exist_ok=True)
SECURE = config.get('secure_cookie', os.getenv('FORME_SECURE_COOKIE', '1') == '1')
ORIGINS = set(config.get('origins', ['https://my-robot-home.com', 'https://www.my-robot-home.com']))
engine = create_engine(DB_URL, pool_pre_ping=True, **({'connect_args': {'check_same_thread': False}} if DB_URL.startswith('sqlite:') else {'pool_recycle': 1800}))
Factory = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()
def uid(): return uuid.uuid4().hex
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def colid(): return Column(String(32), primary_key=True, default=uid)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String(254), unique=True, nullable=False)
    username = Column(String(60), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(120), default='')
    phone = Column(String(40), default='')
    created_at = Column(String(40), default=now)
class LoginSession(Base):
    __tablename__ = 'sessions'
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True, index=True)
    role = Column(String(15), nullable=False)
    expires_at = Column(BigInteger, nullable=False)
    created_at = Column(String(40), default=now)
class Upload(Base):
    __tablename__ = 'uploads'
    id = colid()
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    filename = Column(String(180), nullable=False)
    content_type = Column(String(80), nullable=False)
    byte_size = Column(BigInteger, nullable=False)
    sha256 = Column(String(64))
    status = Column(String(24), default='pending')
    created_at = Column(String(40), default=now)
class Submission(Base):
    __tablename__ = 'submissions'
    id = colid()
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    upload_id = Column(String(32), ForeignKey('uploads.id'), unique=True, nullable=False)
    template_id = Column(String(20), nullable=False)
    color = Column(String(40), nullable=False)
    material = Column(String(40), nullable=False)
    inspiration = Column(Text, default='')
    inspiration_file = Column(String(64))
    status = Column(String(32), default='needs_capture_review')
    model_stage = Column(String(32), default='queued')
    model_file = Column(String(64))
    model_filename = Column(String(180))
    quote_hkd = Column(Numeric(10,2))
    admin_note = Column(Text, default='')
    created_at = Column(String(40), default=now)
    updated_at = Column(String(40), default=now)
class ModelingEvent(Base):
    __tablename__ = 'modeling_events'
    id = colid()
    submission_id = Column(String(32), ForeignKey('submissions.id'), nullable=False, index=True)
    status = Column(String(32), nullable=False)
    stage = Column(String(32), nullable=False)
    note = Column(Text, default='')
    actor = Column(String(30), default='admin')
    created_at = Column(String(40), default=now)
class WorkerJob(Base):
    __tablename__ = 'worker_jobs'
    submission_id = Column(String(32), ForeignKey('submissions.id'), primary_key=True)
    state = Column(String(24), nullable=False, default='queued')
    lease_hash = Column(String(64))
    lease_until = Column(BigInteger, default=0)
    artifact_sha256 = Column(String(64))
    updated_at = Column(String(40), default=now)
class Order(Base):
    __tablename__ = 'orders'
    id = colid()
    order_number = Column(String(40), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    submission_id = Column(String(32), ForeignKey('submissions.id'), unique=True, nullable=False)
    amount_hkd = Column(Numeric(10,2), nullable=False)
    payment_status = Column(String(24), default='pending')
    order_status = Column(String(24), default='placed')
    created_at = Column(String(40), default=now)
    updated_at = Column(String(40), default=now)
class Payment(Base):
    __tablename__ = 'payments'
    id = colid()
    order_id = Column(String(32), ForeignKey('orders.id'), nullable=False, index=True)
    method = Column(String(80), nullable=False)
    reference = Column(String(120), default='')
    proof_file = Column(String(64))
    proof_filename = Column(String(180))
    status = Column(String(24), default='submitted')
    review_note = Column(Text, default='')
    created_at = Column(String(40), default=now)
    reviewed_at = Column(String(40))
class Delivery(Base):
    __tablename__ = 'deliveries'
    id = colid()
    order_id = Column(String(32), ForeignKey('orders.id'), unique=True, nullable=False)
    recipient_name = Column(String(120), nullable=False)
    recipient_phone = Column(String(40), nullable=False)
    address_line = Column(String(500), nullable=False)
    region = Column(String(100), nullable=False)
    district = Column(String(100), nullable=False)
    delivery_note = Column(Text, default='')
    carrier = Column(String(100), default='')
    tracking_number = Column(String(120), default='')
    delivery_status = Column(String(24), default='pending')
    shipped_at = Column(String(40))
    delivered_at = Column(String(40))
    confirmed_at = Column(String(40))
    updated_at = Column(String(40), default=now)
class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id = colid()
    action = Column(String(60), nullable=False)
    target_id = Column(String(40), nullable=False)
    actor = Column(String(40), nullable=False)
    detail = Column(Text, default='')
    created_at = Column(String(40), default=now)
class RateLimit(Base):
    __tablename__ = 'rate_limits'
    key = Column(String(64), primary_key=True)
    count = Column(Integer, nullable=False, default=0)
    expires_at = Column(BigInteger, nullable=False)
Base.metadata.create_all(engine)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

def fail(code, status=400): raise HTTPException(status, detail={'code': code})
def db():
    with Factory() as s: yield s
@app.middleware('http')
async def protections(request, call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin = request.headers.get('origin')
        if (origin and origin not in ORIGINS) or request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': {'code': 'INVALID_ORIGIN'}}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

def fields(row, omit=()):
    if row is None: return None
    d = {c.name: getattr(row,c.name) for c in row.__table__.columns if c.name not in omit}
    return {k: str(v) if isinstance(v,Decimal) else v for k,v in d.items()}
def user_public(user): return fields(user, ('password_hash',))
def audit(s, action, target, actor, detail=''):
    s.add(AuditEvent(action=action,target_id=str(target),actor=str(actor),detail=detail))
def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384,r=8,p=1).hex()
    return f'scrypt$16384$8$1${salt}${value}'
def verify(password, encoded):
    try:
        _,n,r,p,salt,digest = encoded.split('$')
        value = hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=int(n),r=int(r),p=int(p)).hex()
        return hmac.compare_digest(value,digest)
    except (ValueError,AttributeError): return False
ADMIN_HASH = config.get('admin_password_hash') or (hash_password(os.environ['FORME_ADMIN_PASSWORD']) if os.getenv('FORME_ADMIN_PASSWORD') else None)
DUMMY_HASH = hash_password('no-such-user', 'ed2ef4dc3eb4df46766e3d88a1c97184')
async def body(request):
    if int(request.headers.get('content-length','0')) > 16384: fail('REQUEST_TOO_LARGE',413)
    raw = await request.body()
    if len(raw)>16384: fail('REQUEST_TOO_LARGE',413)
    try:
        value=json.loads(raw)
        if not isinstance(value,dict): fail('INVALID_REQUEST')
        return value
    except (ValueError,TypeError): fail('INVALID_REQUEST')
def text_field(d,key,maxlen,required=True):
    value=d.get(key,'')
    if not isinstance(value,str): fail('INVALID_'+key.upper())
    value=value.strip()
    if len(value)>maxlen or (required and not value): fail('INVALID_'+key.upper())
    return value
def money(value):
    try:
        result=Decimal(str(value))
        if not result.is_finite() or result<=0 or result>Decimal('9999999.99') or result != result.quantize(Decimal('.01')): fail('INVALID_AMOUNT')
        return result
    except (InvalidOperation,TypeError,ValueError): fail('INVALID_AMOUNT')
def rate(s,request,category,limit,window=60):
    ip=request.client.host if request.client else 'unknown'
    period=int(time.time())//window
    key=hashlib.sha256(f'{category}:{ip}:{period}'.encode()).hexdigest()
    entry=s.get(RateLimit,key)
    if not entry:
        try:
            s.add(RateLimit(key=key,count=0,expires_at=(period+1)*window)); s.commit()
        except IntegrityError: s.rollback()
    s.execute(update(RateLimit).where(RateLimit.key==key).values(count=RateLimit.count+1)); s.commit()
    s.expire_all()
    if s.get(RateLimit,key).count>limit: fail('TOO_MANY_ATTEMPTS',429)
def identity(s,request,role='customer'):
    token=request.cookies.get('forme_admin' if role=='admin' else 'forme_customer','')
    row=s.get(LoginSession,hashlib.sha256(token.encode()).hexdigest()) if token else None
    if not row or row.role!=role or row.expires_at<int(time.time()): fail('ADMIN_SESSION_REQUIRED' if role=='admin' else 'CUSTOMER_SESSION_REQUIRED',401)
    return row if role=='admin' else s.get(User,row.user_id)
def worker_identity(request):
    token=request.headers.get('authorization','')
    if not WORKER_KEY or not hmac.compare_digest(token, 'Bearer '+WORKER_KEY): fail('WORKER_UNAUTHORIZED',401)
def leased_job(s,id,request):
    worker_identity(request)
    row=s.get(WorkerJob,id)
    token=request.headers.get('x-job-token','')
    if not row or row.state!='running' or row.lease_until<int(time.time()) or not token or not hmac.compare_digest(row.lease_hash or '',hashlib.sha256(token.encode()).hexdigest()):
        fail('JOB_LEASE_REQUIRED',409)
    return row
def session_response(s,request,user=None,role='customer'):
    token=secrets.token_urlsafe(32)
    name='forme_admin' if role=='admin' else 'forme_customer'
    old=request.cookies.get(name)
    if old:
        existing=s.get(LoginSession,hashlib.sha256(old.encode()).hexdigest())
        if existing: s.delete(existing)
    lifetime=8*3600 if role=='admin' else 7*86400
    s.add(LoginSession(token_hash=hashlib.sha256(token.encode()).hexdigest(),user_id=user.id if user else None,role=role,expires_at=int(time.time())+lifetime))
    s.commit()
    response=JSONResponse({'ok':True,'user':user_public(user) if user else {'username':'forme'}})
    response.set_cookie(name,token,max_age=lifetime,httponly=True,secure=SECURE,samesite='strict',path='/api')
    return response
@app.get('/api/health')
def health(s:DBSession=Depends(db)):
    s.execute(select(func.count(User.id)))
    return {'ok':True,'service':'forme-cloud','version':'2026.10.12-admin1'}
@app.post('/api/customer/register')
async def register(request:Request,s:DBSession=Depends(db)):
    rate(s,request,'register',10,3600)
    d=await body(request)
    email=text_field(d,'email',254).lower()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email): fail('INVALID_EMAIL')
    username=text_field(d,'username',60)
    if not re.fullmatch(r'[A-Za-z0-9_\-\u4e00-\u9fff]{3,40}',username) or username.lower()=='forme': fail('INVALID_USERNAME')
    password=text_field(d,'password',128)
    if len(password)<8: fail('PASSWORD_TOO_SHORT')
    user=User(email=email,username=username.lower(),password_hash=hash_password(password),full_name=text_field(d,'full_name',120,False))
    s.add(user)
    try: s.commit()
    except IntegrityError: s.rollback(); fail('EMAIL_OR_USERNAME_EXISTS',409)
    audit(s,'registered',user.id,user.id)
    return session_response(s,request,user)
@app.post('/api/customer/login')
async def login(request:Request,s:DBSession=Depends(db)):
    rate(s,request,'login',8)
    d=await body(request)
    name=text_field(d,'identifier',254).lower()
    password=text_field(d,'password',128)
    user=s.scalar(select(User).where((User.email==name)|(User.username==name)))
    valid=verify(password,user.password_hash if user else DUMMY_HASH)
    if not user or not valid: fail('INVALID_CREDENTIALS',401)
    return session_response(s,request,user)
@app.post('/api/admin/login')
async def admin_login(request:Request,s:DBSession=Depends(db)):
    if not ADMIN_HASH: fail('ADMIN_LOGIN_NOT_CONFIGURED',503)
    rate(s,request,'admin_login',5)
    d=await body(request)
    valid=verify(text_field(d,'password',128),ADMIN_HASH)
    if text_field(d,'username',60)!='forme' or not valid: fail('INVALID_CREDENTIALS',401)
    audit(s,'admin_login','forme','admin')
    return session_response(s,request,role='admin')
@app.post('/api/{role}/logout')
def logout(role:str,request:Request,s:DBSession=Depends(db)):
    if role not in ('customer','admin'): fail('NOT_FOUND',404)
    name='forme_admin' if role=='admin' else 'forme_customer'
    token=request.cookies.get(name,'')
    row=s.get(LoginSession,hashlib.sha256(token.encode()).hexdigest())
    if row: s.delete(row); s.commit()
    response=JSONResponse({'ok':True}); response.delete_cookie(name,path='/api',secure=SECURE,httponly=True,samesite='strict'); return response
@app.get('/api/customer/session')
def customer_session(request:Request,s:DBSession=Depends(db)): return {'user':user_public(identity(s,request))}
@app.get('/api/admin/session')
def admin_session(request:Request,s:DBSession=Depends(db)):
    identity(s,request,'admin'); return {'username':'forme'}
@app.patch('/api/customer/profile')
async def profile(request:Request,s:DBSession=Depends(db)):
    user=identity(s,request); d=await body(request)
    user.full_name=text_field(d,'full_name',120,False); user.phone=text_field(d,'phone',40,False)
    s.commit(); return {'user':user_public(user)}
TEMPLATES=['01','02','03','04','05','06','05-magnetic']
@app.get('/api/customer/templates')
def templates(request:Request,s:DBSession=Depends(db)):
    identity(s,request); return {'items':[{'id':i} for i in TEMPLATES]}
def owned(s,cls,id,user):
    row=s.get(cls,id)
    if not row or row.user_id!=user.id: fail('NOT_FOUND',404)
    return row
@app.post('/api/uploads/init')
async def init_upload(request:Request,s:DBSession=Depends(db)):
    user=identity(s,request); d=await body(request); rate(s,request,'upload',30,3600)
    size=d.get('byte_size')
    if type(size) is not int or size<12 or size>512*1024**2: fail('INVALID_FILE_SIZE')
    content_type=text_field(d,'content_type',80)
    if content_type not in ('video/mp4','video/quicktime','video/webm'): fail('INVALID_VIDEO_TYPE')
    used=s.scalar(select(func.coalesce(func.sum(Upload.byte_size),0)).where(Upload.user_id==user.id))
    if used+size>3*1024**3 or shutil.disk_usage(DATA).free<size+1024**3: fail('STORAGE_LIMIT',413)
    row=Upload(user_id=user.id,filename=Path(text_field(d,'filename',180)).name,content_type=content_type,byte_size=size)
    s.add(row); s.commit(); return {'uploadId':row.id,'uploadUrl':f'/api/uploads/{row.id}/content'}
async def save_stream(request,path,limit,kind,expected=None):
    declared=request.headers.get('content-length')
    if declared and int(declared)>limit: fail('FILE_TOO_LARGE',413)
    tmp=path.with_name(path.name+'.'+uid()+'.part'); size=0; first=b''; digest=hashlib.sha256()
    try:
        with tmp.open('wb') as f:
            async for chunk in request.stream():
                size+=len(chunk)
                if size>limit: fail('FILE_TOO_LARGE',413)
                if len(first)<64: first=(first+chunk)[:64]
                digest.update(chunk); f.write(chunk)
        if not size or (expected is not None and size!=expected): fail('FILE_SIZE_MISMATCH')
        image=first.startswith(b'\xff\xd8\xff') or first.startswith(b'\x89PNG\r\n\x1a\n') or (first[:4]==b'RIFF' and first[8:12]==b'WEBP')
        if kind=='video' and not (first[4:8]==b'ftyp' or first.startswith(b'\x1aE\xdf\xa3')): fail('INVALID_VIDEO_CONTENT')
        if kind=='image' and not image: fail('INVALID_IMAGE_CONTENT')
        if kind=='proof' and not (image or first.startswith(b'%PDF-')): fail('INVALID_PROOF_CONTENT')
        if kind=='glb' and not first.startswith(b'glTF'): fail('INVALID_MODEL_CONTENT')
        os.replace(tmp,path)
        return digest.hexdigest()
    finally: tmp.unlink(missing_ok=True)
@app.put('/api/uploads/{id}/content')
async def upload_content(id:str,request:Request,s:DBSession=Depends(db)):
    user=identity(s,request); row=owned(s,Upload,id,user)
    if row.status!='pending': fail('UPLOAD_ALREADY_RECEIVED',409)
    # Database claim stops two requests from replacing the same source file.
    changed=s.execute(update(Upload).where(Upload.id==id,Upload.status=='pending').values(status='receiving')).rowcount; s.commit()
    if not changed: fail('UPLOAD_BUSY',409)
    try: row.sha256=await save_stream(request,DATA/(id+'.video'),row.byte_size,'video',row.byte_size); row.status='received'; s.commit()
    except BaseException: row.status='pending'; s.commit(); raise
    return {'ok':True}
@app.post('/api/uploads/{id}/complete')
def upload_complete(id:str,request:Request,s:DBSession=Depends(db)):
    row=owned(s,Upload,id,identity(s,request))
    if row.status not in ('received','complete'): fail('UPLOAD_INCOMPLETE')
    row.status='complete'; s.commit(); return {'ok':True}
def design_json(s,row,admin=False):
    d=fields(row,('inspiration_file','model_file'))
    d['model']={'stage':row.model_stage}
    d['events']=[fields(e) for e in s.scalars(select(ModelingEvent).where(ModelingEvent.submission_id==row.id).order_by(ModelingEvent.created_at,ModelingEvent.id))]
    prefix='admin' if admin else 'customer'
    d['video_url']=f'/api/{prefix}/submissions/{row.id}/files/video'
    d['inspiration_url']=f'/api/{prefix}/submissions/{row.id}/files/inspiration' if row.inspiration_file else None
    d['model_url']=f'/api/{prefix}/submissions/{row.id}/files/model' if row.model_file and (admin or row.status=='ready') else None
    return d
@app.post('/api/customer/submissions')
async def submit(request:Request,s:DBSession=Depends(db)):
    user=identity(s,request); d=await body(request)
    upload=owned(s,Upload,text_field(d,'upload_id',32),user)
    if upload.status!='complete': fail('UPLOAD_INCOMPLETE')
    template=text_field(d,'template_id',20); color=text_field(d,'color',40); material=text_field(d,'material',40)
    if template not in TEMPLATES or material not in ('PLA','ABS','Lightweight Polymer','Durable Nylon','Premium Resin'): fail('INVALID_DESIGN')
    if color not in ('Satin Silver','Deep Charcoal','Soft Sand','Ocean Blue') and not re.fullmatch(r'#[a-fA-F0-9]{6}',color): fail('INVALID_COLOR')
    existing=s.scalar(select(Submission).where(Submission.upload_id==upload.id))
    if existing: return {'submissionId':existing.id}
    row=Submission(user_id=user.id,upload_id=upload.id,template_id=template,color=color,material=material,inspiration=text_field(d,'inspiration',500,False))
    s.add(row)
    try: s.flush()
    except IntegrityError:
        s.rollback(); return {'submissionId':s.scalar(select(Submission).where(Submission.upload_id==upload.id)).id}
    s.add(ModelingEvent(submission_id=row.id,status=row.status or 'needs_capture_review',stage='queued',note='影片與設計已收到，等待人工審核。',actor='customer'))
    audit(s,'design_submitted',row.id,user.id); s.commit(); return {'submissionId':row.id}
@app.get('/api/customer/submissions')
def designs(request:Request,s:DBSession=Depends(db)):
    user=identity(s,request); return {'items':[design_json(s,x) for x in s.scalars(select(Submission).where(Submission.user_id==user.id).order_by(Submission.created_at.desc()))]}
@app.get('/api/customer/submissions/{id}')
def design(id:str,request:Request,s:DBSession=Depends(db)): return design_json(s,owned(s,Submission,id,identity(s,request)))
@app.put('/api/customer/submissions/{id}/inspiration-image')
async def inspiration(id:str,request:Request,s:DBSession=Depends(db)):
    row=owned(s,Submission,id,identity(s,request)); filename=uid()+'.image'
    await save_stream(request,DATA/filename,10*1024**2,'image')
    row.inspiration_file=filename; row.updated_at=now(); s.commit(); return {'ok':True}
@app.get('/api/{role}/submissions/{id}/files/{kind}')
def design_file(role:str,id:str,kind:str,request:Request,s:DBSession=Depends(db)):
    if role=='admin': identity(s,request,'admin'); row=s.get(Submission,id)
    elif role=='customer': row=owned(s,Submission,id,identity(s,request))
    else: fail('NOT_FOUND',404)
    if not row: fail('NOT_FOUND',404)
    if kind=='video': upload=s.get(Upload,row.upload_id); path=DATA/(upload.id+'.video'); filename=upload.filename
    elif kind=='model':
        if role=='customer' and row.status!='ready': fail('MODEL_NOT_RELEASED',404)
        path=DATA/(row.model_file or 'absent'); filename=row.model_filename or 'model.glb'
    elif kind=='inspiration': path=DATA/(row.inspiration_file or 'absent'); filename='inspiration.image'
    else: fail('NOT_FOUND',404)
    if not path.is_file(): fail('NOT_FOUND',404)
    return FileResponse(path,filename=filename,media_type='application/octet-stream',headers={'Content-Security-Policy':"sandbox; default-src 'none'"})
@app.get('/api/admin/users')
def admin_users(request:Request,q:str='',s:DBSession=Depends(db)):
    identity(s,request,'admin'); query=select(User).order_by(User.id.desc())
    if q: query=query.where(User.email.contains(q[:100])|User.username.contains(q[:100]))
    return {'items':[dict(user_public(u),design_count=s.scalar(select(func.count(Submission.id)).where(Submission.user_id==u.id)),order_count=s.scalar(select(func.count(Order.id)).where(Order.user_id==u.id))) for u in s.scalars(query)]}
@app.get('/api/admin/users/{id}')
def admin_user(id:int,request:Request,s:DBSession=Depends(db)):
    identity(s,request,'admin'); user=s.get(User,id)
    if not user: fail('NOT_FOUND',404)
    return {'user':user_public(user),'submissions':[design_json(s,x,True) for x in s.scalars(select(Submission).where(Submission.user_id==id).order_by(Submission.created_at.desc()))], 'orders':[order_json(s,x,True) for x in s.scalars(select(Order).where(Order.user_id==id).order_by(Order.created_at.desc()))]}
@app.patch('/api/admin/submissions/{id}')
async def review_design(id:str,request:Request,s:DBSession=Depends(db)):
    identity(s,request,'admin'); row=s.get(Submission,id)
    if not row: fail('NOT_FOUND',404)
    d=await body(request)
    status=text_field(d,'status',32); stage=text_field(d,'model_stage',32)
    if status not in ('needs_capture_review','needs_recapture','accepted','modeling','ready','rejected'): fail('INVALID_STATUS')
    if stage not in ('queued','extracting_frames','features','matching','sparse_reconstruction','dense_reconstruction','scale_review','modeling','ready','stopped'): fail('INVALID_STAGE')
    if status=='ready' and not row.model_file: fail('MODEL_REQUIRED_FOR_READY',409)
    row.status=status; row.model_stage=stage; row.admin_note=text_field(d,'admin_note',2000,False); row.updated_at=now()
    job=s.get(WorkerJob,id)
    if status=='accepted' and (job is None or job.state in ('blocked','completed')):
        if job is None: s.add(WorkerJob(submission_id=id,state='queued'))
        else: job.state='queued'; job.lease_hash=None; job.lease_until=0
    elif status in ('needs_recapture','rejected') and job:
        job.state='blocked'; job.lease_hash=None; job.lease_until=0
    elif status=='ready' and job:
        job.state='completed'; job.lease_hash=None; job.lease_until=0
    if 'quote_hkd' in d: row.quote_hkd=money(d['quote_hkd']) if d['quote_hkd'] not in ('',None) else None
    s.add(ModelingEvent(submission_id=id,status=status,stage=stage,note=row.admin_note,actor='admin'))
    audit(s,'design_reviewed',id,'admin',json.dumps(d,ensure_ascii=False)); s.commit(); return design_json(s,row,True)
@app.put('/api/admin/submissions/{id}/model')
async def attach_model(id:str,request:Request,s:DBSession=Depends(db)):
    identity(s,request,'admin'); row=s.get(Submission,id)
    if not row: fail('NOT_FOUND',404)
    filename=Path(request.headers.get('x-file-name','model.glb')).name[:180]
    ext=Path(filename).suffix.lower()
    if ext not in ('.glb','.stl','.3mf'): fail('INVALID_MODEL_TYPE')
    stored=uid()+ext; await save_stream(request,DATA/stored,100*1024**2,'glb' if ext=='.glb' else 'model')
    row.model_file=stored; row.model_filename=filename; row.updated_at=now(); audit(s,'model_uploaded',id,'admin',filename); s.commit(); return {'ok':True}
@app.get('/api/worker/jobs')
def worker_jobs(request:Request,s:DBSession=Depends(db)):
    worker_identity(request)
    rows=s.scalars(select(WorkerJob).where(WorkerJob.state=='monitoring').order_by(WorkerJob.updated_at)).all()
    return {'items':[{'submissionId':row.submission_id,'artifactSha256':row.artifact_sha256} for row in rows]}
@app.post('/api/worker/claim')
def worker_claim(request:Request,s:DBSession=Depends(db)):
    worker_identity(request)
    # Include submissions approved before the worker table was deployed.
    old_approved=s.scalars(select(Submission.id).outerjoin(WorkerJob,WorkerJob.submission_id==Submission.id)
        .where(Submission.status=='accepted',WorkerJob.submission_id==None).limit(100)).all()
    for approved_id in old_approved:
        try:
            s.add(WorkerJob(submission_id=approved_id,state='queued')); s.commit()
        except IntegrityError:
            s.rollback()
    current=int(time.time())
    candidates=s.scalars(select(WorkerJob).join(Submission,WorkerJob.submission_id==Submission.id)
        .where(Submission.status=='accepted',or_(WorkerJob.state=='queued',((WorkerJob.state=='running')&(WorkerJob.lease_until<current))))
        .order_by(WorkerJob.updated_at).limit(20)).all()
    for job in candidates:
        token=secrets.token_urlsafe(32)
        changed=s.execute(update(WorkerJob).where(WorkerJob.submission_id==job.submission_id,
            or_(WorkerJob.state=='queued',((WorkerJob.state=='running')&(WorkerJob.lease_until<current))))
            .values(state='running',lease_hash=hashlib.sha256(token.encode()).hexdigest(),lease_until=current+900,updated_at=now())).rowcount
        s.commit()
        if changed:
            row=s.get(Submission,job.submission_id)
            upload=s.get(Upload,row.upload_id)
            return {'job':{'schemaVersion':1,'submissionId':row.id,'uploadId':upload.id,'filename':upload.filename,
                'contentType':upload.content_type,'byteSize':upload.byte_size,'sha256':upload.sha256,
                'templateId':row.template_id,'color':row.color,'material':row.material,'inspiration':row.inspiration},
                'jobToken':token}
    return {'job':None}
@app.get('/api/worker/jobs/{id}/video')
def worker_video(id:str,request:Request,s:DBSession=Depends(db)):
    worker_identity(request)
    job=s.get(WorkerJob,id)
    if not job or job.state not in ('running','monitoring'): fail('JOB_NOT_FOUND',404)
    row=s.get(Submission,id); upload=s.get(Upload,row.upload_id)
    path=DATA/(upload.id+'.video')
    if not path.is_file() or upload.status!='complete': fail('VIDEO_NOT_FOUND',404)
    return FileResponse(path,media_type='application/octet-stream',headers={'X-Content-SHA256':upload.sha256})
@app.post('/api/worker/jobs/{id}/imported')
def worker_imported(id:str,request:Request,s:DBSession=Depends(db)):
    worker_identity(request)
    existing=s.get(WorkerJob,id)
    if existing and existing.state=='monitoring': return {'ok':True}
    job=leased_job(s,id,request)
    job.state='monitoring'; job.lease_hash=None; job.lease_until=0; job.updated_at=now()
    audit(s,'worker_imported',id,'worker'); s.commit()
    return {'ok':True}
@app.post('/api/worker/jobs/{id}/requeue')
def worker_requeue(id:str,request:Request,s:DBSession=Depends(db)):
    worker_identity(request)
    job=s.get(WorkerJob,id)
    if not job or job.state!='monitoring': fail('JOB_NOT_FOUND',404)
    job.state='queued'; job.lease_hash=None; job.lease_until=0; job.updated_at=now()
    audit(s,'worker_requeued',id,'worker','Local import missing; retrying source transfer'); s.commit()
    return {'ok':True}
@app.post('/api/worker/jobs/{id}/heartbeat')
def worker_heartbeat(id:str,request:Request,s:DBSession=Depends(db)):
    job=leased_job(s,id,request)
    job.lease_until=int(time.time())+900; job.updated_at=now(); s.commit()
    return {'ok':True}
@app.post('/api/worker/jobs/{id}/progress')
async def worker_progress(id:str,request:Request,s:DBSession=Depends(db)):
    worker_identity(request)
    job=s.get(WorkerJob,id); row=s.get(Submission,id)
    if not job or job.state!='monitoring' or not row: fail('JOB_NOT_FOUND',404)
    d=await body(request)
    stage=text_field(d,'stage',32); note=text_field(d,'note',500,False)
    if stage not in ('queued','extracting_frames','features','matching','sparse_reconstruction','dense_reconstruction','scale_review','modeling','stopped'): fail('INVALID_STAGE')
    status=text_field(d,'status',32)
    if status not in ('accepted','modeling','needs_recapture','rejected'): fail('INVALID_STATUS')
    if row.model_stage==stage and row.status==status and row.admin_note==note: return {'ok':True}
    row.model_stage=stage; row.status=status; row.admin_note=note; row.updated_at=now()
    s.add(ModelingEvent(submission_id=id,status=status,stage=stage,note=note,actor='worker'))
    if status in ('needs_recapture','rejected'): job.state='blocked'
    audit(s,'worker_progress',id,'worker',stage); s.commit()
    return {'ok':True}
@app.put('/api/worker/jobs/{id}/artifact')
async def worker_artifact(id:str,request:Request,s:DBSession=Depends(db)):
    worker_identity(request)
    job=s.get(WorkerJob,id); row=s.get(Submission,id)
    if not job or job.state!='monitoring' or not row: fail('JOB_NOT_FOUND',404)
    filename=Path(request.headers.get('x-file-name','cover-trial.3mf')).name[:180]
    ext=Path(filename).suffix.lower()
    if ext not in ('.glb','.stl','.3mf'): fail('INVALID_MODEL_TYPE')
    stored=uid()+ext
    digest=await save_stream(request,DATA/stored,100*1024**2,'glb' if ext=='.glb' else 'model')
    expected=request.headers.get('x-content-sha256','')
    if not re.fullmatch(r'[a-f0-9]{64}',expected) or digest!=expected:
        (DATA/stored).unlink(missing_ok=True); fail('ARTIFACT_HASH_MISMATCH')
    old=row.model_file
    row.model_file=stored; row.model_filename=filename; row.updated_at=now(); job.artifact_sha256=digest
    audit(s,'worker_artifact',id,'worker',digest); s.commit()
    if old: (DATA/old).unlink(missing_ok=True)
    return {'ok':True,'sha256':digest,'reviewRequired':True}
async def local_proxy(request:Request,s:DBSession,source:str,path:str=''):
    identity(s,request,'admin')
    if not LOCAL_OPERATOR_TOKEN: fail('LOCAL_OPERATOR_NOT_CONFIGURED',503)
    if any(part in ('.','..') for part in path.split('/')): fail('INVALID_LOCAL_PATH',400)
    clean='/'.join(quote(part,safe='-_.') for part in path.split('/'))
    upstream=LOCAL_OPERATOR_URL+'/'+source+('/'+clean if clean or source=='operator' else '')
    if request.url.query: upstream+='?'+request.url.query
    headers={'Authorization':'Bearer '+LOCAL_OPERATOR_TOKEN}
    for name in ('content-type','range','if-range'):
        if request.headers.get(name): headers[name]=request.headers[name]
    payload=b'' if request.method in ('GET','HEAD') else await request.body()
    if len(payload)>65536: fail('LOCAL_REQUEST_TOO_LARGE',413)
    client=httpx.AsyncClient(timeout=httpx.Timeout(30.0,read=300.0),follow_redirects=False,trust_env=False)
    try:
        upstream_request=client.build_request(request.method,upstream,headers=headers,content=payload)
        response=await client.send(upstream_request,stream=True)
    except httpx.RequestError:
        await client.aclose()
        fail('LOCAL_MAC_OFFLINE',503)
    forward={key:response.headers[key] for key in ('content-type','content-length','content-disposition','content-range','accept-ranges') if key in response.headers}
    if source=='operator' and (path=='' or path.endswith('.html')):
        forward['Content-Security-Policy']="default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
    async def chunks():
        try:
            if response.is_stream_consumed:
                yield response.content
            else:
                async for chunk in response.aiter_raw(): yield chunk
        finally:
            await response.aclose()
            await client.aclose()
    return StreamingResponse(chunks(),status_code=response.status_code,headers=forward)
@app.api_route('/api/admin/operator/',methods=['GET'])
async def operator_home(request:Request,s:DBSession=Depends(db)):
    try:
        return await local_proxy(request,s,'operator','')
    except HTTPException as exc:
        if exc.status_code!=503: raise
        return HTMLResponse('<!doctype html><html lang="zh-Hans"><meta charset="utf-8"><title>本机工作流离线</title><main style="font:18px system-ui;max-width:42rem;margin:10vh auto"><h1>本机工作流暂不可用</h1><p>Mac 或管理隧道离线。云端用户任务与订单仍可在管理平台查看。</p><a href="/admin.html">返回管理平台</a></main></html>',status_code=503)
@app.api_route('/api/admin/operator/{path:path}',methods=['GET'])
async def operator_asset(path:str,request:Request,s:DBSession=Depends(db)):
    return await local_proxy(request,s,'operator',path)
@app.api_route('/api/internal/{path:path}',methods=['GET','POST','PUT','PATCH'])
async def operator_internal(path:str,request:Request,s:DBSession=Depends(db)):
    return await local_proxy(request,s,'api/internal',path)
@app.get('/api/uploads')
async def operator_uploads(request:Request,s:DBSession=Depends(db)):
    return await local_proxy(request,s,'api/uploads')
@app.get('/api/uploads/{path:path}')
async def operator_upload_detail(path:str,request:Request,s:DBSession=Depends(db)):
    return await local_proxy(request,s,'api/uploads',path)
def order_json(s,row,admin=False):
    d=fields(row); d['delivery']=fields(s.scalar(select(Delivery).where(Delivery.order_id==row.id)))
    d['payments']=[]
    for p in s.scalars(select(Payment).where(Payment.order_id==row.id).order_by(Payment.created_at.desc())):
        item=fields(p,('proof_file',)); item['proof_url']=f'/api/{"admin" if admin else "customer"}/payments/{p.id}/proof' if p.proof_file else None; d['payments'].append(item)
    return d
@app.post('/api/customer/orders')
async def place_order(request:Request,s:DBSession=Depends(db)):
    user=identity(s,request); d=await body(request); row=owned(s,Submission,text_field(d,'submission_id',32),user)
    if row.status!='ready' or not row.quote_hkd: fail('DESIGN_NOT_READY_FOR_ORDER',409)
    existing=s.scalar(select(Order).where(Order.submission_id==row.id))
    if existing: return order_json(s,existing)
    shipping={key:text_field(d,key,maxlen) for key,maxlen in [('recipient_name',120),('recipient_phone',40),('address_line',500),('region',100),('district',100)]}
    shipping['delivery_note']=text_field(d,'delivery_note',1000,False)
    order=Order(user_id=user.id,submission_id=row.id,order_number='F'+datetime.now(timezone.utc).strftime('%Y%m%d')+'-'+secrets.token_hex(4).upper(),amount_hkd=row.quote_hkd)
    s.add(order)
    try: s.flush()
    except IntegrityError:
        s.rollback(); return order_json(s,s.scalar(select(Order).where(Order.submission_id==row.id)))
    s.add(Delivery(order_id=order.id,**shipping)); audit(s,'order_placed',order.id,user.id); s.commit(); return order_json(s,order)
@app.get('/api/customer/orders')
def customer_orders(request:Request,s:DBSession=Depends(db)):
    user=identity(s,request); return {'items':[order_json(s,x) for x in s.scalars(select(Order).where(Order.user_id==user.id).order_by(Order.created_at.desc()))]}
@app.post('/api/customer/orders/{id}/payments')
async def submit_payment(id:str,request:Request,s:DBSession=Depends(db)):
    user=identity(s,request); order=owned(s,Order,id,user)
    if order.payment_status=='paid' or order.order_status=='cancelled': fail('PAYMENT_NOT_ALLOWED',409)
    d=await body(request); payment=Payment(order_id=id,method=text_field(d,'method',80),reference=text_field(d,'reference',120))
    s.add(payment); order.payment_status='submitted'; audit(s,'payment_submitted',id,user.id); s.commit(); return {'paymentId':payment.id}
@app.put('/api/customer/payments/{id}/proof')
async def proof(id:str,request:Request,s:DBSession=Depends(db)):
    user=identity(s,request); payment=s.get(Payment,id)
    if not payment: fail('NOT_FOUND',404)
    owned(s,Order,payment.order_id,user)
    if payment.status!='submitted': fail('PAYMENT_ALREADY_REVIEWED',409)
    filename=uid()+'.proof'; await save_stream(request,DATA/filename,20*1024**2,'proof')
    payment.proof_file=filename; payment.proof_filename=Path(request.headers.get('x-file-name','payment-proof')).name[:180]; s.commit(); return {'ok':True}
@app.get('/api/{role}/payments/{id}/proof')
def proof_file(role:str,id:str,request:Request,s:DBSession=Depends(db)):
    payment=s.get(Payment,id)
    if not payment: fail('NOT_FOUND',404)
    if role=='admin': identity(s,request,'admin')
    elif role=='customer': owned(s,Order,payment.order_id,identity(s,request))
    else: fail('NOT_FOUND',404)
    path=DATA/(payment.proof_file or 'absent')
    if not path.is_file(): fail('NOT_FOUND',404)
    return FileResponse(path,filename=payment.proof_filename or 'proof',media_type='application/octet-stream',headers={'Content-Security-Policy':"sandbox; default-src 'none'"})
@app.patch('/api/admin/payments/{id}')
async def review_payment(id:str,request:Request,s:DBSession=Depends(db)):
    identity(s,request,'admin'); payment=s.get(Payment,id)
    if not payment: fail('NOT_FOUND',404)
    d=await body(request); status=text_field(d,'status',24)
    if status not in ('confirmed','rejected') or payment.status!='submitted': fail('INVALID_PAYMENT_REVIEW',409)
    payment.status=status; payment.review_note=text_field(d,'review_note',1000,False); payment.reviewed_at=now()
    order=s.scalar(select(Order).where(Order.id==payment.order_id).with_for_update())
    if order.payment_status=='paid' and status=='confirmed': fail('ALREADY_PAID',409)
    confirmed=s.scalar(select(func.count(Payment.id)).where(Payment.order_id==order.id,Payment.status=='confirmed'))
    order.payment_status='paid' if confirmed else ('submitted' if s.scalar(select(func.count(Payment.id)).where(Payment.order_id==order.id,Payment.status=='submitted')) else 'pending')
    audit(s,'payment_reviewed',id,'admin',json.dumps(d,ensure_ascii=False)); s.commit(); return {'ok':True}
@app.patch('/api/admin/orders/{id}')
async def ship_order(id:str,request:Request,s:DBSession=Depends(db)):
    identity(s,request,'admin'); order=s.scalar(select(Order).where(Order.id==id).with_for_update())
    if not order: fail('NOT_FOUND',404)
    d=await body(request); status=text_field(d,'order_status',24)
    flow={'placed':{'placed','modeling','printing','cancelled'},'modeling':{'modeling','printing','cancelled'},'printing':{'printing','shipped','cancelled'},'shipped':{'shipped','delivered'},'delivered':{'delivered'},'cancelled':{'cancelled'}}
    if status not in flow.get(order.order_status,set()): fail('INVALID_ORDER_TRANSITION',409)
    if status in ('modeling','printing','shipped','delivered') and order.payment_status!='paid': fail('PAYMENT_NOT_CONFIRMED',409)
    delivery=s.scalar(select(Delivery).where(Delivery.order_id==id))
    if delivery.confirmed_at and status!='delivered': fail('ALREADY_RECEIVED',409)
    carrier=text_field(d,'carrier',100,False); tracking=text_field(d,'tracking_number',120,False)
    if status in ('shipped','delivered') and (not carrier or not tracking): fail('TRACKING_REQUIRED')
    order.order_status=status; order.updated_at=now(); delivery.carrier=carrier; delivery.tracking_number=tracking
    delivery.delivery_status={'placed':'pending','modeling':'preparing','printing':'preparing','shipped':'shipped','delivered':'delivered','cancelled':'cancelled'}[status]
    if status=='shipped' and not delivery.shipped_at: delivery.shipped_at=now()
    if status=='delivered' and not delivery.delivered_at: delivery.delivered_at=now()
    delivery.updated_at=now(); audit(s,'order_updated',id,'admin',json.dumps(d,ensure_ascii=False)); s.commit(); return order_json(s,order,True)
@app.post('/api/customer/orders/{id}/confirm-receipt')
def confirm_receipt(id:str,request:Request,s:DBSession=Depends(db)):
    user=identity(s,request); order=owned(s,Order,id,user)
    if order.order_status not in ('shipped','delivered'): fail('ORDER_NOT_SHIPPED',409)
    delivery=s.scalar(select(Delivery).where(Delivery.order_id==id))
    if not delivery.confirmed_at:
        delivery.confirmed_at=now(); delivery.delivered_at=delivery.delivered_at or now(); delivery.delivery_status='delivered'; delivery.updated_at=now()
        order.order_status='delivered'; order.updated_at=now(); audit(s,'receipt_confirmed',id,user.id); s.commit()
    return {'ok':True}
