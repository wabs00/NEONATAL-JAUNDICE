"""Isolated functional/security regression audit; no user records are touched."""
import hashlib
import io
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
SCRATCH=tempfile.TemporaryDirectory(prefix='neo-functional-audit-',dir=os.getenv('NEO_AUDIT_WORK_DIR'))
os.environ['NEO_DATA_DIR']=SCRATCH.name
os.environ['NEO_ENABLE_RESEARCH_MODEL']='1'
from fastapi.testclient import TestClient
from backend import app as source

REQUESTS=0
def image_bytes(format='JPEG',size=(320,240)):
    buffer=io.BytesIO();Image.new('RGB',size,'#ddc2a8').save(buffer,format=format);return buffer.getvalue()

class Audit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(source.app,raise_server_exceptions=False)
        cls.client.__enter__()
    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None,None,None)
        SCRATCH.cleanup()
    def setUp(self):
        self.client.cookies.clear();source.attempts.clear()
    def call(self,method,path,expected=200,token=None,**kwargs):
        global REQUESTS
        REQUESTS+=1
        headers=kwargs.pop('headers',{})
        if token:headers['Authorization']='Bearer '+token
        result=self.client.request(method,path,headers=headers,**kwargs)
        self.assertEqual(result.status_code,expected,(method,path,result.status_code,result.text[:400]))
        return result
    def account(self):
        name='audit_'+secrets.token_hex(5)
        body=dict(nurse_id=name,full_name='Audit Nurse',email=name+'@example.test',facility='Test Facility',password='test-password-123')
        self.call('POST','/auth/register',201,json=body)
        token=self.call('POST','/auth/login',json={'nurse_id':name,'password':body['password']}).json()['access_token']
        self.client.cookies.clear()
        return token,body
    def upload(self,token,baby='AUDIT-001',format='JPEG',expected=201,**overrides):
        data=dict(baby_id=baby,age_days='2',weight='3.2',gestational_age='38',feeding_type='Mixed',notes='Audit note',consent='true')
        data.update(overrides)
        return self.call('POST','/assessment',expected,token=token,data=data,files={'image':('../../escape.jpg',image_bytes(format),'image/jpeg')})

    def test_01_static_health_headers_and_schema(self):
        self.assertEqual(self.call('GET','/health').json()['version'],'2.2.0')
        for path in ['/','/assets/app.js','/assets/research.js','/assets/style.css','/docs','/openapi.json']:
            response=self.call('GET',path)
            self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
        for path in ['/data/neo.db','/backend/app.py','/models/research/model.json','/../backend/app.py']:
            self.call('GET',path,404)

    def test_02_registration_validation_uniqueness(self):
        token,body=self.account()
        self.call('POST','/auth/register',409,json=body)
        invalid={'full_name':['  ','\t\n'], 'facility':['  '], 'email':['bad-email'], 'nurse_id':['../x','a'], 'password':['short']}
        for key,values in invalid.items():
            for value in values:
                with self.subTest(key=key,value=value):
                    payload={**body,'nurse_id':'audit_'+secrets.token_hex(4),'email':secrets.token_hex(4)+'@example.test',key:value}
                    self.call('POST','/auth/register',422,json=payload)

    def test_03_auth_cookie_bearer_expiry_logout(self):
        token,body=self.account()
        self.call('GET','/auth/me',token=token)
        self.call('GET','/auth/me',401,headers={'Authorization':'Bearer invalid'})
        self.call('POST','/auth/login',json={'nurse_id':body['nurse_id'],'password':body['password']})
        cookie=self.client.cookies.get('neo_session')
        self.assertTrue(cookie)
        cookie_header=self.client.cookies.jar
        self.call('GET','/auth/me')
        self.call('POST','/auth/logout',403,headers={'Origin':'https://untrusted.example'})
        self.call('POST','/auth/logout')
        self.call('GET','/auth/me',401)
        self.client.cookies.clear()
        with source.db() as conn:
            conn.execute('UPDATE sessions SET expires=? WHERE token=?',(time.time()-1,hashlib.sha256(token.encode()).hexdigest()))
        self.call('GET','/auth/me',401,token=token)

    def test_04_upload_formats_validation_and_consent(self):
        token,_=self.account()
        for format in ['JPEG','PNG','WEBP']:
            with self.subTest(format=format):
                record=self.upload(token,format=format).json()
                self.assertIsNone(record['confidence'])
                result=self.call('GET',f"/assessments/{record['assessment_id']}/image",token=token)
                self.assertEqual(Image.open(io.BytesIO(result.content)).format,'JPEG')
        for key,value in [('age_days','-1'),('age_days','29'),('age_days','1.5'),('weight','0'),('weight','nan'),('weight','inf'),('gestational_age','19'),('gestational_age','45'),('feeding_type','Unknown'),('baby_id','  '),('notes','x'*2001),('consent','false')]:
            with self.subTest(key=key,value=value):self.upload(token,expected=422,**{key:value})

    def test_05_byte_pixel_corrupt_filename_limits(self):
        token,_=self.account()
        data=dict(baby_id='LIMIT',age_days='0',weight='1.5',gestational_age='30',feeding_type='Formula',consent='true')
        for payload,expected in [(b'invalid image',422),(b'x'*(8*1024*1024+1),413),(image_bytes('PNG',(5000,4001)),422)]:
            self.call('POST','/assessment',expected,token=token,data=data,files={'image':('../../escape.jpg',payload,'image/jpeg')})
        record=self.upload(token).json()
        with source.db() as conn:filename=conn.execute('SELECT image_path FROM assessments WHERE id=?',(record['assessment_id'],)).fetchone()[0]
        self.assertNotIn('..',filename);self.assertNotIn('/',filename)

    def test_06_record_ownership_and_review_validation(self):
        first,_=self.account();second,_=self.account()
        record=self.upload(first).json()['assessment_id']
        self.assertEqual(self.call('GET','/assessments',token=second).json()['total'],0)
        self.call('GET',f'/assessments/{record}/image',404,token=second)
        self.call('PATCH',f'/assessments/{record}',404,token=second,json={'status':'Reviewed'})
        self.call('POST',f'/research/assessments/{record}/predict',404,token=second)
        for body in [{'status':'Severe'},{'status':'Reviewed','bilirubin':-1},{'status':'Reviewed','bilirubin':101},{'status':'Reviewed','notes':'x'*2001}]:
            self.call('PATCH',f'/assessments/{record}',422,token=first,json=body)
        self.call('PATCH',f'/assessments/{record}',token=first,json={'status':'Referred','notes':'Clinical review','bilirubin':8.2})
        item=self.call('GET','/assessments',token=first).json()['items'][0]
        self.assertEqual((item['status'],item['notes'],item['bilirubin']),('Referred','Clinical review',8.2))

    def test_07_search_literal_filter_pagination_totals(self):
        token,_=self.account()
        self.upload(token,baby='NEO%1');self.upload(token,baby='NEO_2');self.upload(token,baby='OTHER')
        percent=self.call('GET','/assessments',token=token,params={'q':'%'}).json()
        self.assertEqual(percent['total'],1,'Percent search must be literal')
        underscore=self.call('GET','/assessments',token=token,params={'q':'_'}).json()
        self.assertEqual(underscore['total'],1,'Underscore search must be literal')
        first=self.call('GET','/assessments?limit=1&offset=0',token=token).json()
        second=self.call('GET','/assessments?limit=1&offset=1',token=token).json()
        self.assertNotEqual(first['items'][0]['assessment_id'],second['items'][0]['assessment_id'])
        self.call('PATCH',f"/assessments/{first['items'][0]['assessment_id']}",token=token,json={'status':'Reviewed'})
        self.assertEqual(self.call('GET','/assessments?status=Reviewed',token=token).json()['total'],1)
        summary=self.call('GET','/dashboard',token=token).json()
        self.assertEqual((summary['total'],summary['pending'],summary['reviewed'],summary['referred']),(3,2,1,0))

    def test_08_missing_and_corrupt_stored_photo(self):
        token,_=self.account();record=self.upload(token).json()['assessment_id']
        with source.db() as conn:filename=conn.execute('SELECT image_path FROM assessments WHERE id=?',(record,)).fetchone()[0]
        image_path=source.DATA/'images'/filename
        image_path.unlink()
        self.call('GET',f'/assessments/{record}/image',404,token=token)
        self.call('POST',f'/research/assessments/{record}/predict',404,token=token)
        image_path.write_bytes(b'corrupt')
        self.call('POST',f'/research/assessments/{record}/predict',422,token=token)

    def test_09_research_cache_separation_disabled_model(self):
        token,_=self.account();record=self.upload(token).json()['assessment_id']
        status=self.call('GET','/research/model',token=token).json()
        self.assertTrue(status['available']);self.assertFalse(status['diagnostic_model_available'])
        result=self.call('POST',f'/research/assessments/{record}/predict',token=token).json()
        self.assertTrue(result['research_only']);self.assertIsNone(result['clinical_confidence'])
        self.assertEqual(result,self.call('POST',f'/research/assessments/{record}/predict',token=token).json())
        item=self.call('GET','/assessments',token=token).json()['items'][0]
        self.assertEqual(item['status'],'Pending review');self.assertIsNone(item['bilirubin'])
        model=source.app.state.research_model
        try:
            source.app.state.research_model=None
            self.call('POST',f'/research/assessments/{record}/predict',503,token=token)
        finally:source.app.state.research_model=model

    def test_10_concurrent_assessments(self):
        token,_=self.account()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda i:self.upload(token,baby=f'CONCURRENT-{i}').json()['assessment_id'],range(8)))
        self.assertEqual(len(set(results)),8)
        self.assertEqual(self.call('GET','/dashboard',token=token).json()['total'],8)

    def test_11_login_throttle(self):
        for _ in range(10):self.call('POST','/auth/login',401,json={'nurse_id':'missing','password':'bad'})
        self.call('POST','/auth/login',429,json={'nurse_id':'missing','password':'bad'})

    def test_12_filtered_csv_all_rows_and_safe_cells(self):
        import csv
        token,body=self.account()
        record=self.upload(token,baby='=2+2',notes='Line one\n"quoted", value').json()['assessment_id']
        with source.db() as conn:
            conn.executemany('INSERT INTO assessments(nurse_id,baby_id,age_days,weight,gestational_age,feeding_type,image_path,status,consent_recorded) VALUES(?,?,?,?,?,?,?,?,?)',
                [(body['nurse_id'],f'EXPORT-{i:03}',2,3.2,38,'Mixed','synthetic.jpg','Reviewed',1) for i in range(105)])
        response=self.call('GET','/assessments/export',token=token)
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),106)
        special=next(r for r in rows if r['assessment_id']==str(record))
        self.assertEqual(special['baby_id'],"'=2+2")
        self.assertEqual(special['notes'],'Line one\n"quoted", value')
        filtered=self.call('GET','/assessments/export?status=Reviewed&q=EXPORT',token=token)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(filtered.content.decode('utf-8-sig'))))),105)
        second,_=self.account()
        self.assertEqual(len(list(csv.DictReader(io.StringIO(self.call('GET','/assessments/export',token=second).content.decode('utf-8-sig'))))),0)
        self.client.cookies.clear();self.call('GET','/assessments/export',401)

    def test_13_export_cursor_ignores_later_inserts(self):
        token,_=self.account()
        self.upload(token,baby='SNAP-1');self.upload(token,baby='SNAP-2')
        first=self.call('GET','/assessments?limit=1',token=token).json()
        self.upload(token,baby='SNAP-3')
        second=self.call('GET','/assessments',token=token,params={'limit':1,'offset':1,'max_id':first['snapshot_max_id']}).json()
        self.assertEqual(second['total'],2)
        self.assertEqual(second['items'][0]['baby_id'],'SNAP-1')

    def test_14_upload_without_consent_rejected(self):
        token,_=self.account()
        self.call('POST','/assessment',422,token=token,data=dict(baby_id='NO-CONSENT',age_days='2',weight='3.2',gestational_age='38',feeding_type='Mixed'),files={'image':('test.jpg',image_bytes(),'image/jpeg')})
        record=self.upload(token).json()['assessment_id']
        with source.db() as conn:consent=conn.execute('SELECT consent_recorded FROM assessments WHERE id=?',(record,)).fetchone()[0]
        self.assertEqual(consent,1)

    def test_15_malformed_and_nonfinite_json(self):
        token,_=self.account();record=self.upload(token).json()['assessment_id']
        for value in ['NaN','Infinity','-Infinity']:
            with self.subTest(value=value):
                self.call('PATCH',f'/assessments/{record}',422,token=token,headers={'Content-Type':'application/json'},content='{"status":"Reviewed","bilirubin":'+value+'}')
        self.call('POST','/auth/login',422,headers={'Content-Type':'application/json'},content='{broken json')
        item=self.call('GET','/assessments',token=token).json()['items'][0]
        self.assertIsNone(item['bilirubin']);self.assertEqual(item['status'],'Pending review')

    def test_16_bearer_scheme_and_interactive_api_schema(self):
        token,_=self.account()
        self.call('GET','/auth/me',headers={'Authorization':'bearer '+token})
        self.call('GET','/auth/me',headers={'Authorization':'bEaReR   '+token})
        self.call('GET','/auth/me',401,headers={'Authorization':'Basic '+token})
        schema=self.call('GET','/openapi.json').json()
        self.assertIn('HTTPBearer',schema['components']['securitySchemes'])
        self.assertTrue(schema['paths']['/assessments']['get']['security'])
        self.call('POST','/auth/logout',headers={'Authorization':'bearer '+token})
        self.call('GET','/auth/me',401,headers={'Authorization':'bearer '+token})

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Audit)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    print(f'HTTP requests executed: {REQUESTS}')
    sys.exit(not result.wasSuccessful())
