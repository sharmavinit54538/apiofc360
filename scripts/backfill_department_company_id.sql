-- =============================================================================
-- Migration / Backfill Script: Backfill departments.company_id from users.company_id
-- =============================================================================
-- Problem:
--   Departments created prior to tenant scoping have `company_id = NULL`.
--   With multi-tenant filtering enabled, those departments will not appear
--   for users querying within their company scope.
--
-- Solution:
--   Backfill `departments.company_id` using the `company_id` of the user who
--   created the department (`departments.created_by -> users.id -> users.company_id`).
--
-- Safety Guarantees:
--   1. Only modifies rows WHERE `departments.company_id IS NULL`.
--   2. Only updates when the creator user has a valid, non-null `company_id`.
--   3. Does NOT touch rows that already have a `company_id`.
--   4. Wrapped in a transaction (BEGIN ... COMMIT) so it can be reviewed and tested safely.
-- =============================================================================

BEGIN;

-- Step 1 (Optional Preview): Inspect departments that will be updated
-- SELECT
--     d.id AS department_id,
--     d.department_code,
--     d.department_name,
--     d.company_id AS current_company_id,
--     u.id AS created_by_user_id,
--     u.company_id AS new_company_id
-- FROM departments d
-- INNER JOIN users u ON d.created_by = u.id
-- WHERE d.company_id IS NULL
--   AND u.company_id IS NOT NULL;

-- Step 2: Perform the backfill UPDATE
UPDATE departments
SET
    company_id = users.company_id,
    updated_at = NOW()
FROM users
WHERE departments.created_by = users.id
  AND departments.company_id IS NULL
  AND users.company_id IS NOT NULL;

-- Step 3 (Verification): Check if any departments still have company_id = NULL
-- (e.g., if created_by was null or user had no company_id)
-- SELECT id, department_code, department_name, created_by
-- FROM departments
-- WHERE company_id IS NULL;

COMMIT;
