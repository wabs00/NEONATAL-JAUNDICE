'use strict';
const researchPanel=document.createElement('section');researchPanel.className='research-panel';
researchPanel.innerHTML='<span class="eyebrow">EXPERIMENTAL MODEL · RESEARCH ONLY</span><h3>Dataset class prediction</h3><p>This model learns the supplied “normal” and “jaundice” folder labels. Labels are not clinically verified. Results are not a diagnosis or a bilirubin measurement.</p><button type="button" class="secondary" id="run-research" disabled>Checking model…</button><p id="research-result" role="status"></p>';
document.getElementById('save-review').before(researchPanel);
const researchButton=document.getElementById('run-research');
let researchRecordId=null;
const originalOpenReview=openReview;
openReview=async record=>{
  researchRecordId=record.assessment_id;document.getElementById('research-result').textContent='';
  researchButton.disabled=true;researchButton.textContent='Checking model…';
  await originalOpenReview(record);
  try{const model=await api('/research/model');if(researchRecordId!==record.assessment_id)return;
    researchButton.disabled=!model.available;researchButton.textContent=model.available?'Run research model':'Research model unavailable';
  }catch{researchButton.disabled=true;researchButton.textContent='Research model unavailable'}
};
researchButton.onclick=async()=>{const recordId=researchRecordId;researchButton.disabled=true;researchButton.textContent='Analyzing…';
  try{const result=await api(`/research/assessments/${recordId}/predict`,{method:'POST'});
    if(researchRecordId===recordId)document.getElementById('research-result').textContent=`Dataset class: ${result.predicted_dataset_class}. Jaundice-class score: ${result.jaundice_class_score.toFixed(3)} (0–1). This score is not calibrated clinical confidence. Clinical review remains required.`;
  }catch(error){if(researchRecordId===recordId)document.getElementById('research-result').textContent=error.message}
  finally{if(researchRecordId===recordId){researchButton.disabled=false;researchButton.textContent='Run research model'}}
};

window.addEventListener('neo-session-cleared',()=>{researchRecordId=null;document.getElementById('research-result').textContent='';researchButton.disabled=true;researchButton.textContent='Research model unavailable'});
