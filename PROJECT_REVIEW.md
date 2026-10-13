# Project review

The archive contains a FastAPI backend and an Expo Router mobile app, plus a second unused React Navigation screen tree. There is no trained vision model in the archive.

| Finding in original | Version 2 change |
| --- | --- |
| `prediction.py` randomly chooses a diagnosis and confidence | Removed; all new records await clinical review |
| Different hardcoded LAN addresses in API and screens | Same-origin dedicated web app; one configurable Expo backend URL |
| Tokens passed in router query parameters | HttpOnly web cookies; native SecureStore and bearer sessions |
| JWT secret hardcoded in source | Random revocable sessions; only token hashes stored in database |
| Client image filename used as a storage path | Server-generated image names and private retrieval |
| No image decoding or upload limits | Format/content checks, byte/pixel limits and thumbnail re-encoding |
| Dashboard loads every record | SQL aggregate totals and indexed, paginated record reads |
| No dependency manifest for Python or launch instructions | Requirements, Windows launch script and setup guide |
| Default-looking screens with weak loading/error handling | Consistent green care workspace, responsive forms and error messages |
| No clinical review workflow | Notes, measured bilirubin, Reviewed/Referred statuses |
| Two competing mobile screen trees | Expo Router entry renders a single shared workspace |

The changes improve the implementation structure and eliminate unnecessary work. They do not establish a measured speedup, medical-device certification, or diagnostic accuracy.

Existing SQLite records are deliberately not migrated: the original stored random predictions, and copying them as clinical results would misrepresent their provenance. The source ZIP and its original records remain available separately.
