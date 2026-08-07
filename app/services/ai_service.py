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

from app.core.exceptions import NotFoundException
from app.db.database import get_db_session
from app.models.ai import AIConversation, AIMessage
from app.models.employee import Employee
from app.models.department import Department
from app.models.recruitment import Job
from app.schemas.ai import ChatResponse, ConversationDetail, ConversationSummary
from app.services.ollama_client import ollama_client

logger = logging.getLogger(__name__)

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


class DBSchemaCache:
    """Dynamic DB Schema Cache with 10 minutes (600s) TTL."""
    def __init__(self, ttl: int = 600):
        self.ttl = ttl
        self.last_loaded = 0
        self.tables = {}  # e.g., {"employees": [{"column_name": "first_name", "data_type": "character varying"}, ...]}

    async def get_schema_description(self, db: AsyncSession) -> str:
        current_time = time.time()
        if not self.tables or (current_time - self.last_loaded > self.ttl):
            try:
                await self.load_schema(db)
            except Exception as e:
                logger.error("Failed to load DB schema dynamically: %s", e)
                if not self.tables:
                    return self.get_fallback_schema_description()
        
        # Build schema description string
        desc = "ACTUAL DATABASE SCHEMA (Do NOT invent tables or columns):\n"
        for table_name, columns in self.tables.items():
            desc += f"- {table_name} (\n"
            for col in columns:
                desc += f"    {col['column_name']} {col['data_type']},\n"
            desc += ")\n"
        return desc

    async def load_schema(self, db: AsyncSession):
        from sqlalchemy import text
        
        # Query active public tables
        tables_query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
        """
        res_tables = await db.execute(text(tables_query))
        table_names = [row[0] for row in res_tables.all()]
        
        new_tables = {}
        for table in table_names:
            # We strictly focus on employees, departments, and jobs for the copilot workspace context
            if table not in ("employees", "departments", "jobs"):
                continue
                
            columns_query = f"""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_schema = 'public' AND table_name = '{table}'
            """
            res_cols = await db.execute(text(columns_query))
            cols = [{"column_name": r[0], "data_type": r[1]} for r in res_cols.all()]
            new_tables[table] = cols
            
        if new_tables:
            self.tables = new_tables
            self.last_loaded = time.time()
            logger.info("Successfully loaded database schema dynamically: %s", list(self.tables.keys()))

    def get_fallback_schema_description(self) -> str:
        return """ACTUAL DATABASE SCHEMA:
