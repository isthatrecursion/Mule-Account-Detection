# Model rollback rehearsal and operation

Scope: local research/test selection. Qualified operation needs certified data,
independent approval and the later shared-deployment controls.

1. Identify the incident/review reference and the previously approved candidate
   for the same target environment. Read the authoritative deployment version
   from `model_deployments`; never infer it from an MLflow alias or tag.
2. Verify the candidate is registered, compatible and not retired/rejected.
   Preserve both current and previous bundle directories, registry mappings,
   decisions, audit events and existing job/score evidence.
3. Run:

   ```text
   mule-detection rollback-model --candidate-id <previous-candidate-uuid> --target-environment research --alias active --expected-version <current-db-version> --reason <incident-reference>
   ```

   The command checks independent digest/environment authorization and the saved
   fixture through the restricted loader before changing selection. It updates
   the future-selection pointer and appends actor, reason, before/after identity
   and deployment version in one transaction. A stale expected version fails.
4. Confirm the new DB version/candidate and the `model:rollback` audit/outbox.
   The successful command includes fixture health and then mirrors the selected
   remote version to the environment-prefixed MLflow alias. If the mirror fails
   after commit, retain the DB change and run:

   ```text
   mule-detection reconcile-model-alias --target-environment research --alias active
   ```

   Reread DB authority before retrying a rollback; a command error does not mean
   the deployment transaction rolled back after an external mirror failure.
5. New jobs pin the restored candidate. Existing jobs keep their immutable pins;
   retirement/revocation prevents their publication when revalidated. Completed
   runs remain unchanged. Any rescoring must use a new explicit run and preserve
   the original lineage.

The synthetic two-bundle test changes selection twice and rolls back, verifies
immutable existing-job identity, rejects stale updates and checks the rollback
audit. Missing/corrupt/retired or incompatible targets cannot pass the loader.
