"""Verify model serialization and app/training preprocessing agreement."""
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.app import prepare_image
from ml.vision import ResearchModel, normalized_image

class ArtifactTests(unittest.TestCase):
    def test_serialization_and_score_contract(self):
        model=ResearchModel(ROOT/'models/research')
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'synthetic.jpg'
            Image.new('RGB',(320,240),'#ddc2a8').save(path)
            result=model.predict(path)
            self.assertTrue(result['research_only'])
            self.assertIsNone(result['clinical_confidence'])
            self.assertGreaterEqual(result['jaundice_class_score'],0)
            self.assertLessEqual(result['jaundice_class_score'],1)

    def test_corrupted_weights_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp)
            shutil.copy(ROOT/'models/research/model.json',temp/'model.json')
            (temp/'features.pt').write_bytes(b'corrupted-checkpoint')
            with self.assertRaisesRegex(ValueError,'checksum'):
                ResearchModel(temp)

    def test_preprocessing_matches_app(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'orientation.jpg'
            image=Image.new('RGB',(1800,900),'#ac9270')
            exif=Image.Exif();exif[274]=6
            image.save(path,format='JPEG',exif=exif)
            data,_,_=prepare_image(path.read_bytes())
            expected=Image.open(io.BytesIO(data)).convert('RGB')
            actual=normalized_image(path)
            self.assertEqual(expected.size,actual.size)
            self.assertEqual(expected.tobytes(),actual.tobytes())

    def test_nonfinite_classifier_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp)
            shutil.copy(ROOT/'models/research/features.pt',temp/'features.pt')
            metadata=json.loads((ROOT/'models/research/model.json').read_text())
            metadata['head']['intercept']=float('nan')
            (temp/'model.json').write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError,'finite'):ResearchModel(temp)

    def test_wrong_class_mapping_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            temp=Path(temp)
            metadata=json.loads((ROOT/'models/research/model.json').read_text())
            metadata['classes']=['jaundice','normal']
            (temp/'model.json').write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError,'class mapping'):ResearchModel(temp)

if __name__=='__main__':unittest.main()
