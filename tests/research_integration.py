"""API and exported-artifact checks using only synthetic uploaded images."""
import argparse
import io
import json
import secrets
import urllib.error
import urllib.request
from PIL import Image

parser=argparse.ArgumentParser()
parser.add_argument('--url',default='http://127.0.0.1:8005')
URL=parser.parse_args().url
checks=0
def call(path,method='GET',body=None,token=None,kind='application/json',expected=200):
    global checks
    if isinstance(body,dict):body=json.dumps(body).encode()
    headers={'Content-Type':kind}
    if token:headers['Authorization']='Bearer '+token
    try:
        with urllib.request.urlopen(urllib.request.Request(URL+path,body,headers,method=method),timeout=60) as response:
            status,data=response.status,response.read()
    except urllib.error.HTTPError as error:status,data=error.code,error.read()
    assert status==expected,(path,status,data)
    checks+=1
    return json.loads(data)
def account():
    name='mltest_'+secrets.token_hex(4)
    call('/auth/register','POST',dict(nurse_id=name,full_name='Model Test',email=name+'@example.test',facility='Synthetic Test',password='test-password-123'),expected=201)
    return call('/auth/login','POST',dict(nurse_id=name,password='test-password-123'))['access_token']
first,second=account(),account()
status=call('/research/model',token=first)
assert status['available'] and status['research_only'] and not status['diagnostic_model_available'],status
call('/research/model',expected=401)
buffer=io.BytesIO();Image.new('RGB',(320,240),'#ddc2a8').save(buffer,format='JPEG')
boundary='test-'+secrets.token_hex(8);data=bytearray()
for key,value in dict(consent='true',baby_id='SYNTHETIC-MODEL-TEST',age_days='2',weight='3.2',gestational_age='38',feeding_type='Mixed').items():
    data.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
data.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="synthetic.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode());data.extend(buffer.getvalue());data.extend(f'\r\n--{boundary}--\r\n'.encode())
record=call('/assessment','POST',bytes(data),first,'multipart/form-data; boundary='+boundary,201)
assert record['confidence'] is None
endpoint=f"/research/assessments/{record['assessment_id']}/predict"
call(endpoint,'POST',token=second,expected=404)
call(endpoint,'POST',expected=401)
result=call(endpoint,'POST',token=first)
assert result['research_only'] is True and result['clinical_confidence'] is None
assert result['predicted_dataset_class'] in ('normal','jaundice') and 0<=result['jaundice_class_score']<=1
assert call(endpoint,'POST',token=first)==result
history=call('/assessments?q=SYNTHETIC-MODEL-TEST',token=first)
assert history['items'][0]['status']=='Pending review' and history['items'][0]['bilirubin'] is None
call('/auth/logout','POST',token=first)
call(endpoint,'POST',token=first,expected=401)
print(f'PASS: {checks} research API checks. Research result kept separate; ownership, caching and logout verified.')
