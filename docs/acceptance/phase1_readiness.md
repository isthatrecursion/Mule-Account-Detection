# Phase 1 implementation and handoff

Prepared: 2026-10-20. Scope: **research package, configuration, error/CLI conventions, clocks, synthetic tests and CI foundation**. Qualified operation remains blocked. This phase creates no deployable scoring model, database service, API or analyst UI.

## Delivered points

| Point | Implementation | Evidence |
|---|---|---|
| P01.01 | Streaming preservation script and immutable reference manifest for nine original evidence files; saved historical dependency versions retained. | [Windows reference verification](../../artifacts/phase1/windows_foundation_v3/check_09.txt); copied-fixture mutation test. Historical hashes match the original verification report. |
| P01.02 | Installable src-layout package with domain/application/adapters and all twelve architecture module boundaries; UI boundary documented. | Wheel/sdist builds on both systems; fresh wheel import outside checkout. |
| P01.03 | Python 3.12 package metadata, five exact reference ML pins, separate hashed Windows/Linux runtime/dev locks, pinned build tools. | pip-tools resolution on each target platform, pip check, and [fresh runtime installation](../../artifacts/phase1/windows_install_v2/report.json). |
| P01.04 | Pydantic settings with explicit precedence, mandatory secret endpoints, confined absolute paths, positive limits, policy fingerprints and research/qualified restrictions. | Positive and negative settings tests on both systems. Endpoint values never appear in ordinary errors or public fingerprints. |
| P01.05 | Secret/environment/export/private-fixture/model ignores and independent Docker context allowlist. | [Exclusion and package-content controls](../../artifacts/phase1/controls_v1/report.json). Reviewed historical artifacts and .env.example stay trackable. |
| P01.06 | Stable safe error codes/exit codes; allowlisted JSON logs that drop arbitrary messages, payloads, notes, exception details and malformed extras. | Secret-bearing exception and malformed-metadata regression tests; safe nonzero CLI failure tests. |
| P01.07 | Deterministic mixed-class, null/unknown-category factories; duplicate-column and invalid-time fixtures; fixed clock; dedicated test-database guard and explicit markers. | [Synthetic-only checkout](../../artifacts/phase1/clean_checkout_v2/report.json): 38 tests pass with no raw CSV or historical artifact directory. Actual input-contract validators belong to Phase 2. |
| P01.08 | Windows/Linux GitHub Actions matrix installs locks, runs lint/types/tests, builds a wheel and checks a fresh install; uploads safe failure evidence. | Matching local check sequences pass; broken fixture/import controls return nonzero. **Remote GitHub Actions execution NOT_RUN.** No PostgreSQL service job is claimed before Phase 3. |
| P01.09 | Typed argparse requests and thin application dispatch for validate/train/evaluate/score/reconcile/replay/health. | Bad arguments never dispatch; all six unimplemented operations fail with UNSUPPORTED_OPERATION. Health returns foundation_only, not operational readiness. |
| P01.10 | UTC SystemClock/ManualClock, real monotonic duration timer and immutable execution context. | Ten logical minutes advance instantly while compute timer measures real elapsed time; context immutability test. Future job/lease/maturity policies must accept these interfaces. |

## Executed verification

- [Windows final foundation report](../../artifacts/phase1/windows_foundation_v3/report.json): Python 3.12.10; **38 tests pass**, Ruff, formatting, strict mypy, pip check, wheel/sdist build, CLI help, 271 Phase 0 specification checks and unchanged-reference verification pass.
- [Linux final foundation report](../../artifacts/phase1/linux_foundation_v3/report.json): Python 3.12.15 in Ubuntu/WSL; **38 tests pass**, Ruff, formatting, strict mypy, pip check, wheel/sdist build, CLI help and Phase 0 checks pass. Linux runtime/dev locks were resolved on Linux, not copied from Windows.
- [Fresh final-wheel installation](../../artifacts/phase1/windows_install_v2/report.json): a second isolated runtime environment installs the hashed runtime lock, checks dependencies and every locked version, imports the package and ML libraries outside the repository, then exercises CLI help.
- [Synthetic checkout report](../../artifacts/phase1/clean_checkout_v2/report.json): the final wheel's package files plus synthetic tests/configuration pass all 38 tests without confidential inputs. The copy contains neither DataSet__1_.csv nor historical artifacts.
- [Negative/exclusion controls](../../artifacts/phase1/controls_v1/report.json): ten checks cover failure propagation, ignored secrets/exports, trackable example/reference files, Docker exclusions, archive contents and redacted argument errors. These are local controls, not a remotely executed CI approval.

Each saved run has an exclusive directory and checksum manifest. Foundation reports record actual commands, UTC execution times, interpreter/dependency versions, Git HEAD plus dirty state and exact source/config/fixture fingerprints. These are uncommitted implementation runs; the report does not pretend the implementation is already present in HEAD. Roadmap status and this handoff are written after execution and remain outside the source manifest to avoid circular hashes.

The first Linux run is retained as FAILED: pytest's fd-capture temporary file could not be truncated on the WSL-mounted Windows filesystem. The runner now uses native temporary storage on Linux and workspace temporary storage on Windows; subsequent runs pass. Earlier intermediate runs are retained as history. No failed run was overwritten or converted into a pass.

## Reproduce and continue

See [development instructions](../development.md) for installation, lock regeneration, configuration, secrets, command syntax and evidence reproduction. Use a **new** run directory:

```powershell
.\.venv\Scripts\python.exe scripts/verify_foundation.py --with-reference --output-dir artifacts/phase1/my_new_run
.\.venv\Scripts\python.exe scripts/verify_installation.py --wheel artifacts/phase1/my_new_run/dist/mule_detection-0.1.0-py3-none-any.whl --output-dir artifacts/phase1/my_new_install
```

On Linux use its Python 3.12 environment and omit --with-reference in CI or on a machine without approved confidential inputs. Wheel installation requires package-index access or a prepopulated approved cache. The synthetic tests themselves need no network. Fast tests exclude postgres/benchmark markers; no nonexistent integration is silently counted as passing.

Phase 1 is engineering-complete within this foundation scope. Human agreement to Phase 0 operating policies remains pending; all 14 external dependencies remain open, and product acceptance requirements remain PLANNED. Reading qualified settings is not model approval. Model/data qualification must still come from immutable validation and independent approval records in later phases. Remote CI, PostgreSQL integration, reference ML parity after refactoring, operational services and production controls remain future checks.

Phase 2 can implement versioned batch/snapshot/label/dictionary/model/event/evidence contracts, failure fixtures and the research adapter using this foundation. Do not fit, tune, demonstrate or operationally evaluate on the saved 1,817-row holdout; do not assign business meanings to anonymous features. No architecture design decision changed.
