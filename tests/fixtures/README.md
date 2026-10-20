# Synthetic fixtures

All automated fixtures are generated or authored synthetic data. `foundation` contains deliberate schema/time failures; factories provide mixed labels, null values, unknown categories, manifests, model metadata and actor claims at a fixed UTC time. No fixture is sampled from the historical dataset. Later contract tests must reject the invalid fixtures once the Phase 2 validators exist. No fake database connections or scoring outputs stand in for unimplemented services.

PostgreSQL tests use marker `postgres` and an explicitly supplied `MULE_TEST_DATABASE_URL` whose database name starts `mule_test_`. The guard rejects ordinary operational database names and query-based connection overrides. It never performs a reset. The dedicated database must also use a separate least-privilege role before Phase 3 adds mutation tests.
