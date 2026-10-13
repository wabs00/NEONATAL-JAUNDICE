'use strict';
const $=id=>document.getElementById(id);
let registering=false, user=null, page='dashboard', offset=0, records=[], total=0, selected=null, previewURL=null, imageURL=null, searchTimer, toastTimer, historyRequest=0;
const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const formatDate=value=>new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'});
function notify(message){$('toast').textContent=message;$('toast').style.display='block';clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').style.display='none',4500)}
function clearWorkspace(){
  $('assessment-form').reset();$('review-form').reset();$('auth-form').reset();
  if(previewURL)URL.revokeObjectURL(previewURL);previewURL=null;
  $('photo-preview').removeAttribute('src');$('photo-preview').hidden=true;$('photo-name').textContent='';
  $('review-image').removeAttribute('src');selected=null;records=[];offset=0;total=0;historyRequest++;
  $('search').value='';$('status-filter').value='';$('recent').textContent='';$('records').textContent='';$('nurse-name').textContent='';$('facility').textContent='';$('initials').textContent='N';
  for(const key of ['total','pending','reviewed','referred'])$(key).textContent='0';
  window.dispatchEvent(new Event('neo-session-cleared'));
}
async function api(path,options={}){
  const requestUser=user;
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),20000);
  try{
    const response=await fetch(path,{credentials:'same-origin',...options,signal:controller.signal});
    const type=response.headers.get('content-type')||'';const data=type.includes('application/json')?await response.json():response.ok&&type.includes('text/csv')?await response.blob():{detail:'The server returned an unexpected response. Please retry.'};
    if(!response.ok){if(response.status===401&&user&&user===requestUser){user=null;clearWorkspace();$('workspace').hidden=true;$('auth').hidden=false;$('review-dialog').close()}
      const detail=Array.isArray(data.detail)?data.detail.map(x=>x.loc.slice(1).join('.')+': '+x.msg).join('; '):data.detail;
      throw new Error(detail||'The request could not be completed');}
    return data;
  }catch(error){if(error.name==='AbortError')throw new Error('The server took too long. Check your connection and retry.');throw error}
  finally{clearTimeout(timeout)}
}
const json=(method,body)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
function busy(button,state,label){button.disabled=state;button.textContent=label}
$('auth-switch').onclick=()=>{registering=!registering;$('registration').hidden=!registering;for(const input of $('registration').querySelectorAll('input'))input.required=registering;
  $('auth-title').textContent=registering?'A new chapter in care.':'Welcome back.';$('auth-sub').textContent=registering?'Create your personal workspace.':'Sign in to your personal care workspace.';
  $('auth-submit').textContent=registering?'Create account →':'Sign in →';$('auth-switch').textContent=registering?'Already registered? Sign in':'New here? Create an account';
  $('auth-form').elements.password.minLength=registering?10:1;$('auth-form').elements.password.autocomplete=registering?'new-password':'current-password';$('auth-error').textContent=''};
$('auth-form').onsubmit=async event=>{event.preventDefault();$('auth-error').textContent='';busy($('auth-submit'),true,'Please wait…');
  const values=Object.fromEntries(new FormData(event.target));try{if(registering){await api('/auth/register',json('POST',values));$('auth-switch').click();notify('Account created. Sign in to continue.')}else{await api('/auth/login',json('POST',{nurse_id:values.nurse_id,password:values.password}));event.target.elements.password.value='';await enter()}}
  catch(error){$('auth-error').textContent=error.message}finally{busy($('auth-submit'),false,registering?'Create account →':'Sign in →')}};
async function enter(){user=await api('/auth/me');for(const id of ['auth-error','assessment-error','review-error'])$(id).textContent='';$('auth').hidden=true;$('workspace').hidden=false;$('nurse-name').textContent=user.full_name;$('facility').textContent=user.facility;
  $('initials').textContent=user.full_name.split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();$('date').textContent=new Date().toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'});await navigate('dashboard')}
$('logout').onclick=async()=>{try{await api('/auth/logout',{method:'POST'});location.reload()}catch(error){notify(error.message)}};
const mobileLogout=document.createElement('button');mobileLogout.className='text-button mobile-logout';mobileLogout.textContent='Sign out';mobileLogout.onclick=$('logout').onclick;document.querySelector('.header-right').append(mobileLogout);
document.querySelectorAll('[data-page]').forEach(button=>button.onclick=()=>navigate(button.dataset.page));
async function navigate(next){page=next;document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==next);document.querySelectorAll('nav button').forEach(el=>el.classList.toggle('active',el.dataset.page===next));
  $('crumb').textContent={dashboard:'Overview',assessment:'New assessment',history:'Assessment records',guide:'Workflow guide'}[next];try{if(next==='dashboard')await loadDashboard();if(next==='history')await loadHistory()}catch(error){notify(error.message)}}
function badge(status){return `<span class="badge ${status==='Reviewed'?'reviewed':status==='Referred'?'referred':''}">${escapeHTML(status)}</span>`}
function table(items,compact=false){if(!items.length)return `<div class="empty"><span class="empty-icon">⊕</span><strong>${compact?'Your first record starts here.':'No assessments found.'}</strong><p>${compact?'Create an assessment to see your care activity.':'Try a different search or create a new assessment.'}</p><button class="text-button" data-empty-create>＋ New assessment</button></div>`;
 return `<div class="table-scroll"><table><thead><tr><th>BABY ID</th><th>DATE</th>${compact?'':'<th>AGE / WEIGHT</th>'}<th>STATUS</th><th></th></tr></thead><tbody>${items.map(item=>`<tr><td><strong>${escapeHTML(item.baby_id)}</strong></td><td>${escapeHTML(formatDate(item.created_at))}</td>${compact?'':`<td>${item.age_days} days · ${item.weight} kg</td>`}<td>${badge(item.status)}</td><td><button class="row-open" data-record="${item.assessment_id}">Open ↗</button></td></tr>`).join('')}</tbody></table></div>`}
