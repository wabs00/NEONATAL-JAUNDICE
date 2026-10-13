"""Shared MobileNetV3 feature extraction. Class scores are not clinical confidence."""
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageOps

def normalized_image(source):
    with Image.open(source) as original:
        image=ImageOps.exif_transpose(original).convert('RGB')
        image.thumbnail((1600,1600))
        buffer=io.BytesIO()
        image.save(buffer,format='JPEG',quality=82,optimize=True)
    buffer.seek(0)
    with Image.open(buffer) as saved:
        return saved.convert('RGB').copy()

def feature_network(pretrained=False):
    import torch
    from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
    model=mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1 if pretrained else None)
    return torch.nn.Sequential(model.features,torch.nn.AdaptiveAvgPool2d(1),torch.nn.Flatten()).eval()

def preprocessing():
    from torchvision.models import MobileNet_V3_Small_Weights
    return MobileNet_V3_Small_Weights.IMAGENET1K_V1.transforms()

class ResearchModel:
    def __init__(self,directory):
        import numpy as np
        import torch
        self.np=np;self.torch=torch
        directory=Path(directory)
        self.metadata=json.loads((directory/'model.json').read_text(encoding='utf-8'))
        if self.metadata.get('schema_version')!=1 or self.metadata.get('research_only') is not True:
            raise ValueError('Only versioned research artifacts are supported')
        if self.metadata.get('classes')!=['normal','jaundice'] or self.metadata.get('threshold')!=.5:
            raise ValueError('Unsupported class mapping or threshold')
        weight_path=directory/'features.pt'
        if hashlib.sha256(weight_path.read_bytes()).hexdigest()!=self.metadata['weights_sha256']:
            raise ValueError('Model weight checksum mismatch')
        torch.set_num_threads(2)
        self.network=feature_network()
        self.network.load_state_dict(torch.load(weight_path,map_location='cpu',weights_only=True))
        self.transform=preprocessing()
        head=self.metadata['head']
        self.mean=np.asarray(head['mean']);self.scale=np.asarray(head['scale'])
        self.coef=np.asarray(head['coef']);self.intercept=float(head['intercept'])
        if any(x.shape!=(576,) for x in [self.mean,self.scale,self.coef]) or np.any(self.scale<=0):
            raise ValueError('Invalid classifier dimensions')
        if not all(np.all(np.isfinite(x)) for x in [self.mean,self.scale,self.coef]) or not np.isfinite(self.intercept):
            raise ValueError('Classifier parameters must be finite')

    def predict(self,image_path,already_normalized=True):
        np=self.np;torch=self.torch
        if already_normalized:
            with Image.open(image_path) as original:
                image=ImageOps.exif_transpose(original).convert('RGB').copy()
        else:image=normalized_image(image_path)
        with torch.inference_mode():
            features=self.network(self.transform(image).unsqueeze(0)).numpy()[0]
        logit=float(np.dot((features-self.mean)/self.scale,self.coef)+self.intercept)
        score=float(1/(1+np.exp(-np.clip(logit,-60,60))))
        return {'model_id':self.metadata['model_id'],'research_only':True,
                'predicted_dataset_class':'jaundice' if score>=.5 else 'normal',
                'jaundice_class_score':round(score,4),'clinical_confidence':None,
                'notice':'Experimental folder-label classification. This is not a diagnosis, bilirubin estimate, or clinical risk assessment.'}
