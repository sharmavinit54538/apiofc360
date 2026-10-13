"""Service layer for AI Chat Assistant."""

from __future__ import annotations

import logging
import time
import uuid
import json
import asyncio
import re
from datetime import datetime
from typing import Annotated, AsyncGenerator, Any

from fastapi import Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import (
    ProgrammingError,
    IntegrityError,
    OperationalError,
    DBAPIError,
)

from app.core.config import settings
from app.core.exceptions import NotFoundException, LLMUnavailableError
from app.db.database import get_db_session
from app.models.ai import AIConversation, AIMessage
from app.models.employee import Employee
from app.models.department import Department
from app.models.recruitment import Job
from app.schemas.ai import ChatResponse, ConversationDetail, ConversationSummary
from app.services.ollama_client import ollama_client

logger = logging.getLogger(__name__)

ASSISTANT_NAME = "OFC HR AI"

# Simple in-memory cache with TTL support
class MemoryCache:
    def __init__(self):
        self._cache = {}
        
    def get(self, key: str) -> Any:
        entry = self._cache.get(key)
        if entry:
            val, expires = entry
            if expires is None or time.time() < expires:
                return val
            else:
                del self._cache[key]
        return None
        
    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        expires = time.time() + ttl if ttl is not None else None
        self._cache[key] = (value, expires)
        
    def delete(self, key: str) -> None:
        self._cache.pop(key, None)
        
    def clear(self) -> None:
        self._cache.clear()

ai_cache = MemoryCache()


# ─── ALLOWED_TABLES Whitelist ──────────────────────────────────────────────
# Each table defines: allowed columns, blocklisted columns, whether it has company_id/is_deleted,
# and few-shot examples for the SQL generator.
ALLOWED_TABLES: dict[str, dict] = {
    "employees": {
        "columns": [
            "id", "user_id", "company_id", "employee_id", "first_name", "last_name",
            "profile_photo_url", "gender", "date_of_birth", "personal_email", "company_email",
            "phone", "alternate_phone", "blood_group", "marital_status", "middle_name",
            "father_name", "mother_name", "spouse_name", "nationality", "preferred_language",
            "aadhaar_number", "passport_number", "driving_license", "voter_id", "tax_regime",
            "upi_id", "esic_number", "work_mode", "business_unit", "employee_category",
            "probation_period_months", "onboarding_data", "employee_onboarding_completed",
            "employee_onboarding_step", "face_embedding", "is_face_enrolled", "face_enrolled_at",
            "department", "designation", "team", "reporting_manager_id", "manager_id",
            "branch", "work_location", "employment_type", "employment_status", "joining_date",
            "probation_end_date", "shift", "shift_id", "employee_capacity", "cost_center_id",
            "ctc", "basic_salary", "hra", "bonus", "pf", "esi", "professional_tax",
            "pan_number", "uan_number", "pf_number", "esi_number",
            "role", "leave_group", "status", "role_metadata", "verification_status",
            "is_active", "deactivated_at", "deactivated_by", "deactivation_reason",
            "activation_token", "activation_token_expires_at", "invited_at", "invited_by",
            "is_deleted", "deleted_at", "created_by", "created_at", "updated_at",
            "department_id",
        ],
        "blocklist": {
            "password_hash", "password", "token", "activation_token", "aadhaar_number",
            "pan_number", "uan_number", "pf_number", "esi_number", "bank_account",
        },
        "has_company_id": True,
        "has_is_deleted": True,
        "few_shots": [
            {
                "q": "Show all active employees",
                "sql": "SELECT id, employee_id, first_name, last_name, department, designation, employment_status, joining_date FROM employees WHERE is_deleted = false AND status = 'ACTIVE' LIMIT 50;"
            },
            {
                "q": "Show employees in Engineering department",
                "sql": "SELECT id, employee_id, first_name, last_name, department, designation, joining_date FROM employees WHERE is_deleted = false AND department ILIKE '%engineering%' LIMIT 50;"
            },
            {
                "q": "How many employees joined this month",
                "sql": "SELECT count(*) FROM employees WHERE is_deleted = false AND joining_date >= date_trunc('month', current_date) AND joining_date < date_trunc('month', current_date) + interval '1 month';"
            },
        ],
    },
    "departments": {
        "columns": [
            "id", "company_id", "department_code", "department_name", "normalized_code",
            "normalized_name", "description", "manager_id", "parent_department_id",
            "branch_id", "location", "cost_center", "budget", "extension_number",
            "employee_capacity", "status", "is_deleted", "deleted_at", "created_by",
            "created_at", "updated_at",
        ],
        "blocklist": set(),
        "has_company_id": True,
        "has_is_deleted": True,
        "few_shots": [
            {
                "q": "Show all departments",
                "sql": "SELECT id, department_code, department_name, description, status FROM departments WHERE is_deleted = false ORDER BY department_name LIMIT 50;"
            },
        ],
    },
    "jobs": {
        "columns": [
            "id", "company_id", "title", "slug", "department", "designation",
            "employment_type", "experience_required", "min_experience", "max_experience",
            "min_salary", "max_salary", "location", "vacancies", "job_description",
            "responsibilities", "requirements", "benefits", "application_deadline",
            "interview_process_description", "status", "is_deleted", "deleted_at",
            "created_by", "created_at", "updated_at",
        ],
        "blocklist": set(),
        "has_company_id": True,
        "has_is_deleted": True,
        "few_shots": [
            {
                "q": "Show open job positions",
                "sql": "SELECT id, title, department, location, vacancies, min_salary, max_salary FROM jobs WHERE is_deleted = false AND status = 'PUBLISHED' LIMIT 50;"
            },
        ],
    },
    "leave_requests": {
        "columns": [
            "id", "employee_id", "leave_type", "start_date", "end_date", "total_days",
            "reason", "status", "approved_by_id", "rejection_reason", "reviewed_by_id",
            "reviewed_at", "created_at", "updated_at",
        ],
        "blocklist": set(),
        "has_company_id": False,
        "has_is_deleted": False,
        "few_shots": [
            {
                "q": "Show employees on leave this month",
                "sql": "SELECT lr.id, lr.employee_id, lr.leave_type, lr.start_date, lr.end_date, lr.status FROM leave_requests lr WHERE lr.start_date >= date_trunc('month', current_date) AND lr.start_date < date_trunc('month', current_date) + interval '1 month' AND lr.status = 'APPROVED' LIMIT 50;"
            },
        ],
    },
    "attendance": {
        "columns": [
            "id", "employee_id", "date", "check_in_time", "check_out_time",
            "status", "source", "confidence", "remarks", "marked_by", "created_at", "updated_at",
        ],
        "blocklist": set(),
        "has_company_id": False,
        "has_is_deleted": False,
        "few_shots": [
            {
                "q": "Show attendance today",
                "sql": "SELECT a.employee_id, a.check_in_time, a.check_out_time, a.status FROM attendance a WHERE a.date = current_date ORDER BY a.employee_id LIMIT 50;"
            },
        ],
    },
    "payslips": {
        "columns": [
            "id", "company_id", "payroll_run_id", "employee_id", "salary_structure_id",
            "payslip_number", "period_month", "period_year", "total_days_in_month",
            "paid_days", "lop_days", "basic", "hra", "conveyance", "special_allowance",
            "other_allowances_total", "arrears", "bonus", "lop_deduction", "gross_earnings",
            "employee_pf", "employer_pf", "employee_esi", "employer_esi", "professional_tax",
            "tds", "other_deductions", "total_deductions", "net_pay", "net_pay_words",
            "payment_status", "payment_date", "payment_reference", "pdf_path", "generated_at",
            "email_status", "email_sent_at", "download_count", "view_count", "created_at", "updated_at",
        ],
        "blocklist": {
            "bank_account", "pan_number", "aadhaar_number",
        },
        "has_company_id": True,
        "has_is_deleted": False,
        "few_shots": [
            {
                "q": "Show payroll summary for current month",
                "sql": "SELECT p.employee_id, p.basic, p.hra, p.gross_earnings, p.total_deductions, p.net_pay FROM payslips p WHERE p.period_month = extract(month from current_date) AND p.period_year = extract(year from current_date) LIMIT 50;"
            },
        ],
    },
    "payroll_runs": {
        "columns": [
            "id", "company_id", "period_id", "run_number", "period_month", "period_year",
            "status", "total_employees", "total_gross", "total_deductions", "total_net",
            "validation_status", "is_locked", "run_by", "run_at", "approved_by", "approved_at",
            "finalized_by", "finalized_at", "paid_at", "created_at", "updated_at",
        ],
        "blocklist": set(),
        "has_company_id": True,
        "has_is_deleted": False,
        "few_shots": [
            {
                "q": "Show latest payroll run",
                "sql": "SELECT * FROM payroll_runs WHERE company_id = '{company_id}' ORDER BY period_year DESC, period_month DESC LIMIT 1;"
            },
        ],
    },
    "salary_structures": {
        "columns": [
            "id", "company_id", "employee_id", "annual_ctc", "basic_monthly", "hra_monthly",
            "conveyance_monthly", "special_allowance_monthly", "other_allowances", "annual_bonus",
            "is_metro_city", "rent_paid_monthly", "tax_regime", "effective_from", "effective_to",
            "is_active", "created_by", "created_at", "updated_at",
        ],
        "blocklist": set(),
        "has_company_id": True,
        "has_is_deleted": False,
        "few_shots": [
            {
                "q": "Show average CTC by department",
                "sql": "SELECT e.department, avg(ss.annual_ctc) as avg_ctc FROM salary_structures ss JOIN employees e ON ss.employee_id = e.id WHERE ss.is_active = true AND e.is_deleted = false GROUP BY e.department ORDER BY avg_ctc DESC LIMIT 50;"
            },
        ],
    },
}


