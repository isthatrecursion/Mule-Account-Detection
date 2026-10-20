# Phase 3 Linux PostgreSQL startup fix

Prepared: 2026-10-21. After commit `4bb835c`, both foundation jobs passed. The [PostgreSQL job](https://github.com/isthatrecursion/Mule-Account-Detection/actions/runs/39503031492/job/118904983771) failed with 186 passing tests and 22 PostgreSQL fixture errors: password authentication failed for `mule_migration`.

## Cause and change

The secret generator creates private mode-0600 files. Linux file-backed Compose secrets preserve host ownership; the PostgreSQL identity cannot read files owned by the runner. The official entrypoint reads the administrative password while root, then switches identities before running initialization scripts. Role-password reads therefore failed. The old `export NAME="$(cat ...)"` statements returned the successful export status, hiding failed reads from `set -e` and allowing empty role passwords.

Compose now invokes a wrapper that reads and validates role secrets before the official privilege switch. Separate assignments propagate read failures. The initialization script uses those injected values, validates them, and keeps a fail-fast fallback for direct initialization. Secret permissions remain private. Git attributes require LF for shell scripts on Windows and Linux.

The workflow tests startup with private synthetic files owned by UID 1001 inside a disposable Linux container. It checks missing, empty and unreadable secrets; requires TCP SCRAM authentication; rejects wrong passwords; and authenticates migration, runtime, read-only and tracking roles. A separate preflight checks the actual Compose connections before the full persistence suite.

## Verification

- [Linux reproduction and corrected startup](../../artifacts/phase3/ci_private_secrets_fix_v1/report.json): the original initializer reproduces the exact migration-role authentication failure; corrected startup passes all four logins and failure checks. Disposable containers have no published ports or persistent data mounts.
- [Full Windows/Docker regression](../../artifacts/phase3/private_secrets_regression_v1/report.json): integrated package, formatting, typing, synthetic/PostgreSQL tests, schema checks and build results.

Remote CI for this new change remains pending until it is committed and pushed. Existing volumes are not reset or repaired by this change. Qualified-use gates remain unchanged.
