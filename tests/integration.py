"""Run against an isolated instance: python tests/integration.py --url http://127.0.0.1:8001"""
import argparse
import io
import json
import secrets
import urllib.error
import urllib.request
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:8001')
URL = parser.parse_args().url
checks = 0

def call(path, method='GET', body=None, token=None, content_type='application/json', expected=200):
    global checks
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    headers = {'Content-Type': content_type}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(URL+path, body, headers, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            status, data = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, data = error.code, error.read()
    assert status == expected, (path, expected, status, data)
    checks += 1
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return data

def account():
    name = 'test_'+secrets.token_hex(4)
    body = dict(nurse_id=name, full_name='Test Nurse', email=name+'@example.test', facility='Test Facility', password='test-password-123')
    call('/auth/register', 'POST', body, expected=201)
    call('/auth/register', 'POST', body, expected=409)
    call('/auth/login', 'POST', dict(nurse_id=name,password='incorrect'), expected=401)
    return call('/auth/login', 'POST', dict(nurse_id=name,password=body['password']))['access_token']

def multipart(image, age='2', filename='../../escaped.jpg'):
    boundary = 'test-'+secrets.token_hex(8)
    data = bytearray()
    fields = dict(consent='true',baby_id='TEST-BABY',age_days=age,weight='3.2',gestational_age='38',feeding_type='Breastfeeding',notes='Observation')
    for key,value in fields.items():
        data.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    data.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: image/jpeg\r\n\r\n'.encode())
    data.extend(image)
    data.extend(f'\r\n--{boundary}--\r\n'.encode())
    return bytes(data), 'multipart/form-data; boundary='+boundary

call('/health')
call('/')
call('/assets/app.js')
call('/assessments', expected=401)
first, second = account(), account()
call('/auth/me', token=first)
buffer = io.BytesIO()
Image.new('RGB',(320,240),'#dfc7aa').save(buffer,format='JPEG')
data, content_type = multipart(buffer.getvalue())
result = call('/assessment', 'POST', data, first, content_type, 201)
assert result['confidence'] is None and result['model_status'] == 'not_available'
record_id = result['assessment_id']
call(f'/assessments/{record_id}/image', token=first)
call(f'/assessments/{record_id}/image', token=second, expected=404)
call(f'/assessments/{record_id}', 'PATCH', dict(status='Reviewed',notes='Reviewed clinically',bilirubin=8.2), second, expected=404)
call(f'/assessments/{record_id}', 'PATCH', dict(status='Reviewed',notes='Reviewed clinically',bilirubin=8.2), first)
history = call('/assessments?q=TEST-BABY&status=Reviewed&limit=1', token=first)
assert history['total'] == 1 and history['items'][0]['bilirubin'] == 8.2
assert call('/assessments', token=second)['total'] == 0
summary = call('/dashboard', token=first)
assert summary['total'] == 1 and summary['reviewed'] == 1 and summary['pending'] == 0
data, content_type = multipart(b'not-an-image')
call('/assessment','POST',data,first,content_type,422)
data, content_type = multipart(buffer.getvalue(), age='-1')
call('/assessment','POST',data,first,content_type,422)
data, content_type = multipart(b'x'*(8*1024*1024+1))
call('/assessment','POST',data,first,content_type,413)
large = io.BytesIO()
Image.new('RGB',(5000,4001),'white').save(large,format='PNG')
data, content_type = multipart(large.getvalue())
call('/assessment','POST',data,first,content_type,422)
data, content_type = multipart(buffer.getvalue())
call('/assessment','POST',data,first,content_type,201)
page_one = call('/assessments?limit=1&offset=0',token=first)
page_two = call('/assessments?limit=1&offset=1',token=first)
assert page_one['total'] == 2 and page_one['items'][0]['assessment_id'] != page_two['items'][0]['assessment_id']
call('/auth/logout','POST',token=first)
call('/auth/me',token=first,expected=401)
print(f'PASS: {checks} HTTP checks; ownership, review, pagination, upload limits, validation, logout, and no fabricated prediction.')