- employees (
    employee_id character varying,
    first_name character varying,
    last_name character varying,
    personal_email character varying,
    company_email character varying,
    phone character varying,
    department character varying,
    designation character varying,
    employment_status character varying,
    joining_date date,
    ctc numeric,
    status character varying,
    is_deleted boolean,
    company_id uuid
)
- departments (
    company_id uuid,
    department_code character varying,
    department_name character varying,
    status character varying,
    is_deleted boolean
)
- jobs (
    company_id uuid,
    title character varying,
    department character varying,
    status character varying,
    is_deleted boolean
)
"""

schema_cache = DBSchemaCache()


SQL_KEYWORDS = {
    "select", "from", "join", "on", "where", "and", "or", "limit", "ilike", 
    "as", "distinct", "null", "not", "in", "order", "by", "group", "desc", 
    "asc", "like", "is", "left", "right", "inner", "outer", "cross", "using", 
    "count", "sum", "avg", "min", "max", "coalesce", "concat", "case", "when", 
    "then", "else", "end", "cast", "date", "interval", "extract", "now", "current_date",
    "true", "false", "having", "between", "any", "all", "exists",
    "date_trunc", "age", "to_char", "to_date", "to_number", "concat_ws", "round", "floor", "ceil", "nullif", "greatest", "least"
}


def validate_sql_query(sql: str, schema: dict) -> tuple[bool, str]:
    """Parses and validates a generated SQL query against table/column presence and dangerous keywords."""
    # Strip SQL comments
    # Remove single line comments
    q_clean = re.sub(r'--.*', '', sql)
    # Remove multi-line comments
    q_clean = re.sub(r'/\*.*?\*/', '', q_clean, flags=re.DOTALL)
    q_clean = q_clean.strip().strip(";").strip()
    
    if not q_clean:
        return False, "Generated query is empty."
        
    # Check for dangerous keywords (SQL Guard)
    dangerous_keywords = {"drop", "delete", "truncate", "alter", "update", "insert", "create", "grant", "revoke"}
    words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', q_clean.lower())
    for word in words:
        if word in dangerous_keywords:
            return False, f"Dangerous SQL keyword detected: '{word.upper()}' is strictly prohibited."
            
    if not q_clean.lower().startswith("select"):
        return False, f"Dangerous query blocked. Only safe SELECT queries are permitted. Query started with: {q_clean[:20]}"

    # Strip string literals enclosed in single quotes to prevent false positive identifier parsing
    q_no_literals = re.sub(r"'[^']*'", "", q_clean)
    
    # Collect all aliases defined using 'AS'
    aliases = set(re.findall(r'\bas\s+([a-zA-Z_][a-zA-Z0-9_]*)\b', q_no_literals, re.IGNORECASE))
    aliases = {a.lower() for a in aliases}
    
    tokens = re.split(r'\s+', q_no_literals.replace(",", " , ").replace("(", " ( ").replace(")", " ) ").strip())
    referenced_tables = {}  # alias: table_name
    
    idx = 0
    while idx < len(tokens):
        token_lower = tokens[idx].lower()
        if token_lower in ("from", "join"):
            idx += 1
            if idx < len(tokens):
                table_cand = tokens[idx].strip('",;`').lower()
                if table_cand == "(":
                    idx += 1
                    continue
                # Table verification
                if table_cand not in schema:
                    return False, f"Table '{table_cand}' does not exist in the database schema."
                
                alias = table_cand
                if idx + 1 < len(tokens):
                    next_token = tokens[idx + 1].lower()
                    if next_token == "as":
                        if idx + 2 < len(tokens):
                            alias = tokens[idx + 2].strip('",;`').lower()
                            idx += 2
                    elif next_token not in (",", "join", "on", "where", "limit", "order", "group", "and", "or", ")"):
                        alias = tokens[idx + 1].strip('",;`').lower()
                        idx += 1
                referenced_tables[alias] = table_cand
        idx += 1

    if not referenced_tables:
        return False, "No tables referenced in the query."

    # Map tables by their actual names too
    for tname in list(referenced_tables.values()):
        referenced_tables[tname] = tname

    # Collect valid columns
    valid_cols_by_table = {}
    all_valid_cols = set()
    for alias, tname in referenced_tables.items():
        valid_cols = {col["column_name"].lower() for col in schema[tname]}
        valid_cols_by_table[alias] = valid_cols
        all_valid_cols.update(valid_cols)

    # Check dot references (e.g. employees.first_name)
    dot_refs = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b', q_no_literals)
    for alias_cand, col_cand in dot_refs:
        alias_l = alias_cand.lower()
        col_l = col_cand.lower()
        
        if alias_l in referenced_tables:
            tname = referenced_tables[alias_l]
            if col_l not in valid_cols_by_table[alias_l]:
                return False, f"Column '{col_cand}' does not exist in table '{tname}'."

    # Check single word references
    all_words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', q_no_literals)
    for word in all_words:
        word_l = word.lower()
        if word_l in SQL_KEYWORDS:
            continue
        if word_l in referenced_tables:
            continue
        if word_l in aliases:
            continue
        
        # Verify it exists in at least one of the queried tables
        if word_l not in all_valid_cols:
            queried_tables_str = ", ".join(f"'{t}'" for t in set(referenced_tables.values()))
            return False, f"Column '{word}' does not exist in any of the queried tables: {queried_tables_str}."

    return True, "Valid SQL query."


def map_db_exception(exc: Exception) -> str:
    exc_name = type(exc).__name__
    exc_str = str(exc).lower()
    
    if "undefinedcolumn" in exc_str or "undefined_column" in exc_str:
        return "I couldn't execute that query because it references a column that does not exist in the database schema."
    if "undefinedtable" in exc_str or "undefined_table" in exc_str:
        return "I couldn't execute that query because it references a table that does not exist in the database schema."
    if "timeout" in exc_str:
        return "The database query timed out. Please try a simpler request."
    if isinstance(exc, ProgrammingError):
        return "There was a syntax or programming error in the generated database query."
    if isinstance(exc, IntegrityError):
        return "The database query could not be completed due to a data integrity constraint."
    if isinstance(exc, OperationalError):
        return "A database operational error occurred. The database might be busy or offline."
    if isinstance(exc, DBAPIError):
        return "A database interface error occurred."
    return f"A database error occurred: {exc_name}"


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
    msg = message.strip().lower()
    words = msg.split()
    cleaned_words = [w.strip("?,.!") for w in words]
    
    # 1. Greetings
    greetings = {
        "hi", "hii", "hiii", "hello", "hlo", "hey", "heyy", "hey there",
        "good morning", "good afternoon", "good evening", "g'day",
        "thanks", "thank you", "thank u", "thx"
    }
    
    # 2. Who are you / How can you help
    who_are_you_phrases = [
        "who are you", "who are u", "what are you", "your name",
        "how can you help", "how can u help", "what can you do", "what can u do"
    ]
    
    # 3. Goodbye
    goodbyes = {
        "bye", "goodbye", "see ya", "see you", "see u", "farewell", "quit", "exit"
    }
    
    # 4. Help
    help_words = {"help", "commands", "features", "guide"}

    # Checks
    if msg in greetings or (cleaned_words and cleaned_words[0] in greetings and len(cleaned_words) <= 2):
        return "Greeting"
        
    if any(p in msg for p in who_are_you_phrases) and len(cleaned_words) <= 6:
        return "Greeting"
        
    if msg in goodbyes or (cleaned_words and cleaned_words[0] in goodbyes and len(cleaned_words) <= 2):
        return "Goodbye"
        
    if msg in help_words or (len(cleaned_words) == 1 and cleaned_words[0] == "help"):
        return "Help"

    # Keywords classification
    payroll_keywords = {"payroll", "salary", "ctc", "pay", "compensation", "payslip"}
    attendance_keywords = {"attendance", "checkin", "checkout", "present", "absent", "working hours", "late", "shift"}
    leave_keywords = {"leave", "leaves", "vacation", "holiday", "holidays", "time off"}
    employee_keywords = {"employee", "employees", "staff", "member", "members", "personnel", "hire", "hired", "join", "joining"}
    department_keywords = {"department", "departments", "dept", "depts", "branch"}
    analytics_keywords = {"analytics", "chart", "graph", "metric", "metrics", "stats", "statistics", "insight", "insights"}
    report_keywords = {"report", "reports", "summary"}

    if any(k in msg for k in payroll_keywords):
        return "Payroll"
    if any(k in msg for k in attendance_keywords):
        return "Attendance"
    if any(k in msg for k in leave_keywords):
        return "Leave"
    if any(k in msg for k in department_keywords):
        return "Department"
    if any(k in msg for k in employee_keywords):
        return "Employee Search"
    if any(k in msg for k in report_keywords):
        return "Report"
    if any(k in msg for k in analytics_keywords):
        return "Analytics"
        
    db_indicators = {"show", "list", "select", "find", "search", "who is", "who are", "get", "display", "retrieve", "how many", "count"}
    if any(k in msg for k in db_indicators):
        return "Database Query"
        
    return "Unknown"


def clean_row_data(row_dict: dict) -> dict:
    """Strips sensitive columns, UUIDs, tokens, and system metadata from db results."""
    excluded_keys = {
        "id", "company_id", "created_by", "deleted_at", "updated_at",
        "activation_token", "activation_token_expires_at", "invited_by", "invited_at",
        "is_deleted", "password_hash", "password", "token", "token_expires_at",
        "department_id", "user_id", "reporting_manager_id"
    }
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
                
                sql_error = None
                max_retries = 3
                results_json = "[]"
                
                # SQL generation/repair loop
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
                        prompt = (
                            f"{schema_desc}\n\n"
                            + SQL_GEN_PROMPT.format(
                                company_id=str(company_id) if company_id else "",
                                history_text=history_text,
                                query=message
                            )
                        )
                    
                    try:
                        raw_sql = await ollama_client.generate_completion(
                            prompt=prompt,
                            system_prompt=SQL_SYSTEM_PROMPT,
                            model="gemma:2b"
                        )
                        generated_sql = clean_generated_sql(raw_sql)
                    except Exception as exc:
                        logger.error("SQL generation failed: %s", exc)
                        sql_error = f"Ollama model generation error: {str(exc)}"
                        retry_count += 1
                        continue

                    # Validate SQL
                    is_valid, err_msg = validate_sql_query(generated_sql, self.schema_cache.tables)
                    validation_result = err_msg
                    if not is_valid:
                        sql_error = err_msg
                        retry_count += 1
                        continue

                    # Execute SQL
                    try:
                        from sqlalchemy import text
                        result = await self.db.execute(text(generated_sql))
                        if result.returns_rows:
                            rows = result.mappings().all()
                            rows_returned = len(rows)
                            
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
                            
                            cleaned_rows = [clean_row_data(dict(row)) for row in rows]
                            if cleaned_rows:
                                results_json = json.dumps(cleaned_rows, cls=CustomEncoder, indent=2)
                            else:
                                results_json = "No matching records found in the database."
                        else:
                            results_json = "Query executed successfully, but returned no rows."
                        
                        # Success
                        sql_error = None
                        break
                    except Exception as sql_exc:
                        await self.db.rollback()
                        rollback_status = "Executed automatic rollback after execution failure"
                        logger.error("SQL query execution failed: %s. SQL: %s", sql_exc, generated_sql)
                        sql_error = map_db_exception(sql_exc)
                        retry_count += 1

                # If repair loop exhausted
                if sql_error:
                    response_text = f"I couldn't execute that query because it doesn't match the current database schema. Let me correct it. Error detail: {sql_error}"
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
                who_msg = "I'm Aurix AI, your HRMS assistant. I can help with employees, payroll, attendance, reports, analytics, onboarding and company information."
                for token in who_msg.split(" "):
                    token_event = {"event": "token", "text": token + " "}
                    yield f"data: {json.dumps(token_event)}\n\n"
                    await asyncio.sleep(0.01)
                response_text = who_msg
                
            elif intent == "Greeting":
                greeting_msg = "Hello! 👋 I'm Aurix AI, your enterprise HR assistant. I can help you with employee records, department structures, payroll stats, attendance tracking, leave policies, onboarding details, and analytics. Try asking 'What departments do we have?' or 'Show all active employees'."
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
                    "Hello! I am Aurix AI, your HRMS assistant. Here are the categories of information you can query:\n\n"
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
                    err_event = {
                        "event": "error",
                        "message": "Ollama AI model server is offline/unavailable.",
                        "status_code": 503
                    }
                    yield f"data: {json.dumps(err_event)}\n\n"
                    return

                # Load schema dynamically
                schema_desc = await self.schema_cache.get_schema_description(self.db)
                
                sql_error = None
                max_retries = 3
                results_json = "[]"
                
                # SQL Generation / Repair Loop
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
                        prompt = (
                            f"{schema_desc}\n\n"
                            + SQL_GEN_PROMPT.format(
                                company_id=str(company_id) if company_id else "",
                                history_text=history_text,
                                query=message
                            )
                        )

                    try:
                        raw_sql = await ollama_client.generate_completion(
                            prompt=prompt,
                            system_prompt=SQL_SYSTEM_PROMPT,
                            model="gemma:2b"
                        )
                        generated_sql = clean_generated_sql(raw_sql)
                    except Exception as exc:
                        logger.error("SQL generation failed: %s", exc)
                        sql_error = f"Ollama model generation error: {str(exc)}"
                        retry_count += 1
                        continue

                    # Validate SQL
                    is_valid, err_msg = validate_sql_query(generated_sql, self.schema_cache.tables)
                    validation_result = err_msg
                    if not is_valid:
                        sql_error = err_msg
                        retry_count += 1
                        continue

                    # Execute SQL
                    try:
                        from sqlalchemy import text
                        result = await self.db.execute(text(generated_sql))
                        if result.returns_rows:
                            rows = result.mappings().all()
                            rows_returned = len(rows)
                            
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
                            
                            cleaned_rows = [clean_row_data(dict(row)) for row in rows]
                            if cleaned_rows:
                                results_json = json.dumps(cleaned_rows, cls=CustomEncoder, indent=2)
                            else:
                                results_json = "No matching records found in the database."
                        else:
                            results_json = "Query executed successfully, but returned no rows."
                        
                        # Successful execution, exit loop
                        sql_error = None
                        break
                    except Exception as sql_exc:
                        await self.db.rollback()
                        rollback_status = "Executed automatic rollback after execution failure"
                        logger.error("SQL query execution failed: %s. SQL: %s", sql_exc, generated_sql)
                        sql_error = map_db_exception(sql_exc)
                        retry_count += 1

                # If repair loop exhausted
                if sql_error:
                    response_text = f"I couldn't execute that query because it doesn't match the current database schema. Let me correct it. Error detail: {sql_error}"
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
                    err_event = {
                        "event": "error",
                        "message": "Ollama AI model server is offline/unavailable.",
                        "status_code": 503
                    }
                    yield f"data: {json.dumps(err_event)}\n\n"
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
            f"Hello! I am Aurix AI, your workforce intelligence assistant.\n\n"
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
