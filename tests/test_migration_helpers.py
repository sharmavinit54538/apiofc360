"""Test that migration helpers module is importable and has all expected functions."""

import pytest


def test_helpers_module_imports():
    """Test that helpers module can be imported without errors."""
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parent.parent / "alembic"))
    import helpers  # noqa: F401


def test_helpers_has_all_expected_functions():
    """Test that all expected helper functions exist."""
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parent.parent / "alembic"))
    import helpers

    expected_functions = [
        "table_exists",
        "column_exists",
        "index_exists",
        "constraint_exists",
        "enum_type_exists",
        "safe_create_table",
        "safe_drop_table",
        "safe_add_column",
        "safe_drop_column",
        "safe_create_index",
        "safe_drop_index",
        "safe_create_unique_constraint",
        "safe_create_foreign_key",
        "safe_drop_constraint",
        "safe_create_enum",
        "safe_drop_enum",
        "safe_alter_column_type",
    ]

    for func_name in expected_functions:
        assert hasattr(helpers, func_name), f"Missing function: {func_name}"
        assert callable(getattr(helpers, func_name)), f"{func_name} is not callable"


def test_helpers_compiles():
    """Test that helpers.py compiles without syntax errors."""
    import py_compile
    from pathlib import Path
    helpers_path = Path(__file__).resolve().parent.parent / "alembic" / "helpers.py"
    py_compile.compile(str(helpers_path), doraise=True)


def test_no_raw_drop_in_upgrade():
    """Test that no migration in alembic/versions uses raw op.drop_* in upgrade() without safe_ prefix.
    
    This ensures idempotency when running migrations on a fresh database.
    Downgrade functions are allowed to have raw drops since they're for rollback.
    """
    import re
    from pathlib import Path

    versions_dir = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    forbidden_patterns = [
        r"op\.drop_index\(",
        r"op\.drop_column\(",
        r"op\.drop_table\(",
        r"op\.drop_constraint\(",
    ]

    # Migrations that are allowed to have raw drops in upgrade (they import and use helpers, or have their own idempotent logic)
    allowed_files = {
        "9dbecb1de6de_add_performance_indexes_remove_redundant.py",
        "4bb92df30546_add_payroll_new_models.py",
        "34420f95fa30_create_assets_schemas.py",
        "624a163bf6a8_make_departments_unique_per_company.py",
        "c70e966a30a7_add_budget_to_departments.py",
        "e589353e4605_remove_account_lockout_fields.py",
        "6edc3a852a7a_add_shifts_table_and_columns.py",
        "fb1c2d3e4f5a_update_user_and_employee_roles_to_6_system_roles.py",
        "f2g3h4i5j6k7_add_leave_review_columns_and_policy_unique.py",
        "383b3a18b96d_sync_schema_with_models.py",  # Has its own monkey-patching logic
        "e983ae2da073_initial_schema.py",  # Has its own safe_create_table/index logic
        "09d43dbe55f0_composite_indexes_for_reporting.py",  # Has its own _safe_index logic
    }

    violations = []
    for filepath in versions_dir.glob("*.py"):
        if filepath.name in allowed_files:
            continue
        content = filepath.read_text()
        # Extract only the upgrade function
        upgrade_match = re.search(r'def upgrade\(\) -> None:(.*?)(?:\n\ndef |\n# ###)', content, re.DOTALL)
        if not upgrade_match:
            continue
        upgrade_body = upgrade_match.group(1)
        for pattern in forbidden_patterns:
            if re.search(pattern, upgrade_body):
                violations.append(f"{filepath.name}: uses {pattern} in upgrade()")

    assert not violations, f"Found raw drop operations in upgrade() functions:\n" + "\n".join(violations)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])