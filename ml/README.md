# Trained research model

This project now includes a **trained two-class research classifier** in `models/research/`. It uses frozen ImageNet MobileNetV3 Small features and a logistic classifier trained on the supplied `normal` and `jaundice` folders. No image was sent to an external service; only software and pretrained weights were downloaded.

The folder labels are not confirmed clinical diagnoses. The dataset does not include patient IDs, measured bilirubin, age-specific treatment thresholds or clinical label provenance. This artifact must not be presented as a validated jaundice detector. It cannot estimate bilirubin or grade mild/moderate/severe disease.

## Try it in the app

From the project root:

```powershell
.\start-research.ps1
```

Open **http://127.0.0.1:8005**, create an account or sign in, save an assessment, then open its record. The review dialog includes **Run research model**. The result is a predicted dataset class and a raw 0–1 jaundice-class score. It is explicitly marked research-only and is stored separately from clinical notes, status and measured bilirubin.

The first run installs the CPU model dependencies in `.venv-research`. Normal `start.ps1` leaves research inference disabled by default. For manual startup, install matching PyTorch CPU wheels and the requirements, then set `NEO_ENABLE_RESEARCH_MODEL=1` before starting Uvicorn. `NEO_RESEARCH_MODEL_DIR` can override the model folder.

The same research endpoint is available from a selected record in the Expo mobile app. Native camera and model-button behavior still need physical-device testing.

## Actual results

Training: 456 images. Validation: 152 images. Test: 152 images. The regularization parameter was selected using validation data only; the test set was not used for tuning. The prediction threshold is 0.5.

| Held-out image metric | Result |
| --- | --- |
| Accuracy | 85.5% (130 / 152) |
| Balanced accuracy | 84.6% |
| Jaundice-folder recall | 82.5% (33 / 40) |
| Jaundice-folder precision | 68.8% (33 / 48) |
| ROC AUC | 0.924 |
| Missed jaundice-folder images | 7 / 40 |
| Normal-folder images predicted jaundice | 15 / 112 |

Grouped evaluation counts the detected duplicate clusters once: 151 test groups, 86.1% accuracy, 84.9% balanced accuracy and 0.932 ROC AUC. These groups are **not confirmed independent patients**. Distinct photos of the same infant may cross partitions, so both forms of evaluation can overstate unseen-patient performance.

## Dataset audit

- 760 JPEG images, all 1000 × 1000 pixels.
- 560 normal-folder images and 200 jaundice-folder images.
- No unreadable images.
- Five extra exact duplicate copies; detected copies kept in the same partition.
- 755 conservative perceptual-similarity groups; no detected cross-label conflicts.
- Repeated infants were visible during sample inspection. Perceptual hashing does not reliably link all photos of an infant.

Audit and split evidence are in `ml/evidence/`; full metrics are in `models/research/evaluation.json`. The companion notebook `ml/audit_and_training.ipynb` checks the recorded audit, split separation and metrics. No training photos are packaged in this project.

## Reproduce training

The original dataset remains unchanged. Use your own permitted copy of the two-class directory:

```powershell
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r ml\requirements.txt
python ml\audit.py --dataset "PATH_TO_DATASET" --output "work\audit"
python ml\train.py --dataset "PATH_TO_DATASET" --audit "work\audit" --output "models\research" --cache "work\model-cache"
```

For the recorded run, Python was 3.11.9, PyTorch 2.14.1+cpu, TorchVision 0.29.1+cpu, scikit-learn 1.8.0, NumPy 2.4.4 and Pillow 12.3.0. Use the recorded versions for closer reproducibility. The pipeline does not fabricate examples or labels.

To improve the split, fill in `ml/evidence/patient_manifest_template.csv` using verified pseudonymous patient IDs. Every included image needs an ID. Then add `--patient-manifest "PATH_TO_COMPLETED_MANIFEST"` to training. Detected duplicate copies with contradictory patient IDs are rejected. Do not guess IDs from image appearance; use the original collection records.

The trained feature weights are stored as a state dictionary, loaded with `weights_only=True` and verified against a checksum. The classifier/scaler are plain JSON, not a pickled executable estimator. Image preprocessing matches the app's JPEG normalization before the MobileNet transforms. Features are extracted once and cached for repeated local training.

## Next improvement that matters

Obtain the dataset's source/license and clinical labeling method. Recover patient IDs, split by patient, and collect a separate evaluation set from the intended facilities, skin tones and phone cameras. Pair photos with contemporaneous measured bilirubin if the intended task is bilirubin estimation. Independently evaluate missed-positive cases and capture-quality failures before considering clinical use.

Do not add random yellow color augmentation: it changes the visual cue the model is supposed to learn. This baseline has no synthetic augmentation and has not been fine-tuned on the held-out set. It has no out-of-distribution detector, so unrelated images can also receive a class score.

## Method reference

Architecture and pretrained preprocessing follow the official [TorchVision MobileNetV3 Small documentation](https://docs.pytorch.org/vision/main/models/generated/torchvision.models.mobilenet_v3_small.html). The pretrained network is a generic image feature extractor, not a pretrained neonatal diagnostic system.
