# Phase 3 first remote CI failure and checkout fix

Prepared: 2026-10-21. PR #1 initially tested commit `2e90571`. The Windows foundation job passed; the Linux foundation job failed at **Check versioned contract schemas**, and PostgreSQL failed at **Persistence checks**. Job metadata was retrieved from GitHub's public Actions API. Detailed job-log downloads require authentication; the diagnosis below is supported by an independent clean-checkout reproduction.

## Cause and change

The registered `research_v1` schema stores the exact SHA-256 of `eda/01_schema_and_feature_dictionary.csv`. The approved local dictionary uses CRLF serialization and hashes to `967a9f412a398c9c8b7f714eb87e80915ef3bfc6e66d03d98284ccdfd131739a`. Git's Windows text normalization stored LF bytes in the original commit, hashing to `070c2a071d9a0e189df52511ab5e6ff7f8d51f7d83cd68e80c151384a1a49d0b`. The parsed text/values agree after newline normalization, but the raw bytes do not. Windows checkout restores CRLF; Linux checkout keeps LF. The research-schema generator correctly rejected the mismatched provenance fingerprint.

`.gitattributes` now marks only this source dictionary `-text`. The dictionary must also be re-added using `git add --renormalize -- eda/01_schema_and_feature_dictionary.csv` so Git stores the original bytes instead of retaining the earlier normalized blob. Its working-file content, registered digest, feature roles/types, contract versions, raw dataset, split and holdout boundaries remain unchanged. This is preservation of the existing byte identity, not regeneration of the frozen registry around a different input.

`tests/unit/test_dictionary_checkout.py` reproduces the old Windows add operation, then verifies that re-adding under the new attribute preserves the registered bytes in both LF and CRLF checkout configurations. The tests use isolated temporary Git repositories and do not commit or alter the user's index/configuration.

## Evidence and status

- [Clean Linux reproduction and corrected checks](../../artifacts/phase3/ci_line_endings_fix_v1/report.json): exports a Git checkout with Linux EOL settings using a separate index/object directory, leaves the private dataset as an unexpanded LFS pointer, reproduces the original research-schema failure, then verifies the corrected schema and foundation checks.
- [Windows/Docker regression run](../../artifacts/phase3/windows_ci_fix_v1/report.json): **208 tests**, including 22 PostgreSQL cases and the two new Git checkout regressions; all integrated checks pass against Docker PostgreSQL 17.9.
- [Earlier Docker verification](../../artifacts/phase3/docker_20261020_221852/report.json) and [container recreation](../../artifacts/phase3/docker_restart_20261020_221852/report.json) confirm that the earlier Docker startup/lifecycle gap is now closed on this machine. The original Phase 3 handoff remains a historical record of its preparation-time status.

The new remote CI run remains pending until this fix is committed and pushed to `codex/phase3-persistence`. Local passing evidence must not be reported as remote CI passing. All external qualified-use approval gates remain unchanged.

Initial failed runs: [Foundation](https://github.com/isthatrecursion/Mule-Account-Detection/actions/runs/39497963062), [PostgreSQL](https://github.com/isthatrecursion/Mule-Account-Detection/actions/runs/39497963095).