class DBSchemaCache:
    """Dynamic DB Schema Cache with 10 minutes (600s) TTL."""
    def __init__(self, ttl: int = 600):
        self.ttl = ttl
        self.last_loaded = 0
        self.tables: dict[str, list[dict]] = {}

    async def get_schema_description(self, db: AsyncSession) -> str:
        current_time = time.time()
        if not self.tables or (current_time - self.last_loaded > self.ttl):
            try:
                await self.load_schema(db)
            except Exception as e:
                logger.error("Failed to load DB schema dynamically: %s", e)
                if not self.tables:
                    return self.get_fallback_schema_description()
        
        desc = "ACTUAL DATABASE SCHEMA (Do NOT invent tables or columns):\n"
        for table_name, columns in self.tables.items():
            desc += f"- {table_name} (\n"
            for col in columns:
                desc += f"    {col['column_name']} {col['data_type']},\n"
            desc += ")\n"
        
        # Add few-shot examples
        desc += "\n--- FEW-SHOT EXAMPLES ---\n"
        for table_name, config in ALLOWED_TABLES.items():
            if table_name in self.tables:
                for fs in config.get("few_shots", []):
                    desc += f"-- Q: {fs['q']}\n{fs['sql']}\n\n"
        return desc

    async def load_schema(self, db: AsyncSession):
        from sqlalchemy import text
        
        tables_query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """
        res_tables = await db.execute(text(tables_query))
        table_names = [row[0] for row in res_tables.all()]
        
        new_tables = {}
        for table in table_names:
            if table not in ALLOWED_TABLES:
                continue
                
            columns_query = f"""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = 'public' AND table_name = '{table}'
            """
            res_cols = await db.execute(text(columns_query))
            cols = [{"column_name": r[0], "data_type": r[1]} for r in res_cols.all()]
            
            # Filter out blocklisted columns
            allowed_cols = [c for c in cols if c["column_name"] not in ALLOWED_TABLES[table].get("blocklist", set())]
            new_tables[table] = allowed_cols
            
        if new_tables:
            self.tables = new_tables
            self.last_loaded = time.time()
            logger.info("Successfully loaded database schema dynamically: %s", list(self.tables.keys()))

    def get_fallback_schema_description(self) -> str:
        desc = "ACTUAL DATABASE SCHEMA (Do NOT invent tables or columns):\n"
        for table_name, config in ALLOWED_TABLES.items():
            desc += f"- {table_name} (\n"
            for col in config["columns"]:
                if col not in config.get("blocklist", set()):
                    desc += f"    {col} <type>,\n"
            desc += ")\n"
        return desc


schema_cache = DBSchemaCache()


def validate_sql_query(sql: str, schema: dict) -> tuple[bool, str]:
    """Validates a generated SQL query using sqlglot (PostgreSQL dialect).
    
    Rules:
    - Exactly one statement, root SELECT only
    - No DML/DDL (INSERT, UPDATE, DELETE, CREATE, DROP, ALTER, TRUNCATE, GRANT, REVOKE)
    - No dangerous functions (pg_sleep, pg_read_file, set_config, dblink, lo_*)
    - All tables must be in ALLOWED_TABLES
    - All columns must exist and not be blocklisted
    - Must accept EXTRACT, lower(), ::text, FILTER, OVER, UNION, OFFSET
    - Keywords inside string literals are ignored
    """
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError:
        logger.error("sqlglot not installed, falling back to regex validator")
        return _validate_sql_query_regex(sql, schema)
    
    # Parse with PostgreSQL dialect
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
    except Exception as e:
        return False, f"SQL parse error: {e}"
    
    if not parsed:
        return False, "Generated query is empty."
    
    if len(parsed) > 1:
        return False, "Multiple statements are not allowed."
    
    stmt = parsed[0]
    
    # Must be a SELECT statement (or UNION which wraps in SetOperation)
    if not (isinstance(stmt, exp.Select) or isinstance(stmt, exp.SetOperation)):
        return False, "Only SELECT statements are permitted."
    
    # For SetOperation (UNION), check all sub-statements are SELECT
    if isinstance(stmt, exp.SetOperation):
        for sub_stmt in stmt.flatten():
            if not isinstance(sub_stmt, exp.Select):
                return False, "UNION components must be SELECT statements."
    
    # Check for forbidden statement types - use string names to handle version differences
    forbidden_type_names = {"Insert", "Update", "Delete", "Create", "Drop", "Alter", "Truncate", "Grant", "Revoke", "Copy", "Vacuum"}
    for node in stmt.walk():
        if type(node).__name__ in forbidden_type_names:
            return False, f"Dangerous SQL operation detected: {type(node).__name__} is strictly prohibited."
    
    # Check for dangerous functions
    dangerous_funcs = {"pg_sleep", "pg_read_file", "set_config", "dblink", "lo_import", "lo_export", "lo_create", "lo_unlink"}
    for func in stmt.find_all(exp.Anonymous):
        if func.this.lower() in dangerous_funcs:
            return False, f"Dangerous function '{func.this}' is not allowed."
    
    # Handle UNION queries by validating each sub-query separately
    def _validate_select(select_stmt, schema):
        """Validate a single SELECT statement."""
        # Collect tables in this sub-query
        sub_referenced_tables = set()
        for table in select_stmt.find_all(exp.Table):
            table_name = table.name.lower()
            if table_name:
                sub_referenced_tables.add(table_name)
        
        if not sub_referenced_tables:
            return False, "No tables referenced in the query."
        
        # Verify all tables are allowed
        for table_name in sub_referenced_tables:
            if table_name not in ALLOWED_TABLES:
                return False, f"Table '{table_name}' is not allowed. Allowed tables: {', '.join(ALLOWED_TABLES.keys())}"
        
        # Verify columns
        for column in select_stmt.find_all(exp.Column):
            col_name = column.name.lower()
            table_name = column.table.lower() if column.table else None
            
            # If column is qualified with table name, check against that table
            if table_name and table_name in ALLOWED_TABLES:
                target_tables = {table_name}
            else:
                # Unqualified column - check against all tables in this sub-query
                target_tables = sub_referenced_tables
            
            for target_table in target_tables:
                if target_table not in ALLOWED_TABLES:
                    continue
                
                # Use schema parameter if provided, otherwise fall back to ALLOWED_TABLES
                if schema and target_table in schema:
                    allowed_cols = {c["column_name"].lower() for c in schema[target_table] if isinstance(c, dict) and "column_name" in c}
                    # Also handle case where schema has simple column names
                    if not allowed_cols:
                        allowed_cols = {c.lower() for c in schema[target_table] if isinstance(c, str)}
                else:
                    allowed_cols = {c.lower() for c in ALLOWED_TABLES[target_table]["columns"]}
                
                blocklist = {c.lower() for c in ALLOWED_TABLES[target_table].get("blocklist", set())}
                
                if col_name in blocklist:
                    return False, f"Column '{col_name}' is blocklisted in table '{target_table}'."
                
                if col_name and col_name not in allowed_cols:
                    # Allow sqlglot-generated pseudo-columns like ROW_NUMBER, etc.
                    if col_name not in {"row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile"}:
                        return False, f"Column '{col_name}' does not exist in table '{target_table}'."
        
        return True, "Valid SQL query."
    
    # For UNION, validate each sub-query separately
    if isinstance(stmt, exp.SetOperation):
        for sub_stmt in stmt.flatten():
            is_valid, msg = _validate_select(sub_stmt, schema)
            if not is_valid:
                return False, msg
        return True, "Valid SQL query."
    
    # For regular SELECT, collect all tables
    referenced_tables = set()
    for table in stmt.find_all(exp.Table):
        table_name = table.name.lower()
        if table_name:
            referenced_tables.add(table_name)
    
    if not referenced_tables:
        return False, "No tables referenced in the query."
    
    # Verify all tables are allowed
    for table_name in referenced_tables:
        if table_name not in ALLOWED_TABLES:
            return False, f"Table '{table_name}' is not allowed. Allowed tables: {', '.join(ALLOWED_TABLES.keys())}"
    
    # Verify columns
    for column in stmt.find_all(exp.Column):
        col_name = column.name.lower()
        table_name = column.table.lower() if column.table else None
        
        # If column is qualified with table name, check against that table
        if table_name and table_name in ALLOWED_TABLES:
            target_tables = {table_name}
        else:
            # Unqualified column - check against all referenced tables
            target_tables = referenced_tables
        
        for target_table in target_tables:
            if target_table not in ALLOWED_TABLES:
                continue
            
            # Use schema parameter if provided, otherwise fall back to ALLOWED_TABLES
            if schema and target_table in schema:
                allowed_cols = {c["column_name"].lower() for c in schema[target_table] if isinstance(c, dict) and "column_name" in c}
                # Also handle case where schema has simple column names
                if not allowed_cols:
                    allowed_cols = {c.lower() for c in schema[target_table] if isinstance(c, str)}
            else:
                allowed_cols = {c.lower() for c in ALLOWED_TABLES[target_table]["columns"]}
            
            blocklist = {c.lower() for c in ALLOWED_TABLES[target_table].get("blocklist", set())}
            
            if col_name in blocklist:
                return False, f"Column '{col_name}' is blocklisted in table '{target_table}'."
            
            if col_name and col_name not in allowed_cols:
                # Allow sqlglot-generated pseudo-columns like ROW_NUMBER, etc.
                if col_name not in {"row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile"}:
                    return False, f"Column '{col_name}' does not exist in table '{target_table}'."
    
    return True, "Valid SQL query."


def _validate_sql_query_regex(sql: str, schema: dict) -> tuple[bool, str]:
    """Fallback regex-based validator (kept for compatibility)."""
    # Strip SQL comments
    q_clean = re.sub(r'--.*', '', sql)
    q_clean = re.sub(r'/\*.*?\*/', '', q_clean, flags=re.DOTALL)
    q_clean = q_clean.strip().strip(";").strip()
    
    if not q_clean:
        return False, "Generated query is empty."
        
    dangerous_keywords = {"drop", "delete", "truncate", "alter", "update", "insert", "create", "grant", "revoke"}
    words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', q_clean.lower())
    for word in words:
        if word in dangerous_keywords:
            return False, f"Dangerous SQL keyword detected: '{word.upper()}' is strictly prohibited."
            
    if not q_clean.lower().startswith("select"):
        return False, f"Dangerous query blocked. Only safe SELECT queries are permitted. Query started with: {q_clean[:20]}"
    
    return True, "Valid SQL query (regex fallback)."


def rewrite_sql_for_tenant(sql: str, company_id: uuid.UUID | None, is_super_admin: bool, role: str, max_rows: int = 100) -> str:
    """Rewrite validated SQL to enforce tenant isolation and limits.
    
    - Adds company_id = :company_id AND is_deleted = false to all ALLOWED_TABLES that support it
    - Enforces LIMIT max_rows (default 100)
    - Uses bound parameter for company_id (never formats into SQL)
    - Raises if company_id is required but missing and user is not super_admin
    """
    import sqlglot
    from sqlglot import exp
    
    if not company_id and not is_super_admin:
        raise ValueError("Company ID required for tenant isolation unless super_admin")
    
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
        if not parsed:
            return sql
        stmt = parsed[0]
    except Exception:
        # If parsing fails, return original (should not happen after validation)
        return sql
    
    # Find all table references
    for table in stmt.find_all(exp.Table):
        table_name = table.name.lower()
        if table_name in ALLOWED_TABLES:
            config = ALLOWED_TABLES[table_name]
            
            # Add company_id filter if table supports it and we have a company_id
            if config.get("has_company_id") and company_id:
                # Create a WHERE condition: table.company_id = :company_id
                company_id_param = exp.Placeholder(this="company_id")
                company_id_cond = exp.EQ(
                    this=exp.Column(this=exp.Identifier(this="company_id"), table=exp.Identifier(this=table_name)),
                    expression=company_id_param,
                )
                
                # Add is_deleted = false if table supports it
                if config.get("has_is_deleted"):
                    is_deleted_cond = exp.EQ(
                        this=exp.Column(this=exp.Identifier(this="is_deleted"), table=exp.Identifier(this=table_name)),
                        expression=exp.false(),
                    )
                    combined_cond = exp.And(this=company_id_cond, expression=is_deleted_cond)
                else:
                    combined_cond = company_id_cond
                
                # Add to WHERE clause
                if stmt.args.get("where"):
                    existing_where = stmt.args["where"]
                    stmt.set("where", exp.Where(this=exp.And(this=existing_where.this, expression=combined_cond)))
                else:
                    stmt.set("where", exp.Where(this=combined_cond))
    
    # Enforce LIMIT
    if max_rows > 0:
        # Remove existing LIMIT
        stmt = stmt.transform(
            lambda node: None if isinstance(node, exp.Limit) else node,
            copy=False,
        )
        # Add new LIMIT
        stmt = stmt.limit(max_rows)
    
    return stmt.sql(dialect="postgres")


def get_read_only_session(db: AsyncSession, timeout_seconds: int):
    """Create a read-only session with statement timeout."""
    from sqlalchemy import text
    async def _setup(conn):
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        await conn.execute(text(f"SET LOCAL statement_timeout = {timeout_seconds * 1000}"))
    return _setup


def build_sql_prompt(company_id: uuid.UUID | None, history_text: str, query: str) -> str:
    """Single prompt builder used for both first attempt and repair retry."""
    schema_desc = schema_cache.get_fallback_schema_description()  # Will be replaced with dynamic
    return (
        f"{schema_desc}\n\n"
        + SQL_GEN_PROMPT.format(
            company_id=str(company_id) if company_id else "",
            history_text=history_text,
            query=query
        )
    )


async def _execute_sql_loop(
    self,
    message: str,
    company_id: uuid.UUID | None,
    conversation_id: uuid.UUID,
    claims: dict,
    schema_desc: str,
    max_retries: int = 3,
) -> tuple[str, str]:
    """Shared SQL generate/validate/execute/repair loop.
    
    Returns:
        tuple: (results_json, generated_sql)
    
    Raises:
        LLMUnavailableError: If LLM is unavailable
        ValueError: If SQL validation fails after retries
        Exception: If database execution fails after retries
    """
    sql_error = None
    retry_count = 0
    generated_sql = ""
    results_json = "[]"
    
    while retry_count < max_retries:
        history_text = await self._compile_history(conversation_id)
        
        if sql_error:
            prompt = (
                f"Your previously generated SQL was invalid:\n"
                f"SQL: {generated_sql}\n"
                f"ERROR: {sql_error}\n"
                f"Please generate a CORRECT PostgreSQL query using ONLY correct columns from the schema:\n\n"
                f"{schema_desc}\n\n"
                f"USER QUESTION: {message}\n"
                f"Corrected SQL:"
            )
        else:
            prompt = build_sql_prompt(company_id, history_text, message)
        
        try:
            raw_sql = await ollama_client.generate_completion(
                prompt=prompt,
                system_prompt=SQL_SYSTEM_PROMPT,
                model=settings.AI_SQL_MODEL
            )
            generated_sql = clean_generated_sql(raw_sql)
        except LLMUnavailableError as llm_exc:
            logger.error("LLM unavailable during SQL generation: %s", llm_exc)
            raise
        except Exception as exc:
            logger.error("SQL generation failed: %s", exc)
            sql_error = f"Ollama model generation error: {str(exc)}"
            retry_count += 1
            continue
        
        # Validate SQL
        is_valid, err_msg = validate_sql_query(generated_sql, self.schema_cache.tables)
        if not is_valid:
            sql_error = err_msg
            retry_count += 1
            continue
        
        # Execute SQL with tenant isolation
        try:
            from sqlalchemy import text
            
            user_role = claims.get("role", "")
            is_super_admin = user_role.lower() in {"super_admin", "SUPER_ADMIN"} or claims.get("is_super_admin", False)
            
            rewritten_sql = rewrite_sql_for_tenant(
                generated_sql,
                company_id=company_id,
                is_super_admin=is_super_admin,
                role=user_role,
                max_rows=100
            )
            
            # Set up read-only transaction with timeout
            sql_timeout = getattr(settings, "AI_SQL_TIMEOUT_SECONDS", 30)
            await self.db.execute(text("SET TRANSACTION READ ONLY"))
            await self.db.execute(text(f"SET LOCAL statement_timeout = {sql_timeout * 1000}"))
            
            # Execute with bound parameter for company_id
            result = await self.db.execute(
                text(rewritten_sql),
                {"company_id": str(company_id)} if company_id else {}
            )
            if result.returns_rows:
                rows = result.mappings().all()
                
                from decimal import Decimal
                from datetime import date
                class CustomEncoder(json.JSONEncoder):
                    def default(self, obj):
                        if isinstance(obj, (Decimal, float)):
                            return float(obj)
                        if isinstance(obj, (date, datetime)):
                            return obj.isoformat()
                        if isinstance(obj, uuid.UUID):
                            return str(obj)
                        return super().default(obj)
                
                cleaned_rows = [clean_row_data(dict(row), claims.get("role")) for row in rows]
                if cleaned_rows:
                    results_json = json.dumps(cleaned_rows, cls=CustomEncoder, indent=2)
                else:
                    results_json = "No matching records found in the database."
            else:
                results_json = "Query executed successfully, but returned no rows."
            
            # Success
            return results_json, generated_sql
        except Exception as sql_exc:
            await self.db.rollback()
            logger.error("SQL query execution failed: %s. SQL: %s", sql_exc, rewritten_sql if 'rewritten_sql' in locals() else generated_sql)
            sql_error = map_db_exception(sql_exc)
            retry_count += 1
    
    # If we exhausted retries
    raise ValueError(f"SQL repair loop exhausted: {sql_error}")


SYSTEM_PROMPT = """You are OFC HR AI, the advanced workforce intelligence assistant for Office Function Consolidator – Human Resources.
You help HR managers, leaders, and employees query organizational statistics, department details, payroll insights, and general HR queries.
You have direct, read-only access to the company's real-time database facts.

