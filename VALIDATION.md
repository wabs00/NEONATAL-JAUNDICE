# Validation — release 2.2.0, 12 October 2026

See [the full audit report](AUDIT_REPORT.md) for findings, repairs and reproducible commands.

## Passed

- 156 checked HTTP requests across 16 regression scenarios.
- 30 core integration checks and 14 research integration checks.
- Five model-artifact tests and four training-data integrity tests.
- Python compilation, browser JavaScript syntax and strict TypeScript checks.
- Fresh backend installation and launch; Python dependency consistency checks.
- Fresh locked mobile dependency installation, guarded decoder compatibility patch and Expo web export.
- Desktop browser and Expo web workflows using fictional accounts and synthetic images: registration, login, submission, review, search, filtering, export, logout and session restore/expiry.
- Decoder, query-string and Xcode UUID compatibility checks after dependency updates.

## Verification limits

Physical-device camera, SecureStore and native builds remain untested. The research model is not clinically validated. Two unpatched upstream dependency advisories remain, represented by 19 high-severity package entries. No complete penetration test or sustained load benchmark was performed.

All audit databases were isolated. No runtime databases, patient photos, original training photos or installed dependencies are included in the archive.
