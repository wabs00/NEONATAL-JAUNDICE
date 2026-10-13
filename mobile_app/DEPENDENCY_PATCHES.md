# Dependency patches — release 2.2

The package overrides retain Expo SDK 57 and its React Native generation. They patch command quoting, source maps, affected modern brace-expansion versions, URI decoding and the uuid implementation used by the Xcode project helper.

`npm ci` runs `scripts/patch-uri-decoder.cjs`. Upstream decode-uri-component 0.5.0 fixes its malformed-input performance issue but changes to ES modules; retained query-string consumers require a CommonJS function. The script checks the installed version and the exact upstream source checksum, changes only the export syntax/module type and keeps the patched algorithm. It refuses unexpected source and modifications outside this project’s node_modules. It is idempotent.

Do not omit this local compatibility step. If installing with `--ignore-scripts`, run `node scripts/patch-uri-decoder.cjs` before building. Remove it only after verifying router/query-parser compatibility with upstream module exports.

Two high-severity underlying upstream advisories remain unpatched as of the audit: braces 3.0.3 and node-forge 1.4.0. See `../AUDIT_REPORT.md` and the raw scans in `../audit/evidence/`. A successful build is not a security-clear or clinical-readiness sign-off.
