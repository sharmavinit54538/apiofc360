"""E5 employee/leave/YTD migration validation, commit and snapshot rollback."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import delete as sql_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_migration import DataMigrationBatch, DataMigrationRecord
from app.models.employee import Employee
from app.models.leave_balance import LeaveBalance
from app.models.payroll_models import EmployeeYTDSalary
from app.services.employee_bulk_service import EmployeeBulkService, parse_tabular_file
from app.services.tenant_onboarding_service import validate_employee_assignment

MIGRATION_TYPES = {
    "EMPLOYEES": "EMPLOYEES", "EMPLOYEE_MASTER": "EMPLOYEES", "EMPLOYEE": "EMPLOYEES",
    "LEAVE_BALANCES": "LEAVE_BALANCES", "OPENING_LEAVE_BALANCES": "LEAVE_BALANCES", "LEAVE": "LEAVE_BALANCES",
    "YTD_SALARY": "YTD_SALARY", "YTD_SALARIES": "YTD_SALARY", "SALARY_YTD": "YTD_SALARY", "YTD": "YTD_SALARY",
}


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    return value


def _bool(value: Any, default: bool | None = None) -> bool | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "yes", "1", "y"}:
        return True
    if normalized in {"false", "no", "0", "n"}:
        return False
    raise ValueError(f"Invalid boolean value: {value}")


def _decimal(value: Any, field: str, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or value == "":
        return default
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be numeric.") from exc
    if result < 0:
        raise ValueError(f"{field} cannot be negative.")
    return result


def _paise(row: dict[str, Any], base: str, *aliases: str, default: int | None = 0) -> int | None:
    paise_key = f"{base}_paise"
    if row.get(paise_key) not in (None, ""):
        try:
            value = int(row[paise_key])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{paise_key} must be an integer.") from exc
        if value < 0:
            raise ValueError(f"{paise_key} cannot be negative.")
        return value
    raw = next((row[key] for key in (base, *aliases) if row.get(key) not in (None, "")), None)
    if raw is None:
        return default
    amount = _decimal(raw, base)
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class DataMigrationService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def migration_type(value: str) -> str:
        key = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        if key not in MIGRATION_TYPES:
            raise ValueError(f"Unsupported migration type: {value}")
        return MIGRATION_TYPES[key]

    async def validate_file(
        self, *, company_id: uuid.UUID, migration_type: str, file_bytes: bytes,
        filename: str, actor_id: uuid.UUID | None,
    ) -> DataMigrationBatch:
        rows = parse_tabular_file(file_bytes, filename)
        return await self.validate_payload(
            company_id=company_id, migration_type=migration_type, rows=rows,
            source_filename=filename, file_hash=hashlib.sha256(file_bytes).hexdigest(), actor_id=actor_id,
        )

    async def validate_payload(
        self, *, company_id: uuid.UUID, migration_type: str, rows: list[dict[str, Any]],
        source_filename: str | None = None, file_hash: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> DataMigrationBatch:
        canonical = self.migration_type(migration_type)
        normalized, errors = await self._validate(canonical, company_id, rows)
        digest = file_hash or hashlib.sha256(json.dumps(_safe(rows), sort_keys=True).encode("utf-8")).hexdigest()
        batch = DataMigrationBatch(
            company_id=company_id, migration_type=canonical, source_filename=source_filename,
            file_hash=digest, status="VALIDATED" if not errors else "VALIDATION_FAILED",
            total_rows=len(rows), valid_rows=len(normalized), error_rows=len({e["row"] for e in errors}),
            payload_json=_safe(rows), validation_errors_json=_safe(errors), created_by=actor_id,
        )
        self.session.add(batch)
        await self.session.commit()
        return batch

    async def _validate(
        self, canonical: str, company_id: uuid.UUID, rows: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not rows:
            return [], [{"row": 0, "message": "Migration file contains no data rows."}]
        if canonical == "EMPLOYEES":
            return await EmployeeBulkService(self.session).validate_employees(company_id, rows)
        if canonical == "LEAVE_BALANCES":
            return await self._validate_leave(company_id, rows)
        return await self._validate_ytd(company_id, rows)

    async def _employee_map(self, company_id: uuid.UUID) -> tuple[dict[str, Employee], dict[uuid.UUID, Employee]]:
        employees = (await self.session.execute(select(Employee).where(
            Employee.company_id == company_id, Employee.is_deleted == False,  # noqa: E712
        ))).scalars().all()
        return {employee.employee_id: employee for employee in employees}, {employee.id: employee for employee in employees}

    @staticmethod
    def _employee_reference(row: dict[str, Any], by_code: dict[str, Employee], by_id: dict[uuid.UUID, Employee]) -> Employee | None:
        reference = row.get("employee_uuid") or row.get("employee_id_uuid")
        if reference:
            try:
                return by_id.get(uuid.UUID(str(reference)))
            except ValueError:
                return None
        # In migration files employee_id normally means the human employee code;
        # accept a UUID in that column as a fallback too.
        code = str(row.get("employee_code") or row.get("employee_id") or "").strip()
        if code in by_code:
            return by_code[code]
        try:
            return by_id.get(uuid.UUID(code))
        except ValueError:
            return None

    async def _validate_leave(self, company_id: uuid.UUID, rows: list[dict[str, Any]]):
        by_code, by_id = await self._employee_map(company_id)
        valid, errors = [], []
        seen = set()
        for row_number, row in enumerate(rows, start=2):
            row_errors = []
            employee = self._employee_reference(row, by_code, by_id)
            leave_type = str(row.get("leave_type") or row.get("leave_code") or "").strip()
            if employee is None:
                row_errors.append("Employee was not found in the current tenant.")
            if not leave_type:
                row_errors.append("leave_type is required.")
            try:
                year_raw = row.get("year") or row.get("financial_year")
                year = int(str(year_raw)[:4]) if year_raw not in (None, "") else None
                allocated = _decimal(row.get("allocated_days") or row.get("total_days"), "allocated_days")
                used = _decimal(row.get("used_days"), "used_days")
                carried = _decimal(row.get("carried_forward_days") or row.get("carry_forward_days"), "carried_forward_days")
                balance = _decimal(row.get("balance_days") if row.get("balance_days") not in (None, "") else row.get("opening_balance"), "balance_days", allocated + carried - used)
                if balance < 0:
                    raise ValueError("balance_days cannot be negative.")
                basis = str(row.get("encashment_base") or row.get("basis") or "BASIC").upper()
                divisor = int(row.get("encashment_divisor") or row.get("divisor") or 30)
                if basis not in {"BASIC", "GROSS"} or divisor not in {26, 30}:
                    raise ValueError("Encashment basis must be BASIC/GROSS and divisor 26/30.")
                encashable = _bool(row.get("encashable"), None)
                encashable_days = _decimal(row.get("encashable_days"), "encashable_days", None) if row.get("encashable_days") not in (None, "") else None
            except (ValueError, TypeError) as exc:
                row_errors.append(str(exc))
                errors.extend({"row": row_number, "message": message} for message in row_errors)
                continue
            key = (employee.id if employee else None, leave_type.lower(), year)
            if key in seen:
                row_errors.append("Duplicate employee/leave type/year in the file.")
            seen.add(key)
            if row_errors:
                errors.extend({"row": row_number, "message": message} for message in row_errors)
                continue
            existing = (await self.session.execute(select(LeaveBalance).where(
                LeaveBalance.employee_id == employee.id, LeaveBalance.leave_type == leave_type,
                LeaveBalance.year == year,
            ))).scalars().first() if employee else None
            valid.append({
                "_row_number": row_number, "employee": employee, "leave_type": leave_type, "year": year,
                "allocated_days": allocated, "used_days": used, "carried_forward_days": carried,
                "balance_days": balance, "encashable": encashable, "encashable_days": encashable_days,
                "encashment_base": basis, "encashment_divisor": divisor, "existing": existing,
            })
        return valid, errors

    async def _validate_ytd(self, company_id: uuid.UUID, rows: list[dict[str, Any]]):
        by_code, by_id = await self._employee_map(company_id)
        valid, errors = [], []
        seen = set()
        for row_number, row in enumerate(rows, start=2):
            row_errors = []
            employee = self._employee_reference(row, by_code, by_id)
            if employee is None:
                row_errors.append("Employee was not found in the current tenant.")
            try:
                month = int(row.get("period_month") or row.get("month"))
                year = int(row.get("period_year") or row.get("year"))
                if not 1 <= month <= 12 or not 2000 <= year <= 2100:
                    raise ValueError("A valid period_month and period_year are required.")
                fy_start = year if month >= 4 else year - 1
                financial_year = f"{fy_start}-{fy_start + 1}"
                supplied_fy = str(row.get("financial_year") or "").strip()
                if supplied_fy and supplied_fy != financial_year:
                    raise ValueError(f"financial_year must be {financial_year} for this period.")
                gross = _paise(row, "gross_earnings", "gross")
                arrears_amount = _paise(row, "arrears")
                pf = _paise(row, "pf", "employee_pf")
                esi = _paise(row, "esi", "employee_esi")
                pt = _paise(row, "pt", "professional_tax")
                lwf = _paise(row, "lwf")
                tds = _paise(row, "tds", "income_tax")
                deductions = _paise(row, "total_deductions", "deductions", default=None)
                if deductions is None:
                    deductions = pf + esi + pt + lwf + tds
                net = _paise(row, "net_pay", "net", default=None)
                if net is None:
                    net = gross - deductions
                if net < 0:
                    raise ValueError("net_pay cannot be negative; verify gross and deductions.")
            except (ValueError, TypeError) as exc:
                row_errors.append(str(exc))
                errors.extend({"row": row_number, "message": message} for message in row_errors)
                continue
            key = (employee.id if employee else None, month, year)
            if key in seen:
                row_errors.append("Duplicate employee YTD period in the file.")
            seen.add(key)
            if row_errors:
                errors.extend({"row": row_number, "message": message} for message in row_errors)
                continue
            existing = (await self.session.execute(select(EmployeeYTDSalary).where(
                EmployeeYTDSalary.employee_id == employee.id,
                EmployeeYTDSalary.period_month == month, EmployeeYTDSalary.period_year == year,
            ))).scalar_one_or_none()
            valid.append({
                "_row_number": row_number, "employee": employee, "financial_year": financial_year,
                "period_month": month, "period_year": year, "gross_earnings_paise": gross,
                "arrears_paise": arrears_amount, "pf_paise": pf, "esi_paise": esi, "pt_paise": pt,
                "lwf_paise": lwf, "tds_paise": tds, "total_deductions_paise": deductions,
                "net_pay_paise": net, "existing": existing,
            })
        return valid, errors

    async def commit_batch(self, batch_id: uuid.UUID, *, company_id: uuid.UUID) -> DataMigrationBatch:
        batch = await self.session.get(DataMigrationBatch, batch_id)
        if batch is None or batch.company_id != company_id:
            raise ValueError("Migration batch not found in the current tenant.")
        if batch.status == "COMMITTED":
            return batch
        if batch.status != "VALIDATED" or batch.validation_errors_json:
            raise ValueError("Only an error-free VALIDATED batch can be committed.")
        normalized, errors = await self._validate(batch.migration_type, company_id, batch.payload_json)
        if errors or len(normalized) != batch.total_rows:
            batch.status = "VALIDATION_FAILED"
            batch.validation_errors_json = _safe(errors)
            batch.error_rows = len({error["row"] for error in errors})
            await self.session.commit()
            raise ValueError("Migration validation failed again at commit; no rows were imported.")
        try:
            if batch.migration_type == "EMPLOYEES":
                await self._commit_employees(batch, normalized)
            elif batch.migration_type == "LEAVE_BALANCES":
                await self._commit_leave(batch, normalized)
            else:
                await self._commit_ytd(batch, normalized)
            batch.status = "COMMITTED"
            batch.committed_at = datetime.now(timezone.utc)
            await self.session.commit()
            return batch
        except Exception:
            await self.session.rollback()
            batch.status = "COMMIT_FAILED"
            await self.session.commit()
            raise

    @staticmethod
    def _record(batch: DataMigrationBatch, row_number: int, entity_type: str, entity, action: str, before: dict | None):
        return DataMigrationRecord(
            company_id=batch.company_id, batch_id=batch.id, row_number=row_number,
            entity_type=entity_type, entity_id=entity.id, action=action,
            before_snapshot_json=_safe(before), after_snapshot_json=_safe(DataMigrationService._snapshot(entity_type, entity)),
        )

    async def _commit_employees(self, batch: DataMigrationBatch, rows: list[dict[str, Any]]):
        created = {}
        for item in rows:
            values = {key: value for key, value in item.items() if not key.startswith("_") and key != "manager_code"}
            employee = Employee(**values, company_id=batch.company_id, created_by=batch.created_by, reporting_manager_id=None)
            self.session.add(employee)
            created[employee.employee_id] = employee
        await self.session.flush()
        all_employees = (await self.session.execute(select(Employee).where(Employee.company_id == batch.company_id))).scalars().all()
        by_code = {employee.employee_id: employee for employee in all_employees}
        by_code.update(created)
        for item in rows:
            employee = created[item["employee_id"]]
            if item.get("_manager_code"):
                manager = by_code.get(item["_manager_code"])
                if manager is None or manager.id == employee.id:
                    raise ValueError(f"Invalid manager at row {item['_row_number']}.")
                employee.reporting_manager_id = manager.id
            await validate_employee_assignment(self.session, employee)
            self.session.add(self._record(batch, item["_row_number"], "EMPLOYEE", employee, "CREATE", None))

    @staticmethod
    def _leave_values(item: dict[str, Any]) -> dict[str, Any]:
        return {key: item[key] for key in (
            "leave_type", "year", "allocated_days", "used_days", "carried_forward_days", "balance_days",
            "encashable", "encashable_days", "encashment_base", "encashment_divisor",
        )}

    async def _commit_leave(self, batch: DataMigrationBatch, rows: list[dict[str, Any]]):
        for item in rows:
            existing = item["existing"]
            before = self._snapshot("LEAVE_BALANCE", existing) if existing else None
            if existing is None:
                existing = LeaveBalance(company_id=batch.company_id, employee_id=item["employee"].id)
                self.session.add(existing)
            for key, value in self._leave_values(item).items():
                setattr(existing, key, value)
            await self.session.flush()
            self.session.add(self._record(batch, item["_row_number"], "LEAVE_BALANCE", existing, "UPDATE" if before else "CREATE", before))

    async def _commit_ytd(self, batch: DataMigrationBatch, rows: list[dict[str, Any]]):
        fields = (
            "financial_year", "period_month", "period_year", "gross_earnings_paise", "arrears_paise",
            "pf_paise", "esi_paise", "pt_paise", "lwf_paise", "tds_paise", "total_deductions_paise", "net_pay_paise",
        )
        for item in rows:
            existing = item["existing"]
            before = self._snapshot("YTD_SALARY", existing) if existing else None
            if existing is None:
                existing = EmployeeYTDSalary(company_id=batch.company_id, employee_id=item["employee"].id)
                self.session.add(existing)
            for key in fields:
                setattr(existing, key, item[key])
            existing.source = "E5_MIGRATION"
            existing.migration_batch_id = batch.id
            await self.session.flush()
            self.session.add(self._record(batch, item["_row_number"], "YTD_SALARY", existing, "UPDATE" if before else "CREATE", before))

    @staticmethod
    def _snapshot(entity_type: str, entity: Any) -> dict[str, Any]:
        if entity is None:
            return {}
        if entity_type == "EMPLOYEE":
            fields = ("employee_id", "first_name", "last_name", "personal_email", "company_email", "phone", "department", "designation", "joining_date", "employment_type", "employment_status", "status", "branch_id", "legal_entity_id", "department_id", "reporting_manager_id", "company_id")
        elif entity_type == "LEAVE_BALANCE":
            fields = ("employee_id", "company_id", "leave_type", "year", "allocated_days", "used_days", "carried_forward_days", "balance_days", "encashable", "encashable_days", "encashment_base", "encashment_divisor")
        else:
            fields = ("employee_id", "company_id", "financial_year", "period_month", "period_year", "gross_earnings_paise", "arrears_paise", "pf_paise", "esi_paise", "pt_paise", "lwf_paise", "tds_paise", "total_deductions_paise", "net_pay_paise", "source", "migration_batch_id")
        return _safe({field: getattr(entity, field, None) for field in fields})

    async def rollback_batch(
        self, batch_id: uuid.UUID, *, company_id: uuid.UUID, reason: str | None = None,
    ) -> DataMigrationBatch:
        batch = await self.session.get(DataMigrationBatch, batch_id)
        if batch is None or batch.company_id != company_id:
            raise ValueError("Migration batch not found in the current tenant.")
        if batch.status == "ROLLED_BACK":
            return batch
        if batch.status != "COMMITTED":
            raise ValueError("Only a COMMITTED batch can be rolled back.")
        records = (await self.session.execute(select(DataMigrationRecord).where(
            DataMigrationRecord.batch_id == batch.id
        ).order_by(DataMigrationRecord.row_number.desc()))).scalars().all()
        employee_ids = [record.entity_id for record in records if record.entity_type == "EMPLOYEE" and record.action == "CREATE"]
        if employee_ids:
            employees = (await self.session.execute(select(Employee).where(
                Employee.id.in_(employee_ids), Employee.company_id == batch.company_id,
            ))).scalars().all()
            for employee in employees:
                employee.reporting_manager_id = None
                employee.manager_id = None
            await self.session.flush()
        for record in records:
            model = {"EMPLOYEE": Employee, "LEAVE_BALANCE": LeaveBalance, "YTD_SALARY": EmployeeYTDSalary}[record.entity_type]
            entity = await self.session.get(model, record.entity_id)
            if entity is None:
                record.status = "ROLLED_BACK"
                continue
            if entity.company_id != batch.company_id:
                raise ValueError("Migration record points outside the current tenant.")
            if record.action == "CREATE":
                # Do not ORM-cascade through data added after the import.  Only
                # the row created by this batch is removed; database FKs still
                # protect rows that have since acquired dependencies.
                await self.session.execute(sql_delete(model).where(
                    model.id == record.entity_id, model.company_id == batch.company_id,
                ))
            else:
                for key, value in (record.before_snapshot_json or {}).items():
                    if key in {"company_id", "employee_id", "branch_id", "legal_entity_id", "department_id", "reporting_manager_id", "migration_batch_id"} and value:
                        value = uuid.UUID(value)
                    elif key == "joining_date" and value:
                        value = date.fromisoformat(value)
                    elif key in {"allocated_days", "used_days", "carried_forward_days", "balance_days", "encashable_days"} and value is not None:
                        value = Decimal(value)
                    setattr(entity, key, value)
            record.status = "ROLLED_BACK"
        batch.status = "ROLLED_BACK"
        batch.rolled_back_at = datetime.now(timezone.utc)
        batch.rollback_reason = reason
        await self.session.commit()
        return batch

    async def get_batch(self, batch_id: uuid.UUID, *, company_id: uuid.UUID) -> DataMigrationBatch:
        batch = await self.session.get(DataMigrationBatch, batch_id)
        if batch is None or batch.company_id != company_id:
            raise ValueError("Migration batch not found in the current tenant.")
        return batch


__all__ = ["DataMigrationService", "MIGRATION_TYPES"]
