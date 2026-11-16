OFC360 Employee schema and Asset Management release verification — 16 November 2026

**Decision: NO-GO for production. Implementation and disposable verification passed.**

All 153 final tests passed; none failed, skipped, errored, or remained blocked. Production release still requires the existing encryption key ring to be restored and the new migration applied to the deployment database. No production DDL or data writes were performed during this work.

1. **Root cause and observed state**

The reported Employee drift comes from migration history diverging from executed schema changes. `905a_dpdp_field_encryption` owns the five nullable `VARCHAR(64)` blind-index columns, their nonunique `(company_id, blind_idx)` indexes, and widening encrypted employee/bank fields to `TEXT`. `EncryptedString` stores AES-256-GCM envelopes in `TEXT`; blind indexes use the existing tenant-bound, normalized HMAC-SHA256 function and configured field key ring.

The repair chain already contained `36bffd8d9cb2` (blind columns/indexes), `36bffd8d9cb3` (ciphertext storage widening), and `36bffd8d9cb4`/`cb5` (other Employee columns and organization FKs). Their descriptions explicitly identify earlier stamping over unapplied migrations. The local `fix_alembic.py` utility also directly rewrote `alembic_version` without DDL; it has been disabled locally. Its filename is ignored by this repository. The original operator action is not independently reconstructable from available logs.

Both Batch 7 revisions were reviewed before adding a migration: `911a_batch7_p3_differentiators` and its catch-up revision `36bffd8d9cb1`. They add Employee `last_promotion_date`, Company branding, and related module objects; they do not repair Employee blind indexes. The actual revision graph, rather than stale `Revises` docstrings in some repair files, was used. Fresh base-to-head migration and graph checks pass.

At inspection time, the configured database was already at `40d7b5c909b3`: all five blind columns, all five composite indexes, ciphertext `TEXT` types, Employee FKs, and Company/Asset objects existed. The old missing-column error was therefore not reproducible there. **Three additional real mismatches remained:** `is_pf_eligible`, `is_international_worker`, and `pf_wage_ceiling_applicable` were nullable, whereas both the model and revision `902a` require NOT NULL. None currently contains NULL.

The missing-column condition was reproduced only in a disposable, transactionally rolled-back rehearsal. PostgreSQL returned **SQLSTATE `42703`**, naming `employees.aadhaar_number_blind_idx`. The audit identified all five missing columns/indexes together, plus ciphertext type and statutory nullability drift. There were no SQL errors in the configured read-only model probes. The initial Asset test run instead stopped at Python collection because of indentation errors; that has no SQLSTATE.

Evidence: [configured schema before changes](../verification/asset-pg-20261116/configured-schema-before.json), [final read-only audit](../verification/asset-pg-20261116/configured-readonly-final.json), [reproduced drift and SQLSTATE](../verification/asset-pg-20261116/reproduced-drift.json).

2. **Exact implementation changes**

