# Application audit — 12 October 2026

**Verdict:** The tested documentation and research workflows are operational after repairs. This is not a clean production-security or clinical-readiness sign-off. Two upstream mobile-toolchain advisories remain unpatched, and native hardware behavior and clinical accuracy are not validated.

Audited release: **2.2.0**. The saved source, a fresh backend installation, a fresh mobile dependency installation, desktop web, Expo web and the exported research model were reviewed. All tests used isolated temporary databases or fictional accounts and synthetic photos. The original project ZIP, dataset and existing application records were not modified.

## Checks and outcomes

| Area | Evidence | Outcome |
| --- | --- | --- |
| Registration | Required fields, whitespace-only names/facilities, duplicate ID/email, password constraints; real browser registration | Pass after repair |
| Authentication | Cookies, bearer tokens, invalid credentials, expiry, logout, mixed-case bearer schemes, rejected foreign origins | Pass after repair |
| Interactive API docs | OpenAPI bearer scheme and protected-operation security declarations | Pass after repair |
| Assessment capture | Required fields, age/weight/gestation bounds, feeding enums, JPEG/PNG/WebP, permission acknowledgment | Pass after repair |
| Photo handling | Byte/pixel limits, invalid content, EXIF preprocessing parity, random filenames, private image access | Pass |
| Missing/corrupt photos | Missing files return 404; corrupt stored images fail inference with 422; records remain intact | Pass after repair |
| Records/history | Search, literal percent/underscore characters, filters, page navigation, own-record isolation | Pass after repair |
| Reviews | Notes, measured bilirubin, reviewed/referred states, invalid numeric inputs, dashboard totals | Pass after repair |
| Export | 106 rows exported, 105-row filtered subset, ownership, formula guards, quoted/multiline notes; browser download parsed | Pass after repair |
| Concurrency | Eight parallel assessment saves produce eight unique records and correct totals | Pass; limited smoke test |
| Research model | Availability, inference, cached results, privacy, disabled mode, clinical-record separation | Pass |
| Model artifacts | Checksum, finite parameters, correct class mapping, score contract, app/training preprocessing parity | Five tests pass |
| Training helpers | Empty dataset handling, stale image rejection, dataset path confinement, changing patient labels | Four tests pass |
| Mobile interface | Strict TypeScript, fresh Expo web build, account/login/upload/review/referral/model/session-restore browser workflow | Pass for web build |
| Installation | Windows launcher created a fresh virtual environment and installed dependencies; pip dependency checks | Pass |
| Native Android/iOS | Camera hardware, denial/permission flows, SecureStore persistence and native binary builds | Not verified |
| Security dependencies | Registry scan and targeted compatible patches | Partial: no critical/moderate entries; 19 high entries remain |
| Clinical use | Patient-separated evaluation, label verification, independent clinical testing | Not validated |

The comprehensive regression suite executes **156 checked HTTP requests across 16 test scenarios**. The separate core and research suites execute **30 and 14** checks respectively. Counts overlap in functionality and are not a claim of complete code coverage. Browser checks additionally exercised registration, validation, upload, review, search, pagination, export, HTML-like identifiers, guide navigation and session expiry. Required-field submission was stopped by browser validation. An HTML-like baby ID rendered as text, with no image element created in the records table.

## Defects repaired

| Finding | Before | After |
| --- | --- | --- |
| Whitespace account details | A name or facility containing only spaces could become an empty stored value | Trimmed before length validation; rejected with 422 |
| Photo permission not enforced by API | A direct API upload could omit or deny the interface acknowledgment | `consent=true` required by API and recorded in the database; both clients send it |
| Search wildcard mismatch | `%` and `_` acted as SQL wildcards and returned unrelated records | Literal substring search escapes those characters |
| Missing photo crash | Private photo retrieval returned generic 500 when a file was absent | Clear 404; corrupt images receive a controlled inference error |
| Non-finite JSON crash | NaN/infinity review inputs caused 500 while formatting validation errors | Safe 422 response without echoing raw input; stored review remains unchanged |
| Paged CSV instability | Browser assembled separate pages while data could change | One server-side SELECT captures the matching export rows |
| Expired-session privacy | Unsaved forms/cached display state could survive session failure | Forms, photos, model output and cached state cleared; old asynchronous responses guarded |
| Stale login message | A prior “sign in again” error remained after successful re-login | Error messages cleared when entering the workspace |
| Bearer scheme mismatch | Lowercase `bearer` did not match the scheme returned by login | Standard HTTP bearer parser accepts case-insensitive schemes; logout revokes the same selected token |
| API documentation auth gap | Protected operations had no bearer authorization declaration | OpenAPI exposes the bearer scheme for interactive testing |
| Model artifact handling | Some malformed classifier metadata could load; load failure lacked a diagnostic log | Shape/finite/class checks and startup logging added |
| Training reproducibility | Changed files could reuse old audit/cache assumptions | Files checked against manifest hashes; cache identity includes feature contract; model identity includes weights |
| Empty training inventory | Audit CLI could index an empty row list | Clear CLI error with audit evidence preserved |
| Mobile failed-load display | Initial failures could leave unexplained zero totals | Error surfaced and unloaded totals shown as unknown |
| Mobile logout state | Network failure could prevent local session clearing | Local session/workspace cleared even if the server call fails |
| Release/launch consistency | Different version metadata and fixed-port collisions | Release metadata aligned at 2.2; launch scripts accept `-Port` |

