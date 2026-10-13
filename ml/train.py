"""Train a local folder-label classifier with similarity-group holdouts."""
import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, classification_report, confusion_matrix, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.preprocessing import StandardScaler

if __package__:
    from .vision import feature_network, normalized_image, preprocessing
else:
    from vision import feature_network, normalized_image, preprocessing

def validate_manifest_files(root, rows):
    for row in rows:
        path=(root/row['relative_path']).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError('Manifest image path is outside the dataset')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=row['file_sha256']:
            raise ValueError('Dataset files changed after the audit. Rerun ml/audit.py before training.')

def group_scores(indices,labels,scores,groups):
    unique=sorted(set(zip(groups[indices],labels[indices])))
    truth=np.array([label for _,label in unique])
    values=np.array([scores[(groups[indices]==g)&(labels[indices]==label)].mean() for g,label in unique])
    return truth,values

def metrics(truth,values):
    predicted=(values>=.5).astype(int)
    return {'count':len(truth),'class_counts':dict(Counter(str(int(x)) for x in truth)),
            'balanced_accuracy':float(balanced_accuracy_score(truth,predicted)),
            'roc_auc':float(roc_auc_score(truth,values)) if len(set(truth))==2 else None,
            'confusion_matrix_normal_jaundice':confusion_matrix(truth,predicted,labels=[0,1]).tolist(),
            'classification_report':classification_report(truth,predicted,labels=[0,1],target_names=['normal','jaundice'],output_dict=True,zero_division=0)}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--audit',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--patient-manifest',type=Path,help='CSV with relative_path,patient_id; every image must have a confirmed patient ID.')
    args=parser.parse_args()
    import torch
    torch.set_num_threads(4)
    torch.manual_seed(42)
    root=args.dataset.resolve();args.output.mkdir(parents=True,exist_ok=True);args.cache.mkdir(parents=True,exist_ok=True)
    rows=list(csv.DictReader((args.audit/'manifest.csv').open(encoding='utf-8')))
    rows=[r for r in rows if r['exclude']=='False']
    if not rows:raise ValueError('The manifest has no included images')
    validate_manifest_files(root,rows)
    labels=np.array([int(r['label']) for r in rows]);groups=np.array([r['group_id'] for r in rows])
    if args.patient_manifest:
        patient_rows=list(csv.DictReader(args.patient_manifest.open(encoding='utf-8-sig')))
        patient_map={r['relative_path']:r.get('patient_id','').strip() for r in patient_rows}
        if len(patient_map)!=len(patient_rows):raise ValueError('Patient manifest contains duplicate image paths')
        if any(not patient_map.get(r['relative_path']) for r in rows):raise ValueError('Every included image needs a confirmed patient ID')
        for group in set(groups):
            members=[patient_map[rows[i]['relative_path']] for i in np.flatnonzero(groups==group)]
            if len(set(members))!=1:raise ValueError('Detected duplicate photos are assigned to different patient IDs')
        groups=np.array([patient_map[r['relative_path']] for r in rows])
    group_counts={label:len(set(groups[labels==label])) for label in (0,1)}
    if min(group_counts.values())<5:raise ValueError(f'Not enough independent similarity groups for a 5-fold holdout: {group_counts}')
    outer=StratifiedGroupKFold(5,shuffle=True,random_state=42)
    remaining,test=next(outer.split(np.zeros(len(rows)),labels,groups))
    inner=StratifiedGroupKFold(4,shuffle=True,random_state=43)
    train_rel,val_rel=next(inner.split(np.zeros(len(remaining)),labels[remaining],groups[remaining]))
    train,val=remaining[train_rel],remaining[val_rel]
    for indices in (train,val,test):
        if len(set(labels[indices]))<2:raise ValueError('Each holdout needs both classes. Supply more independent photos.')
    assert not(set(groups[train])&set(groups[val]) or set(groups[train])&set(groups[test]) or set(groups[val])&set(groups[test]))
    dataset_fingerprint=hashlib.sha256('|'.join(r['file_sha256']+r['class_name'] for r in rows).encode()).hexdigest()
    import torchvision
    feature_contract='mobilenetv3-small-imagenet1k-v1/app-jpeg82/resize256-crop224/'+torchvision.__version__
    cache_key=hashlib.sha256((dataset_fingerprint+feature_contract).encode()).hexdigest()
    cache_file=args.cache/(cache_key+'.npz')
    os.environ.setdefault('TORCH_HOME',str(args.cache/'torch'))
    network=feature_network(pretrained=True)
    transform=preprocessing()
    if cache_file.exists():
        features=np.load(cache_file,allow_pickle=False)['features']
    else:
        chunks=[]
        for start in range(0,len(rows),24):
            batch=torch.stack([transform(normalized_image(root/r['relative_path'])) for r in rows[start:start+24]])
            with torch.inference_mode():chunks.append(network(batch).numpy())
            print(f'Extracted features: {min(start+24,len(rows))}/{len(rows)}',flush=True)
        features=np.concatenate(chunks)
        np.savez_compressed(cache_file,features=features)
    scaler=StandardScaler().fit(features[train]);x=scaler.transform(features)
    sizes=Counter(zip(groups[train],labels[train]));class_groups={label:len(set(groups[train][labels[train]==label])) for label in (0,1)}
    weights=np.array([1/(sizes[(groups[i],labels[i])]*class_groups[labels[i]]) for i in train]);weights*=len(train)/weights.sum()
    best=None;candidates=[]
    for c in (.01,.1,1.,10.):
        candidate=LogisticRegression(C=c,max_iter=2000,random_state=42).fit(x[train],labels[train],sample_weight=weights)
        values=candidate.predict_proba(x[val])[:,1];truth,group_values=group_scores(val,labels,values,groups)
        score=balanced_accuracy_score(truth,group_values>=.5)
        candidates.append({'C':c,'validation_group_balanced_accuracy':float(score)})
        if best is None or score>best[0]:best=(score,c,candidate)
    model=best[2]
    results={'class_mapping':{'0':'normal','1':'jaundice'},'selected_C':best[1],'validation_candidates':candidates,
             'split_method':'StratifiedGroupKFold; seed 42 outer test, seed 43 inner validation; no similarity group shared.',
             'label_source':'User dataset folder names; clinical provenance unverified.','threshold':.5,
             'partitions':{},'limitations':['No patient IDs: similarity grouping cannot guarantee patient separation.',
              'No TSB/TcB measurements: cannot estimate bilirubin or grade severity.',
              'Class score is not calibrated clinical confidence.','No external or prospective clinical validation.',
              'Hospital backgrounds, devices, lighting and skin tone may confound results.']}
    if args.patient_manifest:
        results['split_method']='StratifiedGroupKFold using supplied patient IDs; seed 42 outer test, seed 43 inner validation.'
        results['limitations'][0]='Patient IDs were supplied; their correctness was not independently verified.'
    assignments=[]
    for name,indices in [('train',train),('validation',val),('test',test)]:
        values=model.predict_proba(x[indices])[:,1];truth,group_values=group_scores(indices,labels,values,groups)
        results['partitions'][name]={'image_metrics':metrics(labels[indices],values),'group_metrics':metrics(truth,group_values)}
        for index,score in zip(indices,values):assignments.append({'relative_path':rows[index]['relative_path'],'class_name':rows[index]['class_name'],'group_id':groups[index],'partition':name,'jaundice_class_score':float(score)})
    # Evaluation-only comparator, reflecting the training group majority.
    majority=int(class_groups[1]>class_groups[0]);test_truth,test_values=group_scores(test,labels,model.predict_proba(x[test])[:,1],groups)
    results['majority_baseline_group_balanced_accuracy']=float(balanced_accuracy_score(test_truth,np.full_like(test_truth,majority)))
    torch.save(network.state_dict(),args.output/'features.pt')
    head={'mean':scaler.mean_.tolist(),'scale':scaler.scale_.tolist(),'coef':model.coef_[0].tolist(),'intercept':float(model.intercept_[0])}
    weight_digest=hashlib.sha256((args.output/'features.pt').read_bytes()).hexdigest()
    model_fingerprint=hashlib.sha256(json.dumps({'head':head,'dataset':dataset_fingerprint,'weights':weight_digest,'preprocessing':feature_contract},sort_keys=True).encode()).hexdigest()
    metadata={'schema_version':1,'model_id':'neo-mobilenetv3-research-'+model_fingerprint[:10],
              'research_only':True,'architecture':'ImageNet MobileNetV3 Small frozen 576-dimensional features + trained logistic head',
              'preprocessing':'App JPEG normalization; IMAGENET1K_V1 resize 256 / center crop 224 / ImageNet normalization',
              'dataset_fingerprint':dataset_fingerprint,'weights_sha256':weight_digest,
              'head':head,
              'classes':['normal','jaundice'],'threshold':.5,'evaluation':results,
              'runtime_versions':{'torch':torch.__version__,'numpy':np.__version__}}
    (args.output/'model.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    (args.output/'evaluation.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    with (args.audit/'split_assignments.csv').open('w',newline='',encoding='utf-8') as file:
        writer=csv.DictWriter(file,fieldnames=list(assignments[0]));writer.writeheader();writer.writerows(assignments)
    print(json.dumps(results,indent=2),flush=True)

if __name__=='__main__':main()
