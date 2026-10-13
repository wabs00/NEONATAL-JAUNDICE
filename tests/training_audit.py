import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ml.train import group_scores, validate_manifest_files

class TrainingTests(unittest.TestCase):
    def test_empty_dataset_has_clear_cli_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'normal').mkdir();(root/'jaundice').mkdir()
            result=subprocess.run([sys.executable,str(ROOT/'ml/audit.py'),'--dataset',str(root),'--output',str(root/'audit')],capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertIn('No readable images',result.stderr)
            self.assertNotIn('Traceback',result.stderr)
    def test_changed_images_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'photo.jpg';path.write_bytes(b'original')
            row={'relative_path':'photo.jpg','file_sha256':hashlib.sha256(b'original').hexdigest()}
            validate_manifest_files(root,[row])
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed after the audit'):validate_manifest_files(root,[row])
    def test_manifest_cannot_escape_dataset(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'outside the dataset'):
                validate_manifest_files(Path(temp),[{'relative_path':'../outside.jpg','file_sha256':'0'}])
    def test_changing_patient_labels_are_not_collapsed(self):
        labels=np.array([0,1,1]);groups=np.array(['baby-A','baby-A','baby-B'])
        truth,values=group_scores(np.array([0,1,2]),labels,np.array([.1,.8,.9]),groups)
        self.assertEqual(truth.tolist(),[0,1,1]);self.assertTrue(np.allclose(values,[.1,.8,.9]))

if __name__=='__main__':unittest.main()