Use the provided database facts to ground your response. Avoid any fake or fabricated names, numbers, or details.
If the database facts are empty or do not answer the user's specific query, answer using general HR knowledge or politely explain what details you can see.

Formatting guidelines:
- Present lists, tabular details, and metrics using Markdown tables where possible.
- Use bold text for key figures or highlights.
- Keep the tone professional, helpful, and concise.
"""

USER_TEMPLATE = """DATABASE FACTS FOR THIS COMPANY:
- Total Active Employees: {total_employees}
- Registered Departments: {departments}
- Employees Hired This Month: {recent_hires}
- Active Open Job Openings: {open_jobs}
{matched_employee_text}

CONVERSATION HISTORY:
{history_text}

USER MESSAGE:
{user_message}

Answer:"""


SQL_GEN_PROMPT = """You are a PostgreSQL SQL generator. Generate ONLY a single valid raw SQL query to query the tables.
Do NOT output any explanation. Do NOT wrap the query in markdown code blocks like ```sql. Just output raw SQL.

CONSTRAINTS:
1. Return records where is_deleted = False.
2. Use ILIKE with wildcards (e.g., %keyword%) for any partial string matching.
3. If company_id is provided, filter by company_id = '{company_id}'.
4. Always add LIMIT 50 to the query.
5. Do NOT use SELECT *; only select required fields to answer the question.
6. For listing queries (e.g. 'Show all employees' or 'Show departments'), select all matching rows. Do NOT restrict to LIMIT 1 unless explicitly requested for a single record.
7. Never expose columns like password, password_hash, token, created_by, updated_at, deleted_at, activation_token, company_id, internal ids.

CONVERSATION HISTORY:
{history_text}

USER QUESTION: {query}
SQL Query:"""


SQL_SYSTEM_PROMPT = (
    "You are a PostgreSQL SQL generator. You must output ONLY a valid SQL SELECT statement. "
    "Do NOT include any introduction, formatting code blocks, markdown wrapper, greeting, explanation, "
    "or conversational filler. Start your response directly with the SELECT keyword."
)


ANSWER_FORMAT_PROMPT = """You are OFC HR AI, an advanced workforce intelligence assistant for Office Function Consolidator – Human Resources.
Your task is to present the following database query results to the user.

USER QUERY: {query}
DATABASE RESULTS (JSON):
{results_json}

INSTRUCTIONS:
- Format the results using professional Markdown tables, lists, or summary cards.
- Be professional, friendly, helpful, short, and accurate.
- Do not explain SQL or database query details; just answer the user's question directly.
- Never output raw JSON, dict structures, or lists of JSON.
- If no results are returned, politely explain that no matching records were found in the database.
- Do not expose any database schema or table IDs.
"""


def classify_intent_fast(message: str) -> str:
    """Classify user intent using word-boundary matching and Hinglish support.
    
    Returns one of: Greeting, Goodbye, Help, Payroll, Attendance, Leave,
    Employee Search, Department, Report, Analytics, Database Query, Unknown
    """
    import re
    msg = message.strip().lower()
    
    # Tokenize with word boundaries (including Hinglish words)
    tokens = set(re.findall(r'\b[\w\']+\b', msg))
    
    # 1. Greetings - exact matches only for short messages
    greetings = {
        "hi", "hii", "hiii", "hello", "hlo", "hey", "heyy", "hey there",
        "good morning", "good afternoon", "good evening", "g'day",
        "thanks", "thank you", "thank u", "thx",
        "namaste", "namaskar", "pranam",  # Hinglish greetings
    }
    
    if msg in greetings or (len(tokens) <= 2 and any(t in greetings for t in tokens)):
        return "Greeting"
    
    # 2. Who are you / How can you help - phrase matching
    who_are_you_phrases = [
        "who are you", "who are u", "what are you", "your name",
        "how can you help", "how can u help", "what can you do", "what can u do",
        "tum kaun ho", "aap kaun ho", "kaun ho tum",  # Hinglish
    ]
    if any(p in msg for p in who_are_you_phrases) and len(tokens) <= 8:
        return "Greeting"
    
    # 3. Goodbye
    goodbyes = {
        "bye", "goodbye", "see ya", "see you", "see u", "farewell", "quit", "exit",
        "alvida", "chalta hoon", "phir milenge",  # Hinglish
    }
    if msg in goodbyes or (len(tokens) <= 2 and any(t in goodbyes for t in tokens)):
        return "Goodbye"
    
    # 4. Help
    help_words = {"help", "commands", "features", "guide", "madad", "sahayata"}  # Hinglish
    if msg in help_words or (len(tokens) == 1 and next(iter(tokens)) in help_words):
        return "Help"
    
    # 5. Domain keywords with word-boundary matching
    # Hinglish variants included
    payroll_keywords = {
        "payroll", "salary", "ctc", "pay", "compensation", "payslip",
        "kitni salary", "kitna salary", "salary kitni", "ctc kitna",
        "pay kitna", "payslip chahiye", "salary details",
    }
    attendance_keywords = {
        "attendance", "checkin", "checkout", "present", "absent", "working hours", "late", "shift",
        "aaj attendance", "aaj ki attendance", "attendance today", "check in", "check out",
        "present kaun", "absent kaun", "late kaun",
    }
    leave_keywords = {
        "leave", "leaves", "vacation", "holiday", "holidays", "time off",
        "chutti", "chuttiyan", "leave balance", "kitni chutti",
    }
    employee_keywords = {
        "employee", "employees", "staff", "member", "members", "personnel", "hire", "hired", "join", "joining",
        "kitne employee", "kitne employees", "employee kitne", "staff kitna",
        "employee list", "staff list", "new hire", "new joiner",
    }
    department_keywords = {
        "department", "departments", "dept", "depts", "branch",
        "department kitne", "departments list", "dept list",
    }
    analytics_keywords = {
        "analytics", "chart", "graph", "metric", "metrics", "stats", "statistics", "insight", "insights",
        "report", "reports", "summary", "dashboard", "visualize",
    }
    
    # Check with word-boundary matching (for multi-word phrases) and token matching (for single words)
    def has_keyword(keywords: set[str]) -> bool:
        for kw in keywords:
            if ' ' in kw:
                # Multi-word phrase - check as substring
                if kw in msg:
                    return True
            else:
                # Single word - check token boundary
                if kw in tokens:
                    return True
        return False
    
    if has_keyword(payroll_keywords):
        return "Payroll"
    if has_keyword(attendance_keywords):
        return "Attendance"
    if has_keyword(leave_keywords):
        return "Leave"
    if has_keyword(department_keywords):
        return "Department"
    if has_keyword(employee_keywords):
        return "Employee Search"
    if has_keyword(analytics_keywords):
        return "Analytics"
    
    # 6. Database query indicators
    db_indicators = {
        "show", "list", "select", "find", "search", "who is", "who are", "get", "display", "retrieve", "how many", "count",
        "dikhao", "batao", "kitne", "kaun", "kya",  # Hinglish query words
    }
    if has_keyword(db_indicators):
        return "Database Query"
    
    return "Unknown"


def clean_row_data(row_dict: dict, role: str | None = None) -> dict:
    """Strips sensitive columns, UUIDs, tokens, and system metadata from db results.
    
    Role-based filtering:
    - Salary/CTC columns (ctc, basic_salary, hra, bonus, pf, esi, professional_tax, 
      pan_number, uan_number, pf_number, esi_number) are only shown to HR/admin roles
    - PII columns (aadhaar_number, pan_number, etc.) are always stripped
    """
    # Always excluded keys (system metadata, PII, tokens)
    excluded_keys = {
        "id", "company_id", "created_by", "deleted_at", "updated_at",
        "activation_token", "activation_token_expires_at", "invited_by", "invited_at",
        "is_deleted", "password_hash", "password", "token", "token_expires_at",
        "department_id", "user_id", "reporting_manager_id",
        # PII - always blocked
        "aadhaar_number", "pan_number", "uan_number", "pf_number", "esi_number",
        "bank_account", "passport_number", "driving_license", "voter_id",
    }
    
    # Role-based exclusions: salary/CTC only for HR/admin/super_admin
    is_hr_admin = role and role.lower() in {"hr_admin", "hr_manager", "admin", "super_admin", "super_admin"}
    if not is_hr_admin:
        excluded_keys.update({
            "ctc", "basic_salary", "hra", "bonus", "pf", "esi", "professional_tax",
            "pf_number", "esi_number",  # duplicate but explicit
        })
    
    return {k: v for k, v in row_dict.items() if k not in excluded_keys}


def find_statement_semicolon(s: str) -> int:
    in_quotes = False
    for i, char in enumerate(s):
        if char == "'":
            in_quotes = not in_quotes
        elif char == ";" and not in_quotes:
            return i
    return -1


def clean_generated_sql(sql: str) -> str:
    cleaned = sql.strip()
    # 1. Remove markdown code block wraps first
    code_block_match = re.search(r"```(?:sql)?\s*(select\s+.*?)(?:```|$)", cleaned, re.IGNORECASE | re.DOTALL)
    if code_block_match:
        cleaned = code_block_match.group(1).strip()
    else:
        # Find SELECT and slice from it
        select_idx = cleaned.lower().find("select")
        if select_idx != -1:
            cleaned = cleaned[select_idx:].strip()
            
    # Find statement-terminating semicolon
    semi_idx = find_statement_semicolon(cleaned)
    if semi_idx != -1:
        after_semi = cleaned[semi_idx + 1:].strip()
        # If the trailing text has no SELECT, slice up to the semicolon
        if not re.search(r"\bselect\b", after_semi, re.IGNORECASE):
            cleaned = cleaned[:semi_idx]
            
    return cleaned.strip().rstrip(";")


class AIService:
    """Orchestrates AI chat history, data grounding, and local Ollama inference."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.schema_cache = schema_cache

    async def get_history(self, user_id: uuid.UUID) -> list[ConversationSummary]:
        """Fetch all conversations for a user, ordered by last updated."""
        try:
            stmt = select(AIConversation).where(
                AIConversation.user_id == user_id
            ).order_by(AIConversation.updated_at.desc())
            
            result = await self.db.execute(stmt)
            conversations = result.scalars().all()
            return [ConversationSummary.model_validate(c) for c in conversations]
        except Exception:
            await self.db.rollback()
            raise

    async def get_conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> ConversationDetail:
        """Fetch complete message history for a specific conversation."""
        from sqlalchemy.orm import selectinload
        try:
            stmt = select(AIConversation).options(
                selectinload(AIConversation.messages)
            ).where(
                AIConversation.id == conversation_id,
                AIConversation.user_id == user_id
            )
            result = await self.db.execute(stmt)
            conversation = result.scalar_one_or_none()
            if not conversation:
                raise NotFoundException("Conversation not found or access denied.")
            
            return ConversationDetail.model_validate(conversation)
        except Exception:
            await self.db.rollback()
            raise

    async def rename_conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, title: str
    ) -> ConversationSummary:
        """Rename an existing conversation."""
        try:
            stmt = select(AIConversation).where(
                AIConversation.id == conversation_id,
                AIConversation.user_id == user_id
            )
            result = await self.db.execute(stmt)
            conversation = result.scalar_one_or_none()
            if not conversation:
                raise NotFoundException("Conversation not found or access denied.")
            
            conversation.title = title
            await self.db.commit()
            await self.db.refresh(conversation)
            return ConversationSummary.model_validate(conversation)
        except Exception:
            await self.db.rollback()
            raise

    async def delete_conversation(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        """Delete a conversation and all its messages."""
        try:
            stmt = select(AIConversation).where(
                AIConversation.id == conversation_id,
                AIConversation.user_id == user_id
            )
            result = await self.db.execute(stmt)
            conversation = result.scalar_one_or_none()
            if not conversation:
                raise NotFoundException("Conversation not found or access denied.")
            
            await self.db.delete(conversation)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    async def clear_history(self, user_id: uuid.UUID) -> None:
        """Clear all conversation history for the current user."""
        try:
            stmt = select(AIConversation).where(AIConversation.user_id == user_id)
            result = await self.db.execute(stmt)
            conversations = result.scalars().all()
            for conversation in conversations:
                await self.db.delete(conversation)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    async def get_suggestions(self) -> list[str]:
        """Fetch suggested quick queries dynamically with in-memory caching."""
        cache_key = "default_suggestions"
        cached = ai_cache.get(cache_key)
        if cached is not None:
            return cached
            
        suggestions = [
            "Show employees hired this month",
            "What departments do we have?",
            "How many active employees are registered?",
            "Are there any active job postings?",
        ]
        ai_cache.set(cache_key, suggestions, ttl=300)
        return suggestions

    async def send_message(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID | None,
        message: str,
        conversation_id: uuid.UUID | None = None,
    ) -> ChatResponse:
        """Process chat message, route intent, and generate response (Sync fallback)."""
        start_time = time.perf_counter()
        intent = classify_intent_fast(message)

        try:
            # Fetch or initialize conversation
            conversation = None
            if conversation_id:
                stmt = select(AIConversation).where(
                    AIConversation.id == conversation_id,
                    AIConversation.user_id == user_id
                )
                result = await self.db.execute(stmt)
                conversation = result.scalar_one_or_none()

            if not conversation:
                title = message[:40] + "..." if len(message) > 40 else message
                conversation = AIConversation(
                    user_id=user_id,
                    company_id=company_id,
                    title=title
                )
                self.db.add(conversation)
                await self.db.commit()
                conversation_id = conversation.id
            else:
                conversation_id = conversation.id

            # Save user message immediately to prevent foreign key rollback failures
            user_msg = AIMessage(
                conversation_id=conversation_id,
                role="user",
                message=message
            )
            self.db.add(user_msg)
            await self.db.commit()
        except Exception as db_init_exc:
            await self.db.rollback()
            logger.error("Failed to commit user message context: %s", db_init_exc)
            raise

        response_text = ""
        generated_sql = ""
        rows_returned = 0
        validation_result = "N/A"
        retry_count = 0
        rollback_status = "No transaction modifications"
        tokens_count = "N/A"

        # Greetings mapping check
        is_who_are_you = any(p in message.lower() for p in ["who are you", "who are u", "what are you", "your name"])

        try:
            if is_who_are_you:
                response_text = "I'm OFC HR AI, your HRMS assistant. I can help with employees, payroll, attendance, reports, analytics, onboarding and company information."
            elif intent == "Greeting":
                response_text = "Hello! 👋 I'm OFC HR AI, your enterprise HR assistant. I can help you with employee records, department structures, payroll stats, attendance tracking, leave policies, onboarding details, and analytics. Try asking 'What departments do we have?' or 'Show all active employees'."
            elif intent == "Goodbye":
                response_text = "Goodbye! 👋 Have a wonderful day. Feel free to come back whenever you need help with your workforce."
            elif intent == "Help":
                response_text = (
                    "Hello! I am OFC HR AI, your HRMS assistant. Here are the categories of information you can query:\n\n"
                    "👥 **Employees**\n"
                    "- [Show all active employees](query:Show%20all%20active%20employees)\n"
                    "- [Show employees in Engineering](query:Show%20employees%20in%20Engineering)\n\n"
                    "📅 **Attendance**\n"
                    "- [Attendance today](query:Attendance%20today)\n"
                    "- [List check-ins today](query:List%20check-ins%20today)\n\n"
                    "💰 **Payroll**\n"
                    "- [Payroll summary](query:Payroll%20summary)\n"
                    "- [Average CTC per department](query:Average%20CTC%20per%20department)\n\n"
                    "🌴 **Leave**\n"
                    "- [Employees on leave this month](query:Employees%20on%20leave%20this%20month)\n"
                    "- [Leave policies](query:Leave%20policies)\n\n"
                    "🏢 **Departments**\n"
                    "- [Show departments](query:Show%20departments)\n\n"
                    "👔 **Managers**\n"
                    "- [List company managers](query:List%20company%20managers)\n\n"
                    "📊 **Reports & Analytics**\n"
                    "- [Employees hired this month](query:Employees%20hired%20this%20month)\n"
                    "- [Department headcount report](query:Department%20headcount%20report)"
                )
            elif intent in ("Database Query", "Analytics", "Payroll", "Attendance", "Leave", "Employee Search", "Department", "Report"):
                # Load Schema dynamically
                schema_desc = await self.schema_cache.get_schema_description(self.db)
                
                try:
                    results_json, generated_sql = await self._execute_sql_loop(
                        message=message,
                        company_id=company_id,
                        conversation_id=conversation_id,
                        claims=claims,
                        schema_desc=schema_desc,
                        max_retries=3,
                    )
                except LLMUnavailableError as llm_exc:
                    logger.error("LLM unavailable during SQL generation: %s", llm_exc)
                    return ChatResponse(
                        success=False,
                        conversation_id=conversation_id,
                        response="The AI service is temporarily unavailable. Please try again.",
                        sources=[],
                        suggestions=[],
                    )
                except ValueError as val_exc:
                    logger.error("SQL validation failed after retries: %s", val_exc)
                    response_text = f"I couldn't execute that query because it doesn't match the current database schema. Error: {val_exc}"
                except Exception as exc:
                    logger.error("SQL execution failed: %s", exc)
                    response_text = f"A database error occurred: {map_db_exception(exc)}"
                else:
                    # 4. Format response using LLM
                    format_prompt = ANSWER_FORMAT_PROMPT.format(
                        query=message,
                        results_json=results_json
                    )
                    try:
                        response_text = await ollama_client.generate_completion(
                            prompt=format_prompt,
                            system_prompt=SYSTEM_PROMPT
                        )
                        response_text = response_text.strip()
                    except Exception as exc:
                        logger.error("Response formatting failed: %s", exc)
                        response_text = f"Here are the database results:\n\n```json\n{results_json}\n```"
            else:
                # Fallback for Unknown
                db_facts = await self._gather_database_facts(message, company_id)
                history_text = await self._compile_history(conversation_id)
                user_prompt = USER_TEMPLATE.format(
                    total_employees=db_facts["total_employees"],
                    departments=", ".join(db_facts["departments"]) if db_facts["departments"] else "None",
                    recent_hires="; ".join(db_facts["recent_hires"]) if db_facts["recent_hires"] else "None",
                    open_jobs="; ".join(db_facts["open_jobs"]) if db_facts["open_jobs"] else "None",
                    matched_employee_text=db_facts["matched_employees_text"],
                    history_text=history_text,
                    user_message=message
                )
                try:
                    response_text = await ollama_client.generate_completion(
                        prompt=user_prompt,
                        system_prompt=SYSTEM_PROMPT
                    )
                    response_text = response_text.strip()
                except Exception as exc:
                    logger.error("Fallback completion failed: %s", exc)
                    response_text = self._generate_fallback_response(message, db_facts)

            # Save AI response - Rebind conversation to make sure the session state is clean
            stmt_c = select(AIConversation).where(AIConversation.id == conversation_id)
            res_c = await self.db.execute(stmt_c)
            conversation_obj = res_c.scalar_one_or_none()

            ai_msg = AIMessage(
                conversation_id=conversation_id,
                role="ai",
                message=response_text
            )
            self.db.add(ai_msg)
            if conversation_obj:
                conversation_obj.updated_at = datetime.now()
            await self.db.commit()
            rollback_status = "Committed successfully"
        except Exception as handler_exc:
            await self.db.rollback()
            rollback_status = "Executed exception rollback"
            logger.error("Exception handled inside send_message: %s", handler_exc)
            response_text = "I ran into an internal error while processing your request. Please try again."
        finally:
            await self.db.close()

        total_time = time.perf_counter() - start_time
        logger.info(
            "AI Request Performance Profiler:\n"
            "- User Message: %s\n"
            "- Detected Intent: %s\n"
            "- Generated SQL: %s\n"
            "- Validation Result: %s\n"
            "- Retry Count: %d\n"
            "- Execution Time: %.4fs\n"
            "- Rollback Status: %s\n"
            "- LLM Tokens: %s\n"
            "- LLM Response: %s",
            message, intent, generated_sql, validation_result, retry_count, total_time, rollback_status, tokens_count, response_text
        )

        db_facts = await self._gather_database_facts(message, company_id)
        suggestions = self._generate_dynamic_suggestions(message, db_facts)

        return ChatResponse(
            success=True,
            conversation_id=conversation_id,
            response=response_text,
            sources=["Internal HRMS Database"] if intent not in ("Greeting", "Goodbye", "Help", "Unknown") else [],
            suggestions=suggestions
        )

    async def send_message_stream(
        self,
        user_id: uuid.UUID,
        company_id: uuid.UUID | None,
        message: str,
        conversation_id: uuid.UUID | None = None,
    ) -> AsyncGenerator[str, None]:
        """Process chat message, route intent, and stream Ollama response."""
        start_time = time.perf_counter()
        intent = classify_intent_fast(message)
        
        generated_sql = ""
        rows_returned = 0
        validation_result = "N/A"
        retry_count = 0
        rollback_status = "No transaction modifications"
        tokens_count = "N/A"
        response_text = ""
        request_id = uuid.uuid4().hex[:8]

        def _user_error(event: str, detail: str) -> dict:
            """Generate user-facing error message without exposing internals."""
            messages = {
                "ollama_unreachable": "I'm unable to connect to the AI service. Please try again in a moment.",
                "model_missing": "The AI model is not available. Please contact your administrator.",
                "timeout": "The request took too long to complete. Please try a simpler query.",
                "invalid_sql": "I couldn't understand that query. Please rephrase or try a different question.",
                "db_error": "A database error occurred. Please try again later.",
                "no_data": "No matching records found for your query.",
            }
            return {
                "event": "error",
                "message": messages.get(event, "An error occurred. Please try again."),
                "error_code": event,
                "request_id": request_id,
            }

        try:
            # Fetch or initialize conversation
            conversation = None
            if conversation_id:
                stmt = select(AIConversation).where(
                    AIConversation.id == conversation_id,
                    AIConversation.user_id == user_id
                )
                result = await self.db.execute(stmt)
                conversation = result.scalar_one_or_none()

            if not conversation:
                title = message[:40] + "..." if len(message) > 40 else message
                conversation = AIConversation(
                    user_id=user_id,
                    company_id=company_id,
                    title=title
                )
                self.db.add(conversation)
                await self.db.commit()
                conversation_id = conversation.id
            else:
                conversation_id = conversation.id

            # Save user message immediately to prevent foreign key rollback failures
            user_msg = AIMessage(
                conversation_id=conversation_id,
                role="user",
                message=message
            )
            self.db.add(user_msg)
            await self.db.commit()

            # Metadata event
            meta_event = {
                "event": "meta",
                "conversation_id": str(conversation_id)
            }
            yield f"data: {json.dumps(meta_event)}\n\n"
        except Exception as prep_exc:
            await self.db.rollback()
            logger.error("Failed to prepare database conversation context: %s", prep_exc)
            err_event = {
                "event": "error",
                "message": "Database context setup failed."
            }
            yield f"data: {json.dumps(err_event)}\n\n"
            await self.db.close()
            return

        # Handle message response
        is_who_are_you = any(p in message.lower() for p in ["who are you", "who are u", "what are you", "your name"])

        try:
            if is_who_are_you:
                who_msg = f"I'm {ASSISTANT_NAME}, your HRMS assistant. I can help with employees, payroll, attendance, reports, analytics, onboarding and company information."
                for token in who_msg.split(" "):
                    token_event = {"event": "token", "text": token + " "}
                    yield f"data: {json.dumps(token_event)}\n\n"
                    await asyncio.sleep(0.01)
                response_text = who_msg
                
            elif intent == "Greeting":
                greeting_msg = f"Hello! 👋 I'm {ASSISTANT_NAME}, your enterprise HR assistant. I can help you with employee records, department structures, payroll stats, attendance tracking, leave policies, onboarding details, and analytics. Try asking 'What departments do we have?' or 'Show all active employees'."
                for token in greeting_msg.split(" "):
                    token_event = {"event": "token", "text": token + " "}
                    yield f"data: {json.dumps(token_event)}\n\n"
                    await asyncio.sleep(0.01)
                response_text = greeting_msg
                
            elif intent == "Goodbye":
                goodbye_msg = "Goodbye! 👋 Have a wonderful day. Feel free to come back whenever you need help with your workforce."
                for token in goodbye_msg.split(" "):
                    token_event = {"event": "token", "text": token + " "}
                    yield f"data: {json.dumps(token_event)}\n\n"
                    await asyncio.sleep(0.01)
                response_text = goodbye_msg

            elif intent == "Help":
                help_msg = (
                    f"Hello! I am {ASSISTANT_NAME}, your HRMS assistant. Here are the categories of information you can query:\n\n"
                    "👥 **Employees**\n"
                    "- [Show all active employees](query:Show%20all%20active%20employees)\n"
                    "- [Show employees in Engineering](query:Show%20employees%20in%20Engineering)\n\n"
                    "📅 **Attendance**\n"
                    "- [Attendance today](query:Attendance%20today)\n"
                    "- [List check-ins today](query:List%20check-ins%20today)\n\n"
                    "💰 **Payroll**\n"
                    "- [Payroll summary](query:Payroll%20summary)\n"
                    "- [Average CTC per department](query:Average%20CTC%20per%20department)\n\n"
                    "🌴 **Leave**\n"
                    "- [Employees on leave this month](query:Employees%20on%20leave%20this%20month)\n"
                    "- [Leave policies](query:Leave%20policies)\n\n"
                    "🏢 **Departments**\n"
                    "- [Show departments](query:Show%20departments)\n\n"
                    "👔 **Managers**\n"
                    "- [List company managers](query:List%20company%20managers)\n\n"
                    "📊 **Reports & Analytics**\n"
                    "- [Show hiring report](query:Employees%20hired%20this%20month)\n"
                    "- [Show department headcount](query:Department%20headcount%20report)"
                )
                for line in help_msg.split("\n"):
                    token_event = {"event": "token", "text": line + "\n"}
                    yield f"data: {json.dumps(token_event)}\n\n"
                    await asyncio.sleep(0.01)
                response_text = help_msg

            elif intent in ("Database Query", "Analytics", "Payroll", "Attendance", "Leave", "Employee Search", "Department", "Report"):
                is_healthy = await ollama_client.check_health()
                if not is_healthy:
                    yield f"data: {json.dumps(_user_error('ollama_unreachable', 'Ollama unreachable'))}\n\n"
                    return

                # Load schema dynamically
                schema_desc = await self.schema_cache.get_schema_description(self.db)
                
                try:
                    results_json, generated_sql = await self._execute_sql_loop(
                        message=message,
                        company_id=company_id,
                        conversation_id=conversation_id,
                        claims=claims,
                        schema_desc=schema_desc,
                        max_retries=3,
                    )
                except LLMUnavailableError as llm_exc:
                    logger.error("LLM unavailable during SQL generation: %s", llm_exc)
                    yield f"data: {json.dumps(_user_error('model_missing', str(llm_exc)))}\n\n"
                    return
                except ValueError as val_exc:
                    logger.error("SQL validation failed after retries: %s", val_exc)
                    response_text = f"I couldn't execute that query because it doesn't match the current database schema. Error: {val_exc}"
                    token_event = {"event": "token", "text": response_text}
                    yield f"data: {json.dumps(token_event)}\n\n"
                except Exception as exc:
                    logger.error("SQL execution failed: %s", exc)
                    response_text = f"A database error occurred: {map_db_exception(exc)}"
                    token_event = {"event": "token", "text": response_text}
                    yield f"data: {json.dumps(token_event)}\n\n"
                else:
                    # 4. Format response and stream
                    format_prompt = ANSWER_FORMAT_PROMPT.format(
                        query=message,
                        results_json=results_json
                    )
                    try:
                        async for chunk in ollama_client.generate_stream(
                            prompt=format_prompt,
                            system_prompt=SYSTEM_PROMPT
                        ):
                            token = chunk.get("response", "")
                            if token:
                                response_text += token
                                token_event = {"event": "token", "text": token}
                                yield f"data: {json.dumps(token_event)}\n\n"
                    except Exception as exc:
                        logger.error("Response formatting stream failed: %s", exc)
                        response_text = f"Here are the database results:\n\n```json\n{results_json}\n```"
                        token_event = {"event": "token", "text": response_text}
                        yield f"data: {json.dumps(token_event)}\n\n"

            else:
                # Fallback for Unknown
                is_healthy = await ollama_client.check_health()
                if not is_healthy:
                    yield f"data: {json.dumps(_user_error('ollama_unreachable', 'Ollama unreachable'))}\n\n"
                    return

                db_facts = await self._gather_database_facts(message, company_id)
                history_text = await self._compile_history(conversation_id)
                user_prompt = USER_TEMPLATE.format(
                    total_employees=db_facts["total_employees"],
                    departments=", ".join(db_facts["departments"]) if db_facts["departments"] else "None",
                    recent_hires="; ".join(db_facts["recent_hires"]) if db_facts["recent_hires"] else "None",
                    open_jobs="; ".join(db_facts["open_jobs"]) if db_facts["open_jobs"] else "None",
                    matched_employee_text=db_facts["matched_employees_text"],
                    history_text=history_text,
                    user_message=message
                )
                try:
                    async for chunk in ollama_client.generate_stream(
                        prompt=user_prompt,
                        system_prompt=SYSTEM_PROMPT
                    ):
                        token = chunk.get("response", "")
                        if token:
                            response_text += token
                            token_event = {"event": "token", "text": token}
                            yield f"data: {json.dumps(token_event)}\n\n"
                except Exception as exc:
                    logger.error("Fallback grounding stream failed: %s", exc)
                    response_text = self._generate_fallback_response(message, db_facts)
                    token_event = {"event": "token", "text": response_text}
                    yield f"data: {json.dumps(token_event)}\n\n"

            # Save AI response - Rebind conversation to make sure the session state is clean
            stmt_c = select(AIConversation).where(AIConversation.id == conversation_id)
            res_c = await self.db.execute(stmt_c)
            conversation_obj = res_c.scalar_one_or_none()

            ai_msg = AIMessage(
                conversation_id=conversation_id,
                role="ai",
                message=response_text
            )
            self.db.add(ai_msg)
            if conversation_obj:
                conversation_obj.updated_at = datetime.now()
            await self.db.commit()
            rollback_status = "Committed successfully"
            
        except Exception as stream_exc:
            await self.db.rollback()
            rollback_status = "Executed exception stream rollback"
            logger.error("Stream exception caught: %s", stream_exc)
            # Yield error event safely without throwing ASGI exception
            err_event = {
                "event": "error",
                "message": "Stream request failed: " + map_db_exception(stream_exc)
            }
            yield f"data: {json.dumps(err_event)}\n\n"
        finally:
            await self.db.close()

        # Suggestions & Done
        try:
            db_facts = await self._gather_database_facts(message, company_id)
            suggestions = self._generate_dynamic_suggestions(message, db_facts)
            done_event = {
                "event": "done",
                "suggestions": suggestions,
                "sources": ["Internal SQL Database"] if intent not in ("Greeting", "Goodbye", "Help", "Unknown") else []
            }
            yield f"data: {json.dumps(done_event)}\n\n"
        except Exception as suggestion_exc:
            logger.error("Failed to generate stream suggestions: %s", suggestion_exc)

        # Logging profiler
        total_time = time.perf_counter() - start_time
        logger.info(
            "AI Request Performance Profiler:\n"
            "- User Message: %s\n"
            "- Detected Intent: %s\n"
            "- Generated SQL: %s\n"
            "- Validation Result: %s\n"
            "- Retry Count: %d\n"
            "- Execution Time: %.4fs\n"
            "- Rollback Status: %s\n"
            "- LLM Tokens: %s\n"
            "- LLM Response: %s",
            message, intent, generated_sql, validation_result, retry_count, total_time, rollback_status, tokens_count, response_text
        )

    async def _gather_database_facts(self, query: str, company_id: uuid.UUID | None) -> dict:
        """Fetch metadata facts from SQL Database to ground response with in-memory caching."""
        facts = {
            "total_employees": 0,
            "departments": [],
            "recent_hires": [],
            "open_jobs": [],
            "matched_employees_text": ""
        }

        normalized_query = query.lower()
        company_key = str(company_id) if company_id else "global"

        # 1. Total employees count (Cache for 60 seconds)
        cache_key_total = f"total_employees:{company_key}"
        cached_total = ai_cache.get(cache_key_total)
        if cached_total is not None:
            facts["total_employees"] = cached_total
        else:
            try:
                emp_count_stmt = select(func.count()).select_from(Employee).where(Employee.is_deleted == False)
                if company_id:
                    emp_count_stmt = emp_count_stmt.where(Employee.company_id == company_id)
                emp_count_res = await self.db.execute(emp_count_stmt)
                total = emp_count_res.scalar() or 0
                facts["total_employees"] = total
                ai_cache.set(cache_key_total, total, ttl=60)
            except Exception as err:
                logger.error("Error getting total employees: %s", err)

        # 2. Departments (Cache for 300 seconds)
        cache_key_depts = f"departments:{company_key}"
        cached_depts = ai_cache.get(cache_key_depts)
        if cached_depts is not None:
            facts["departments"] = cached_depts
        else:
            try:
                dept_stmt = select(Department.department_name).where(Department.is_deleted == False)
                if company_id:
                    dept_stmt = dept_stmt.where(Department.company_id == company_id)
                dept_res = await self.db.execute(dept_stmt)
                depts = list(dept_res.scalars().all())
                facts["departments"] = depts
                ai_cache.set(cache_key_depts, depts, ttl=300)
            except Exception as err:
                logger.error("Error getting departments: %s", err)

        # 3. Recent hires (this month) (Cache for 60 seconds)
        cache_key_hires = f"recent_hires:{company_key}"
        cached_hires = ai_cache.get(cache_key_hires)
        if cached_hires is not None:
            facts["recent_hires"] = cached_hires
        else:
            try:
                now = datetime.now()
                month_start = datetime(now.year, now.month, 1).date()
                recent_stmt = select(Employee).where(
                    Employee.joining_date >= month_start,
                    Employee.is_deleted == False
                )
                if company_id:
                    recent_stmt = recent_stmt.where(Employee.company_id == company_id)
                recent_stmt = recent_stmt.order_by(Employee.joining_date.desc()).limit(10)
                recent_res = await self.db.execute(recent_stmt)
                hired_objs = recent_res.scalars().all()
                hires = [
                    f"{emp.first_name} {emp.last_name} ({emp.joining_date}, {emp.department}, {emp.designation})"
                    for emp in hired_objs
                ]
                facts["recent_hires"] = hires
                ai_cache.set(cache_key_hires, hires, ttl=60)
            except Exception as err:
                logger.error("Error getting recent hires: %s", err)

        # 4. Open jobs (Cache for 60 seconds)
        cache_key_jobs = f"open_jobs:{company_key}"
        cached_jobs = ai_cache.get(cache_key_jobs)
        if cached_jobs is not None:
            facts["open_jobs"] = cached_jobs
        else:
            try:
                job_stmt = select(Job).where(Job.status == "PUBLISHED")
                if company_id:
                    job_stmt = job_stmt.where(Job.company_id == company_id)
                job_stmt = job_stmt.limit(10)
                job_res = await self.db.execute(job_stmt)
                job_objs = job_res.scalars().all()
                jobs = [f"{j.title} in {j.department}" for j in job_objs]
                facts["open_jobs"] = jobs
                ai_cache.set(cache_key_jobs, jobs, ttl=60)
            except Exception as err:
                logger.error("Error getting open jobs: %s", err)

        # 5. Search for specific employees if a name is searched
        words = [w for w in normalized_query.split() if w.isalpha() and len(w) >= 2]
        stopwords = {
            "show", "list", "who", "employee", "employees", "hired", "find", "search",
            "month", "active", "department", "departments", "designation", "manager",
            "salary", "what", "is", "are", "the", "for", "with", "this", "that"
        }
        name_tokens = [w for w in words if w not in stopwords]

        if name_tokens:
            try:
                from sqlalchemy import or_
                conditions = []
                for token in name_tokens:
                    conditions.append(Employee.first_name.ilike(f"%{token}%"))
                    conditions.append(Employee.last_name.ilike(f"%{token}%"))
                
                stmt = select(Employee).where(
                    Employee.is_deleted == False,
                    or_(*conditions)
                )
                if company_id:
                    stmt = stmt.where(Employee.company_id == company_id)
                stmt = stmt.limit(5)
                
                res = await self.db.execute(stmt)
                matched_emps = res.scalars().all()
                
                matched_lines = []
                for emp in matched_emps:
                    matched_lines.append(
                        f"- Found Employee: {emp.first_name} {emp.last_name} | ID: {emp.employee_id} | "
                        f"Dept: {emp.department} | Role: {emp.designation} | Joining Date: {emp.joining_date} | "
                        f"CTC: {emp.ctc or 'N/A'} | Status: {emp.employment_status}"
                    )
                if matched_lines:
                    facts["matched_employees_text"] = "\nMATCHED EMPLOYEE RECORDS:\n" + "\n".join(matched_lines)
            except Exception as err:
                logger.error("Error searching matching employees: %s", err)

        return facts

    async def _compile_history(self, conversation_id: uuid.UUID) -> str:
        """Fetch past messages in conversation for context. Limit to last 10 messages."""
        try:
            stmt = select(AIMessage).where(
                AIMessage.conversation_id == conversation_id
            ).order_by(AIMessage.created_at.desc()).limit(10)
            
            res = await self.db.execute(stmt)
            msgs = list(res.scalars().all())
            msgs.reverse()
            
            history_lines = []
            for m in msgs:
                role_label = "User" if m.role == "user" else "Assistant"
                history_lines.append(f"{role_label}: {m.message}")
            return "\n".join(history_lines)
        except Exception:
            return ""

    def _generate_fallback_response(self, query: str, facts: dict) -> str:
        """Generates a high-quality Markdown response using local facts when Ollama is offline."""
        q = query.lower()
        
        header = "💡 *[System Note: AI engine offline. Grounding response directly from database facts]*\n\n"
        
        if "hired" in q or "recent" in q or "joining" in q:
            if facts["recent_hires"]:
                tbl = "| Name | Date of Joining | Department | Designation |\n| --- | --- | --- | --- |\n"
                for entry in facts["recent_hires"]:
                    parts = entry.replace(")", "").split(" (")
                    name = parts[0]
                    subparts = parts[1].split(", ")
                    joining = subparts[0]
                    dept = subparts[1]
                    role = subparts[2]
                    tbl += f"| {name} | {joining} | {dept} | {role} |\n"
                return header + "Here are the employees hired this month:\n\n" + tbl
            else:
                return header + "There are no new employees registered as hired in the current month."

        if "department" in q or "dept" in q:
            if facts["departments"]:
                depts = "\n".join([f"- **{d}**" for d in facts["departments"]])
                return header + "The following departments are currently registered in the platform:\n\n" + depts
            else:
                return header + "No active departments were found in the database."

        if "total" in q or "how many employee" in q or "employee count" in q:
            return header + f"There are currently **{facts['total_employees']}** active employees registered in the system."

        if "job" in q or "openings" in q:
            if facts["open_jobs"]:
                jobs = "\n".join([f"- **{j}**" for j in facts["open_jobs"]])
                return header + "Here are the published job listings:\n\n" + jobs
            else:
                return header + "No active published job listings were found."

        if facts["matched_employees_text"]:
            return header + "Here is what I found in the database matching your query:\n\n" + facts["matched_employees_text"].replace("MATCHED EMPLOYEE RECORDS:\n", "")

        fallback_msg = (
            f"Hello! I am {ASSISTANT_NAME}, your workforce intelligence assistant.\n\n"
            f"Currently, my natural language generator is offline, but I can retrieve live facts from your database directly. "
            f"Here is a summary of your workplace data:\n\n"
            f"- **Total Active Employees:** {facts['total_employees']}\n"
            f"- **Departments ({len(facts['departments'])}):** {', '.join(facts['departments']) if facts['departments'] else 'None'}\n"
            f"- **Hires This Month:** {len(facts['recent_hires'])}\n"
            f"- **Active Job Postings:** {len(facts['open_jobs'])}\n\n"
            f"Feel free to ask about departments, hired employees, or workforce stats!"
        )
        return header + fallback_msg

    def _generate_dynamic_suggestions(self, query: str, facts: dict) -> list[str]:
        """Provide relevant dynamic follow-up questions."""
        q = query.lower()
        if "hired" in q or "recent" in q:
            return ["What departments do they work in?", "What is our total employee count?"]
        if "department" in q or "dept" in q:
            return ["Show employees hired this month", "Are there open jobs in these departments?"]
        return [
            "Show employees hired this month",
            "What departments do we have?",
            "List active jobs"
        ]


async def get_ai_service(db: Annotated[AsyncSession, Depends(get_db_session)]) -> AIService:
    """Dependency injection provider for AIService."""
    return AIService(db)