For existing records, the new permission-acknowledgment column remains null rather than inventing past consent. This flag records the uploader’s acknowledgment; it is not independent verification of permission.

## Dependency security findings

The initial production-dependency scan reported **34 affected package entries**: 1 critical, 21 high and 12 moderate. The post-patch scan reports **19 high entries, 0 critical and 0 moderate**. Parent-package entries propagate underlying advisories; they are not 19 distinct vulnerabilities.

Applied changes retain Expo SDK 57 and React Native 0.86:

| Dependency | Selected patch |
| --- | --- |
| shell-quote | 1.12.0 |
| source-map-js | 1.2.2 |
| brace-expansion, affected modern versions | 5.0.12 |
| decode-uri-component | 0.5.0, with a checksum-guarded CommonJS export compatibility step |
| xcode’s uuid dependency | 11.1.1 |

The patched decoder changes module format upstream, while the retained query parser expects a CommonJS function. The local postinstall script preserves the upstream patched algorithm and adjusts its export format; it checks version and source checksum before modifying only the installed module. Decoder/query-parser and Xcode UUID compatibility were tested, and the fresh mobile build passed. No forced Expo downgrade was applied.

Two underlying advisories remain open:

1. **braces 3.0.3:** stack-exhaustion denial of service with deeply nested patterns. [Maintainer-reviewed advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) lists no patched version.
2. **node-forge 1.4.0:** RSA signature verification accepts malformed nested elements. [Maintainer-reviewed advisory](https://github.com/advisories/GHSA-86w9-cpqp-85rv) lists no patched version.

These affect inherited Expo/Metro/build/signing dependencies. The dedicated Python-served web client does not depend on Node at runtime. Exploit reachability across all native/build paths was not established. Their presence prevents a blanket “security clean” conclusion. Build only trusted source and input, keep development tooling private, and revisit supported upstream patches before production/native release.

Raw scan evidence is preserved in `audit/evidence/npm-audit-before.json` and `npm-audit-after.json`. `mobile_app/DEPENDENCY_PATCHES.md` documents the compatibility step. The critical command-quoting patch is supported by the [shell-quote advisory](https://github.com/advisories/GHSA-pqg4-j6r4-53mv); the decoder upgrade follows its [upstream advisory](https://github.com/advisories/GHSA-vcc3-ghjq-m6fr).

## Remaining verification and product limits

- Android/iOS camera behavior, permission denial, SecureStore persistence and native builds still need actual device testing. Expo web is not a substitute for that test.
- The trained model classifies supplied folder labels. It is not a validated diagnosis, measured bilirubin estimator, severity grader or treatment recommender. The previously recorded test missed 7 of 40 jaundice-folder images. Labels and patient-level split independence remain unverified; no retraining or clinical validation was performed during this audit.
- There is no image-quality/out-of-distribution rejection model. An unrelated image can receive a research class score.
- Accounts are self-service and records are nurse-owned. Facility-wide sharing, staff provisioning, password recovery, record deletion/retention automation and immutable clinical edit history are not implemented.
- HTTPS deployment, encryption/backups, incident monitoring, distributed rate limits and recovery procedures were not tested. The in-memory login throttle is intended for a single local process.
- No full penetration test, sustained load test or uptime/SLA assessment was performed.
- The fresh mobile installation and web build were tested. An app-store or native-binary release was not tested.

## Use the audited release

Run `start.ps1` for documentation mode or `start-research.ps1` for the optional research model. Use `-Port 8020` (or another unused port) if an older preview is still running. Verify `/health` reports **2.2.0**; refreshing a page alone does not reload an older Python process.

The audit preview uses an isolated fictional-data workspace. When upgrading a working installation, preserve its existing database and images, keep the same `NEO_DATA_DIR`, and back up that directory before replacing source. The distributable ZIP includes no runtime database or patient photographs.

Re-run the full source audit after installing backend, model and test dependencies:

```powershell
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r backend\requirements.txt -r ml\requirements.txt -r tests\requirements.txt
python tests\full_audit.py
python tests\model_artifact.py
python tests\training_audit.py
```

For the mobile project, run `npm ci` with its local postinstall enabled, `npm run typecheck`, and `npx expo export --platform web`. Repeat the registry scan when preparing a release; its results are time-dependent.