function bindTable(container,items){container.querySelectorAll('[data-record]').forEach(button=>button.onclick=()=>openReview(items.find(x=>x.assessment_id===Number(button.dataset.record))));container.querySelectorAll('[data-empty-create]').forEach(button=>button.onclick=()=>navigate('assessment'))}
async function loadDashboard(){const requestUser=user;const [summary,latest]=await Promise.all([api('/dashboard'),api('/assessments?limit=5')]);if(user!==requestUser)return;for(const key of ['total','pending','reviewed','referred'])$(key).textContent=summary[key];$('recent').innerHTML=table(latest.items,true);bindTable($('recent'),latest.items)}
function query(start=offset,limit=20){return new URLSearchParams({q:$('search').value.trim(),status:$('status-filter').value,offset:String(start),limit:String(limit)})}
async function loadHistory(){const request=++historyRequest;$('records').innerHTML='<div class="empty">Loading assessment records…</div>';try{const data=await api('/assessments?'+query());if(request!==historyRequest)return;records=data.items;total=data.total;$('records').innerHTML=table(records);bindTable($('records'),records);$('record-count').textContent=total?`${offset+1}–${Math.min(offset+20,total)} of ${total} records`:'0 records';$('previous').disabled=offset===0;$('next').disabled=offset+20>=total}catch(error){if(request===historyRequest){$('records').innerHTML='<div class="empty">Could not load records. Use Refresh to retry.</div>';notify(error.message)}}}
$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{offset=0;loadHistory()},300)};$('status-filter').onchange=()=>{offset=0;loadHistory()};$('refresh').onclick=()=>loadHistory();$('previous').onclick=()=>{offset=Math.max(0,offset-20);loadHistory()};$('next').onclick=()=>{offset+=20;loadHistory()};
$('photo').onchange=()=>{const file=$('photo').files[0];if(previewURL)URL.revokeObjectURL(previewURL);$('photo-preview').hidden=true;$('photo-name').textContent='';if(!file)return;
  if(file.size>8*1024*1024||!['image/jpeg','image/png','image/webp'].includes(file.type)){$('photo').value='';notify('Choose a JPEG, PNG or WebP smaller than 8 MB.');return}
  previewURL=URL.createObjectURL(file);$('photo-preview').src=previewURL;$('photo-preview').hidden=false;$('photo-name').textContent=`${file.name} · ${(file.size/1024).toFixed(0)} KB`};
$('assessment-form').onsubmit=async event=>{event.preventDefault();$('assessment-error').textContent='';busy($('save-assessment'),true,'Saving…');try{await api('/assessment',{method:'POST',body:new FormData(event.target)});event.target.reset();if(previewURL)URL.revokeObjectURL(previewURL);previewURL=null;$('photo-preview').hidden=true;$('photo-name').textContent='';notify('Assessment saved. Awaiting clinical review.');offset=0;await navigate('history')}catch(error){$('assessment-error').textContent=error.message}finally{busy($('save-assessment'),false,'Save assessment →')}};
async function openReview(record){selected=record;const form=$('review-form');$('review-title').textContent=record.baby_id;$('review-details').textContent=`${formatDate(record.created_at)} · ${record.age_days} days · ${record.weight} kg · ${record.gestational_age} weeks · ${record.feeding_type}`;form.elements.status.value=record.status;form.elements.notes.value=record.notes;form.elements.bilirubin.value=record.bilirubin??'';$('review-error').textContent='';$('review-image').src=`/assessments/${record.assessment_id}/image`;$('review-dialog').showModal()}
$('close-review').onclick=()=>$('review-dialog').close();$('review-dialog').addEventListener('click',event=>{if(event.target===$('review-dialog')){const r=event.target.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)event.target.close()}});
$('review-form').onsubmit=async event=>{event.preventDefault();busy($('save-review'),true,'Saving…');const body=Object.fromEntries(new FormData(event.target));body.bilirubin=body.bilirubin===''?null:Number(body.bilirubin);try{await api('/assessments/'+selected.assessment_id,json('PATCH',body));$('review-dialog').close();notify('Review updated.');await navigate(page)}catch(error){$('review-error').textContent=error.message}finally{busy($('save-review'),false,'Save review')}};
$('export').onclick=async()=>{busy($('export'),true,'Preparing export…');try{
  const filter=new URLSearchParams({q:$('search').value.trim(),status:$('status-filter').value});
  const file=await api('/assessments/export?'+filter);const url=URL.createObjectURL(file);
  const link=document.createElement('a');link.href=url;link.download='neojaundice-records.csv';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);notify('Filtered records exported.');
}catch(error){notify(error.message)}finally{busy($('export'),false,'↓ Export filtered CSV')}};

api('/auth/me').then(()=>enter()).catch(error=>{if(!error.message.includes('sign in'))$('auth-error').textContent='Could not connect to the server. Please retry.'});
