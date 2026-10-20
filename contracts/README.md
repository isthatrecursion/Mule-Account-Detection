# Server-owned schemas

Generated from the typed models under src/mule_detection/domain/contracts and domain/feature_policy.py. No payload may supply a local file path, remote schema URL or executable loader. The registry resolves fixed version identifiers to Python classes.

Run `python scripts/generate_contract_schemas.py --check` to compare model output, committed schema files and frozen version_manifest.json digests. Version digests hash canonical generated UTF-8 text with LF line endings; execution evidence separately hashes actual file bytes. Normal generation refuses changes to a registered version. Introduce a new model/version while retaining supported prior versions, then explicitly register it with `--register-new-versions DECISION_REFERENCE`. Review semantic changes separately, including validators not expressible in JSON Schema. This initial engineering contract freeze does not certify source data or approve a model.

See [contract behavior and limits](../docs/contracts.md) and [safe error catalog](../docs/contract_error_catalog.md). JSON Schema captures shape; source ownership, approval authority, temporal history, policy compatibility and complete score state also require the corresponding semantic validators.
