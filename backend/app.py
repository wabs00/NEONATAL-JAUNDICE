"""Local-first assessment records API. No diagnostic model is bundled."""
import hashlib
import csv
import hmac
import io
import logging
import os
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv('NEO_DATA_DIR', str(ROOT / 'data')))
MAX_IMAGE = 8 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000

@contextmanager
def db():
    conn = sqlite3.connect(DATA / 'neo.db', timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

@asynccontextmanager
async def lifespan(app):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / 'images').mkdir(exist_ok=True)
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS nurses (nurse_id TEXT PRIMARY KEY, full_name TEXT NOT NULL,
          email TEXT UNIQUE NOT NULL, facility TEXT NOT NULL, password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, nurse_id TEXT NOT NULL REFERENCES nurses(nurse_id), expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS assessments (id INTEGER PRIMARY KEY, nurse_id TEXT NOT NULL REFERENCES nurses(nurse_id),
          baby_id TEXT NOT NULL, age_days INTEGER NOT NULL, weight REAL NOT NULL, gestational_age INTEGER NOT NULL,
          feeding_type TEXT NOT NULL, image_path TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Pending review',
          notes TEXT NOT NULL DEFAULT '', bilirubin REAL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE INDEX IF NOT EXISTS assessments_owner_date ON assessments(nurse_id, id DESC);
        CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires);
        CREATE TABLE IF NOT EXISTS research_predictions (id INTEGER PRIMARY KEY, assessment_id INTEGER NOT NULL REFERENCES assessments(id),
          model_id TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        CREATE UNIQUE INDEX IF NOT EXISTS research_record_model ON research_predictions(assessment_id,model_id);
        ''')
        columns = {row['name'] for row in c.execute('PRAGMA table_info(assessments)')}
        if 'consent_recorded' not in columns:
            c.execute('ALTER TABLE assessments ADD COLUMN consent_recorded INTEGER')
    app.state.research_model = None
    app.state.research_model_error = False
    if os.getenv('NEO_ENABLE_RESEARCH_MODEL') == '1':
        try:
            from ml.vision import ResearchModel
            directory = Path(os.getenv('NEO_RESEARCH_MODEL_DIR', str(ROOT / 'models' / 'research')))
            app.state.research_model = await run_in_threadpool(ResearchModel, directory)
        except Exception:
            app.state.research_model_error = True
            logging.getLogger('neojaundice').exception('Research model could not be loaded')
    yield

app = FastAPI(title='NeoJaundice AI', version='2.2.0', lifespan=lifespan)

@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Raw inputs may contain NaN/Infinity, passwords or patient text; return safe diagnostics.
    detail = [{'type': item['type'], 'loc': item['loc'], 'msg': item['msg']} for item in error.errors()]
    return JSONResponse(status_code=422, content={'detail': detail})
origins = [x.strip() for x in os.getenv('NEO_CORS_ORIGINS', 'http://localhost:8081,http://localhost:8000,http://127.0.0.1:8000').split(',')]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                   allow_methods=['GET', 'POST', 'PATCH'], allow_headers=['Authorization', 'Content-Type'])

def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + digest

def verify_password(password, stored):
    salt, digest = stored.split(':')
    candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(candidate, digest)

bearer_security = HTTPBearer(auto_error=False, description='Revocable nurse session token returned by /auth/login')

def current_nurse(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_security)):
    bearer = request.headers.get('authorization', '')
    if bearer and credentials is None:
        raise HTTPException(401, 'Please sign in again')
    token = credentials.credentials.strip() if credentials else request.cookies.get('neo_session', '')
    request.state.session_token = token
    with db() as c:
        user = c.execute('SELECT n.nurse_id,n.full_name,n.email,n.facility FROM sessions s JOIN nurses n USING(nurse_id) WHERE s.token=? AND s.expires>?',
                         (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    if not user:
        raise HTTPException(401, 'Please sign in again')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and credentials is None:
        origin = request.headers.get('origin')
        if origin and origin not in origins and origin != str(request.base_url).rstrip('/'):
            raise HTTPException(403, 'Untrusted request origin')
    return dict(user)

class Register(BaseModel):
    nurse_id: str = Field(min_length=2, max_length=60, pattern=r'^[A-Za-z0-9_-]+$')
    full_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=200, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    facility: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=10, max_length=128)

    @field_validator('nurse_id', 'full_name', 'email', 'facility', mode='before')
    @classmethod
    def trim_details(cls, value):
        return value.strip() if isinstance(value, str) else value

class Login(BaseModel):
    nurse_id: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=128)

    @field_validator('nurse_id', mode='before')
    @classmethod
    def trim_id(cls, value):
        return value.strip() if isinstance(value, str) else value

@app.post('/auth/register', status_code=201)
def register(body: Register):
    try:
        with db() as c:
            c.execute('INSERT INTO nurses VALUES(?,?,?,?,?)',
                      (body.nurse_id, body.full_name.strip(), body.email.lower(), body.facility.strip(), hash_password(body.password)))
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'Nurse ID or email already registered')
    return {'message': 'Account created. You can now sign in.'}

# Bounded local throttle; use a shared rate limiter behind a production proxy.
attempts = {}
@app.post('/auth/login')
def login(body: Login, request: Request, response: Response):
    key = request.client.host if request.client else 'local'
    now = time.time()
    for stale in [k for k,v in attempts.items() if now-v[0] > 300]:
        attempts.pop(stale, None)
    count = attempts.get(key, (now, 0))
    if count[1] >= 10:
        raise HTTPException(429, 'Too many attempts. Try again in five minutes.')
    attempts[key] = (count[0], count[1]+1)
    with db() as c:
        user = c.execute('SELECT * FROM nurses WHERE nurse_id=?', (body.nurse_id,)).fetchone()
        stored = user['password'] if user else hash_password('dummy-password')
        if not verify_password(body.password, stored) or not user:
            raise HTTPException(401, 'Invalid Nurse ID or password')
        token = secrets.token_urlsafe(32)
        c.execute('DELETE FROM sessions WHERE expires<=?', (now,))
        c.execute('INSERT INTO sessions VALUES(?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), body.nurse_id, now+3600*8))
    attempts.pop(key, None)
    response.set_cookie('neo_session', token, httponly=True, samesite='strict', max_age=28800,
                        secure=os.getenv('NEO_SECURE_COOKIE') == '1')
    return {'access_token': token, 'token_type': 'bearer', 'nurse_id': body.nurse_id}

@app.get('/auth/me')
def me(nurse=Depends(current_nurse)):
    return nurse

@app.post('/auth/logout')
def logout(request: Request, response: Response, nurse=Depends(current_nurse)):
    token = request.state.session_token
    with db() as c:
        c.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie('neo_session')
    return {'message': 'Signed out'}

def prepare_image(raw):
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValueError('Unsupported image')
            width, height = im.size
            if width * height > Image.MAX_IMAGE_PIXELS:
                raise ValueError('Image dimensions exceed limit')
            im.load()
            im = ImageOps.exif_transpose(im).convert('RGB')
            im.thumbnail((1600, 1600))
            dest = io.BytesIO()
            im.save(dest, format='JPEG', quality=82, optimize=True)
            return dest.getvalue(), width, height
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, 'Choose a valid JPEG, PNG or WebP image under 20 megapixels')

@app.post('/assessment', status_code=201)
async def assess(baby_id: str = Form(..., min_length=1, max_length=80), age_days: int = Form(..., ge=0, le=28),
                 weight: float = Form(..., gt=0, le=10), gestational_age: int = Form(..., ge=20, le=44),
                 feeding_type: str = Form(...), notes: str = Form('', max_length=2000),
                 consent: bool = Form(...), image: UploadFile = File(...), nurse=Depends(current_nurse)):
    if not consent:
        raise HTTPException(422, 'Confirm permission to collect and store the assessment photo')
    if not baby_id.strip() or feeding_type not in ('Breastfeeding', 'Formula', 'Mixed'):
        raise HTTPException(422, 'Check baby ID and feeding type')
    raw = await image.read(MAX_IMAGE+1)
    await image.close()
    if len(raw) > MAX_IMAGE:
        raise HTTPException(413, 'Image must be smaller than 8 MB')
    encoded, width, height = await run_in_threadpool(prepare_image, raw)
    filename = secrets.token_hex(16) + '.jpg'
    path = DATA / 'images' / filename
    def save():
        path.write_bytes(encoded)
        try:
            with db() as c:
                result = c.execute('INSERT INTO assessments(nurse_id,baby_id,age_days,weight,gestational_age,feeding_type,image_path,notes,consent_recorded) VALUES(?,?,?,?,?,?,?,?,?)',
                    (nurse['nurse_id'], baby_id.strip(), age_days, weight, gestational_age, feeding_type, filename, notes.strip(), 1))
                return result.lastrowid
        except Exception:
            path.unlink(missing_ok=True)
            raise
    record_id = await run_in_threadpool(save)
    return {'assessment_id': record_id, 'baby_id': baby_id.strip(), 'risk': 'Pending clinical review',
            'confidence': None, 'model_status': 'not_available', 'image_dimensions': [width, height],
            'recommendation': 'No diagnostic prediction is available. Record a clinician review and measured bilirubin separately.'}

@app.get('/assessments')
def history(q: str = '', status: str = '', limit: int = 20, offset: int = 0, max_id: int | None = None, nurse=Depends(current_nurse)):
    limit = min(max(limit, 1), 100)
    offset = max(0, offset)
    where = "nurse_id=? AND baby_id LIKE ? ESCAPE '\\'"
    search = q[:80].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    params = [nurse['nurse_id'], '%'+search+'%']
    if status:
        where += ' AND status=?'
        params.append(status)
    with db() as c:
        if max_id is None:
            max_id = c.execute('SELECT COALESCE(MAX(id),0) FROM assessments WHERE nurse_id=?', (nurse['nurse_id'],)).fetchone()[0]
        where += ' AND id<=?'
        params.append(max_id)
        total = c.execute('SELECT COUNT(*) FROM assessments WHERE '+where, params).fetchone()[0]
        records = c.execute('SELECT id AS assessment_id,baby_id,age_days,weight,gestational_age,feeding_type,status,notes,bilirubin,created_at,consent_recorded FROM assessments WHERE '+where+' ORDER BY id DESC LIMIT ? OFFSET ?', params+[limit,offset]).fetchall()
    return {'items': [dict(r) for r in records], 'total': total, 'limit': limit, 'offset': offset, 'snapshot_max_id': max_id}

@app.get('/assessments/{record_id}/image')
def photo(record_id: int, nurse=Depends(current_nurse)):
    with db() as c:
        record = c.execute('SELECT image_path FROM assessments WHERE id=? AND nurse_id=?', (record_id,nurse['nurse_id'])).fetchone()
    if not record:
        raise HTTPException(404, 'Assessment not found')
    path = DATA / 'images' / record['image_path']
    if not path.is_file():
        raise HTTPException(404, 'Stored photo is unavailable')
    return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})

@app.get('/assessments/export')
def export_records(q: str = '', status: str = '', nurse=Depends(current_nurse)):
    # One SELECT captures the matching rows consistently, unlike paged client reads.
    search = q[:80].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    where = "nurse_id=? AND baby_id LIKE ? ESCAPE '\\'"
    params = [nurse['nurse_id'], '%'+search+'%']
    if status:
        where += ' AND status=?'
        params.append(status)
    fields = ['assessment_id','baby_id','age_days','weight','gestational_age','feeding_type','status','bilirubin','notes','created_at']
    with db() as c:
        rows = c.execute('SELECT id AS assessment_id,baby_id,age_days,weight,gestational_age,feeding_type,status,bilirubin,notes,created_at FROM assessments WHERE '+where+' ORDER BY id DESC',params).fetchall()
    def cell(value):
        text = '' if value is None else str(value)
        return "'"+text if text.lstrip().startswith(('=','+','-','@')) else text
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow(fields)
    writer.writerows([cell(row[key]) for key in fields] for row in rows)
    return Response('\ufeff'+buffer.getvalue(),media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition':'attachment; filename="neojaundice-records.csv"'})

class Review(BaseModel):
    status: str = Field(pattern=r'^(Pending review|Reviewed|Referred)$')
    notes: str = Field(default='', max_length=2000)
    bilirubin: float | None = Field(default=None, ge=0, le=100)

@app.patch('/assessments/{record_id}')
def review(record_id: int, body: Review, nurse=Depends(current_nurse)):
    with db() as c:
        updated = c.execute('UPDATE assessments SET status=?,notes=?,bilirubin=? WHERE id=? AND nurse_id=?',
                           (body.status,body.notes,body.bilirubin,record_id,nurse['nurse_id']))
        if not updated.rowcount:
            raise HTTPException(404, 'Assessment not found')
    return {'message': 'Review saved'}

@app.get('/dashboard')
def dashboard(nurse=Depends(current_nurse)):
    with db() as c:
        r = c.execute("SELECT COUNT(*) total, COALESCE(SUM(status='Pending review'),0) pending, COALESCE(SUM(status='Reviewed'),0) reviewed, COALESCE(SUM(status='Referred'),0) referred, MAX(created_at) latest FROM assessments WHERE nurse_id=?", (nurse['nurse_id'],)).fetchone()
    return {**dict(r), 'nurse': nurse, 'model_status': 'not_available'}

@app.get('/health')
def health():
    return {'status': 'ok', 'model_status': 'not_available', 'diagnostic_model_available': False,
            'research_model_available': app.state.research_model is not None, 'version': '2.2.0'}

@app.middleware('http')
async def headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    if not request.url.path.startswith('/assets/'):
        response.headers['Cache-Control'] = 'no-store'
    return response

@app.get('/research/model')
def research_model_status(nurse=Depends(current_nurse)):
    model = app.state.research_model
    return {'available': model is not None, 'research_only': True,
            'model_id': model.metadata['model_id'] if model else None,
            'status': 'available' if model else 'load_error' if app.state.research_model_error else 'disabled',
            'diagnostic_model_available': False}

@app.post('/research/assessments/{record_id}/predict')
async def research_predict(record_id: int, nurse=Depends(current_nurse)):
    import json
    model = app.state.research_model
    if model is None:
        raise HTTPException(503, 'Research model is disabled or unavailable. Clinical diagnosis remains unavailable.')
    with db() as c:
        record = c.execute('SELECT image_path FROM assessments WHERE id=? AND nurse_id=?', (record_id,nurse['nurse_id'])).fetchone()
        if not record:
            raise HTTPException(404, 'Assessment not found')
        cached = c.execute('SELECT result_json FROM research_predictions WHERE assessment_id=? AND model_id=?',
                           (record_id,model.metadata['model_id'])).fetchone()
    path = DATA / 'images' / record['image_path']
    if not path.is_file():
        raise HTTPException(404, 'Stored photo is unavailable')
    if cached:
        return json.loads(cached['result_json'])
    try:
        result = await run_in_threadpool(model.predict, path)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, 'Stored photo could not be analyzed; check image integrity')
    with db() as c:
        c.execute('INSERT OR IGNORE INTO research_predictions(assessment_id,model_id,result_json) VALUES(?,?,?)',
                  (record_id,model.metadata['model_id'],json.dumps(result)))
    return result

app.mount('/', StaticFiles(directory=ROOT / 'web', html=True), name='web')