| File | Change |
|---|---|
| `alembic/versions/41a_employee_schema_contract.py` | New repair-only head after `40d7b5c909b3`. Adds missing blind columns/indexes if necessary; safely widens string ciphertext storage to TEXT; validates existing blind-column definitions and index columns, uniqueness, predicates, validity/readiness; enforces the three statutory NOT NULL flags and their existing model defaults. Refuses unresolved NULL records or incompatible objects instead of guessing. Uses a five-second lock timeout. Reentrant upgrade; downgrade intentionally preserves repaired data/schema. No PII decryption in DDL. |
| `scripts/backfill_encrypted_pii.py` | Uses the existing encryption/HMAC methods unchanged. Adds keyset pagination and row locks to avoid stale overwrites. Validates ciphertext, leaves an unreadable or tenantless row untouched, reports aggregate quarantine counts and optional operator-only IDs/reason codes, exits 2 if unresolved rows remain. Preserves dry-run and tenant-scoped operation. |
| `app/models/employee.py` | Removes `delete-orphan` ownership from Employee.assets and preserves database SET NULL behavior. Returning/unassigning an asset must not delete inventory/history. |
| `app/models/asset/request.py` | Adds the employee-name response property. |
| `app/repositories/asset_repository.py` | Blocking row locks refresh stale state; request transitions can lock their row; request queries eagerly load the employee; active warranty excludes the separate 30-day expiring bucket. |
| `app/services/asset_service.py` | Repairs four indentation errors. Locks mutating lifecycle operations, synchronizes holder relationships, refreshes history for responses, rejects assignment of archived/nonavailable assets, maps approving auth users to Employee FKs, validates requesting employees within their tenant, and restricts damage reports to the holder. Fulfillment now assigns the asset and writes history/timeline in the same transaction as request completion. Corrects repeated-maintenance-completion validation. |
| `app/schemas/asset.py` | Exposes employee/lost and maintenance completion fields in private responses; preserves explicitly supplied status updates so the service rejects bypassing lifecycle operations. Existing camelCase history response contract remains intact. Public response remains restricted. |
| `app/api/assets.py` | Resolves auth User IDs to Employee IDs for requests/damage reports; nonadmin request lists are scoped to the caller; static collection routes precede the UUID route. |
| `tests/test_asset_management_comprehensive.py` | Requires the disposable database runner, creates an independent tenant per test, removes broad tag-prefix deletion, fixes invalid fixtures and existing response-name expectations, makes concurrency use two synchronized sessions, verifies persistence through fresh sessions, asserts actual assignment on fulfillment, and checks an API 403 for employee inventory access. Still exactly 41 tests. |
| `tests/test_asset_release_security.py` | Twelve PostgreSQL/API gates for role denial/allowance, authenticated-user mapping, tenant/holder isolation, archived assignment, concurrent fulfillment, and rollback after an injected failure following assignment flush. |
| `tests/test_employee_schema_repair_postgres.py` | Five PostgreSQL migration/backfill tests: all-field drift repair, repeated repair, ciphertext preservation, missing-column SQLSTATE, HMAC backfill/retry, refusal of NULL statutory flags/incompatible indexes, dry-run, corrupt ciphertext and missing tenant handling. |
| `scripts/asset_disposable_pg.py`, `scripts/asset_verify_schema.py` | Isolated loopback verification harness and read-only model/schema auditor; the auditor exits nonzero on drift. |
| Regression tests | Correct stale expectations in three files: directory results omit salary; unverified login returns an OTP challenge with no auth tokens/cookies; invitation uses current `create_user`; password verification mock targets the async function; refresh rotation checks timestamp and replacement-token hash as well as family preservation. Production auth behavior was not weakened. |

3. **PostgreSQL and migration verification**

PostgreSQL 18.3 ran in a dedicated cluster under ignored `scratch/asset-verification-20261116`, listening only on `127.0.0.1:55442`. The test role has no superuser, CREATEDB, or CREATEROLE privilege. Databases: `asset_verify_suite`, `asset_verify_regression`, `asset_verify_migration`. Test encryption configuration is confined to child test processes and never replaces deployment keys. The cluster was stopped after verification; its disposable data and evidence were retained.

| Execution | Result |
|---|---|
| Initial empty Asset database: Alembic base → `40d7b5c909b3` | Exit 0 |
| Asset database: `40d7b5c909b3` → `41a_employee_schema_contract` | Exit 0 |
| Empty regression and final migration databases: base → new head | Exit 0 |
| Repeat `alembic upgrade head` | Exit 0; already at head |
| Repair body rerun against seeded partial drift | Passed, including second invocation and unchanged ciphertext |
| Graph continuity, single head/base, revision length | Four tests passed |

No `alembic stamp` or migration-ledger rewrite was used. The Asset schema was built by Alembic, not by `create_all`. Final audits found **zero mismatches** in `companies`, `employees`, `employee_bank_accounts`, `assets`, `asset_assignment_history`, `asset_maintenance_records`, `asset_requests`, and `asset_damage_reports`: expected columns/types/nullability, PKs, unique definitions, model indexes, FKs and named checks were checked; reflected definitions are retained in JSON. Legacy extra indexes are preserved.

Evidence: [fresh full migration](../verification/payroll-pg-20261115/asset-fresh-final-migration/summary.json), [repair migration](../verification/payroll-pg-20261115/asset-repair-migration/summary.json), [repeat migration](../verification/payroll-pg-20261115/asset-migration-repeat/summary.json), [Asset database schema](../verification/asset-pg-20261116/disposable-schema-final.json), [fresh database schema](../verification/asset-pg-20261116/fresh-schema-final.json). The reused runner stores command/log/XML evidence under the preexisting `payroll-pg-20261115` directory; these run labels are Asset verification runs from 16 November.

4. **Actual test results**

The exact requested command was executed through the isolated runner:

```powershell
python scripts/asset_disposable_pg.py run --database asset_verify_suite --label asset-final -- python -m pytest tests/test_asset_management_comprehensive.py -v --tb=short
```

The runner only appends JUnit and temporary-directory options. Counts below are reconciled from pytest collection output and JUnit test cases, not inferred from category descriptions.

| Final run | Collected | Passed | Failed | Skipped | Errors | Blocked |
|---|---:|---:|---:|---:|---:|---:|
| Asset comprehensive | 41 | 41 | 0 | 0 | 0 | 0 |
| Added API/security + schema/backfill | 17 | 17 | 0 | 0 | 0 | 0 |
| Employee/Auth/encryption/Exit/Payroll concurrency regressions | 84 | 84 | 0 | 0 | 0 | 0 |
| Payroll API suite, including full-and-final settlement | 11 | 11 | 0 | 0 | 0 | 0 |
| **Distinct final tests** | **153** | **153** | **0** | **0** | **0** | **0** |

Pytest has no built-in “blocked” outcome; no final collection/setup error or skipped test is being counted as passed. Deployment blockers below are separate from test outcomes.

Asset category reconciliation: inventory 5 + assignment 7 + return 2 + transfer 4 + status/lost/recovery 4 + maintenance 3 + requests 4 + damage 3 + soft deletion 2 + warranty 1 + public fields 1 + concurrency 1 + Exit 1 + timeline 1 + RBAC 2 = **41**.

The 84 regressions comprise Employee CRUD 5, salary/lifecycle 12, creation robustness 2, authentication lifecycle 7, refresh/cookie hardening 15, revocation/rotation 10, encryption/DPDP 11, Batch 4/Exit/FnF 10, PostgreSQL concurrency 8, and Alembic graph 4. These intentionally mix unit/mocked tests, SQLite module tests, and PostgreSQL integration tests. All 41 Asset tests, 17 new checks and 11 Payroll API tests run against migrated PostgreSQL. API role checks use controlled authenticated claims; actual token/login/refresh behavior is tested by the authentication regressions. This is not a claim that every backend test has been run.

Evidence: [41 Asset results](../verification/payroll-pg-20261115/asset-final/results.xml), [17 supplemental results](../verification/payroll-pg-20261115/asset-supplemental-final/results.xml), [84 regression results](../verification/payroll-pg-20261115/asset-regressions-verified/results.xml), [11 Payroll API results](../verification/payroll-pg-20261115/asset-payroll-api-regressions/results.xml), [machine-readable release totals](../verification/asset-pg-20261116/release-summary.json). Each directory also retains `command.json`, `summary.json`, and the pytest `execution.log`.

Earlier failures are retained: initial collection 0 tests/1 error due to indentation; first runnable baseline 25 passed/16 failed of 41; first fix run 40 passed/1 fixture failure; regression run 79 passed/5 obsolete-contract failures of 84. One earlier regression attempt encountered Windows sandbox temporary-directory access errors and is not release evidence. The final rerun used approved execution outside that sandbox. Final regression warnings are limited to the existing face-recognition dependency's `pkg_resources` deprecation.

5. **Remaining release blockers and controlled deployment procedure**

The configured database (`equnixsphere_prod` on local port 5432) was inspected read-only. It remains at `40d7b5c909b3` with the three statutory nullability mismatches. No current NULL flag values were found, so the new migration's precondition currently passes, subject to a fresh deployment-time check.

More importantly, **`FIELD_ENCRYPTION_KEY` is absent in the configured application environment**. A transaction explicitly set READ ONLY scanned 1,840 employees and 6 bank accounts. It reported 36 quarantined Employee records and 66 encrypted Employee-field read failures, all stating that the field key is required. It proposed zero writes. No new plaintext was stored; ciphertext was neither replaced nor discarded. Prefix checks found no legacy unencrypted Employee PII, but a prefix alone does not establish decryptability. Two populated UAN values and one populated voter value have NULL blind indexes; their correct result cannot be determined until the key ring is restored (empty normalized values legitimately have NULL indexes).

Evidence: [read-only PII preflight](../verification/asset-pg-20261116/configured-pii-preflight.json). The operator manifest with row IDs/reason codes is retained only under ignored `scratch/asset-verification-20261116/configured-backfill-quarantine.json`.

Required deployment sequence:

1. Restore the **existing** field encryption key ring through deployment secret management, retaining historical decryption keys. Do not generate a replacement key to bypass this failure or paste keys into reports.
2. Confirm the target database and recoverable backup; apply `python -m alembic upgrade head` in the deployment window. If NULL statutory values or incompatible objects are reported, review those records/definitions explicitly and retry. Do not stamp.
3. Run `python -m scripts.backfill_encrypted_pii --dry-run --quarantine-report <private-path>` with the restored configuration. Resolve every quarantined row without replacing ciphertext with NULL. Run the actual backfill only after that review, then rerun to verify zero pending updates and zero quarantined rows. The backfill uses the same configured AES-GCM/HMAC code as the application.
4. Run the schema auditor and deployment smoke/security checks. Use roll-forward correction if a later issue occurs; the new repair downgrade deliberately preserves repaired objects.

**Final release decision: NO-GO until the deployment migration and encryption-key/backfill gates pass.** The code repair and all requested disposable Asset integration verification are complete; production readiness is not asserted.
