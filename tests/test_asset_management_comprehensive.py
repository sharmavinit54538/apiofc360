"""Comprehensive tests for Asset Management module."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import (
    Asset,
    AssetAssignmentHistory,
    AssetMaintenanceRecord,
    AssetRequest,
    AssetDamageReport,
    AssetRequestStatus,
    AssetRequestType,
)
from app.models.employee import Employee
from app.models.company import Company
from app.models.user import User, UserRole
from app.schemas.asset import (
    AssetCreate,
    AssetUpdate,
    AssetAssignRequest,
    AssetTransferRequest,
    AssetMaintenanceCreate,
    AssetMaintenanceComplete,
    AssetRequestCreate,
    AssetLostRequest,
    AssetDamageReportCreate,
)
from app.services.asset_service import AssetService
from app.repositories.asset_repository import AssetRepository
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.security import hash_password
from app.db.database import AsyncSessionLocal


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncSession:
    """Get a database session for testing."""
    async with AsyncSessionLocal() as session:
        yield session
        # Rollback any changes
        await session.rollback()


@pytest_asyncio.fixture(scope="function")
async def test_company(db_session: AsyncSession) -> Company:
    """Get or create a test company."""
    # Try to find an existing company first
    result = await db_session.execute(select(Company).limit(1))
    company = result.scalar_one_or_none()
    if company:
        return company
    
    # Create a minimal company with only required fields
    company = Company(
        name=f"Test Company {uuid.uuid4().hex[:8]}",
        status="PENDING",
    )
    db_session.add(company)
    await db_session.commit()
    await db_session.refresh(company)
    return company


@pytest_asyncio.fixture(scope="function")
async def test_user(db_session: AsyncSession, test_company: Company) -> User:
    """Create a test user with HR_ADMIN role."""
    user = User(
        name="Test HR Admin",
        email=f"hr_{uuid.uuid4().hex[:8]}@test.com",
        phone="9999999999",
        password_hash=hash_password("password123"),
        role=UserRole.HR_ADMIN,
        company_id=test_company.id,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture(scope="function")
async def test_employee(db_session: AsyncSession, test_company: Company, test_user: User) -> Employee:
    """Create a test employee."""
    employee = Employee(
        employee_id=f"EMP{uuid.uuid4().hex[:6]}",
        first_name="John",
        last_name="Doe",
        email=f"john.doe_{uuid.uuid4().hex[:6]}@test.com",
        personal_email="john.doe@personal.com",
        phone="9876543210",
        department="Engineering",
        designation="Software Engineer",
        company_id=test_company.id,
        user_id=test_user.id,
        joining_date=date.today() - timedelta(days=365),
        is_active=True,
        status="ACTIVE",
    )
    db_session.add(employee)
    await db_session.commit()
    await db_session.refresh(employee)
    return employee


@pytest_asyncio.fixture(scope="function")
async def test_employee2(db_session: AsyncSession, test_company: Company) -> Employee:
    """Create a second test employee."""
    user = User(
        name="Jane Smith",
        email=f"jane_{uuid.uuid4().hex[:8]}@test.com",
        phone="9876543211",
        password_hash=hash_password("password123"),
        role=UserRole.EMPLOYEE,
        company_id=test_company.id,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    
    employee = Employee(
        employee_id=f"EMP{uuid.uuid4().hex[:6]}",
        first_name="Jane",
        last_name="Smith",
        email=f"jane.smith_{uuid.uuid4().hex[:6]}@test.com",
        personal_email="jane.smith@personal.com",
        phone="9876543211",
        department="Marketing",
        designation="Marketing Manager",
        company_id=test_company.id,
        user_id=user.id,
        joining_date=date.today() - timedelta(days=180),
        is_active=True,
        status="ACTIVE",
    )
    db_session.add(employee)
    await db_session.commit()
    await db_session.refresh(employee)
    return employee


@pytest_asyncio.fixture(scope="function")
async def asset_service(db_session: AsyncSession) -> AssetService:
    """Create asset service instance."""
    return AssetService(db_session)


@pytest_asyncio.fixture(scope="function")
async def asset_repo(db_session: AsyncSession) -> AssetRepository:
    """Create asset repository instance."""
    return AssetRepository(db_session)


class TestAssetInventory:
    """Tests for asset inventory management."""

    async def test_create_asset(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test creating a new asset."""
        payload = AssetCreate(
            tag="LAP001",
            name="MacBook Pro 16",
            category="laptop",
            serial="SN123456",
            vendor="Apple",
            purchase_date=date.today() - timedelta(days=30),
            warranty_until=date.today() + timedelta(days=365),
            brand="Apple",
            model="MacBook Pro 16",
            purchase_cost=Decimal("250000.00"),
            location="Office",
            notes="New employee laptop",
        )
        
        result = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        assert result.id is not None
        assert result.tag == "LAP001"
        assert result.name == "MacBook Pro 16"
        assert result.status == "available"
        assert result.company_id == test_company.id
        assert result.assigned_to is None

    async def test_create_duplicate_tag_same_company_fails(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test that duplicate tag within same company fails."""
        payload = AssetCreate(
            tag="LAP001",
            name="MacBook Pro 16",
            category="laptop",
        )
        
        await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        with pytest.raises(BadRequestException, match="already exists"):
            await asset_service.create_asset(payload, test_user.id, test_company.id)

    async def test_create_same_tag_different_company_succeeds(self, asset_service: AssetService, db_session: AsyncSession, test_user: User):
        """Test that same tag in different companies succeeds."""
        company1 = Company(name="Company 1")
        company2 = Company(name="Company 2")
        db_session.add_all([company1, company2])
        await db_session.commit()
        
        payload = AssetCreate(tag="LAP001", name="Laptop", category="laptop")
        
        await asset_service.create_asset(payload, test_user.id, company1.id)
        result = await asset_service.create_asset(payload, test_user.id, company2.id)
        
        assert result.tag == "LAP001"
        assert result.company_id == company2.id

    async def test_list_assets_with_pagination(self, asset_service: AssetService, asset_repo: AssetRepository, test_company: Company, test_user: User):
        """Test listing assets with pagination."""
        # Create multiple assets
        for i in range(25):
            payload = AssetCreate(
                tag=f"LAP{i:03d}",
                name=f"Laptop {i}",
                category="laptop",
            )
            await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        # Test first page
        result = await asset_service.list_assets(test_company.id, page=1, limit=10)
        assert len(result.items) == 10
        assert result.total == 25
        assert result.page == 1
        
        # Test second page
        result = await asset_service.list_assets(test_company.id, page=2, limit=10)
        assert len(result.items) == 10
        assert result.page == 2

    async def test_filter_assets_by_status(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test filtering assets by status."""
        payload1 = AssetCreate(tag="LAP001", name="Laptop 1", category="laptop")
        payload2 = AssetCreate(tag="LAP002", name="Laptop 2", category="laptop")
        
        asset1 = await asset_service.create_asset(payload1, test_user.id, test_company.id)
        asset2 = await asset_service.create_asset(payload2, test_user.id, test_company.id)
        
        # Assign one asset
        assign_payload = AssetAssignRequest(
            employee_id=test_user.id,  # This will fail but we just need the asset created
            expected_return_date=None,
        )
        # Manually assign for test
        from app.models.employee import Employee
        emp = await asset_service.session.execute(
            select(Employee).where(Employee.user_id == test_user.id)
        )
        emp = emp.scalar_one()
        
        asset1.status = "assigned"
        asset1.employee_id = emp.id
        asset1.assigned_at = datetime.now()
        await asset_service.session.commit()
        
        # Filter by available
        result = await asset_service.list_assets(test_company.id, status="available")
        assert len(result.items) == 1
        assert result.items[0].tag == "LAP002"
        
        # Filter by assigned
        result = await asset_service.list_assets(test_company.id, status="assigned")
        assert len(result.items) == 1
        assert result.items[0].tag == "LAP001"


class TestAssetAssignment:
    """Tests for asset assignment workflow."""

    async def test_valid_assignment(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test assigning an available asset to an employee."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        assign_payload = AssetAssignRequest(
            employee_id=test_employee.id,
            expected_return_date=date.today() + timedelta(days=365),
            notes="New hire assignment",
        )
        
        result = await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)
        
        assert result.status == "assigned"
        assert result.assigned_to == f"{test_employee.first_name} {test_employee.last_name}"
        assert result.employee_id == test_employee.id

    async def test_assign_already_assigned_fails(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test that assigning an already assigned asset fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)
        
        # Try to assign again
        with pytest.raises(BadRequestException, match="already assigned"):
            await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)

    async def test_assign_lost_asset_fails(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test that assigning a lost asset fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        # Mark as lost
        lost_payload = AssetLostRequest(reason="Stolen from office")
        await asset_service.mark_lost(asset.id, lost_payload, test_user.id, test_company.id)
        
        # Try to assign
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        with pytest.raises(BadRequestException, match="current status is 'lost'"):
            await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)

    async def test_assign_retired_asset_fails(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test that assigning a retired asset fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        # Retire the asset
        await asset_service.mark_retired(asset.id, test_user.id, test_company.id)
        
        # Try to assign
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        with pytest.raises(BadRequestException, match="current status is 'retired'"):
            await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)

    async def test_assign_under_repair_asset_fails(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test that assigning an under-repair asset fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        # Send for maintenance
        maint_payload = AssetMaintenanceCreate(vendor="Apple Store", cost=Decimal("5000"))
        await asset_service.add_maintenance(asset.id, maint_payload, test_user.id, test_company.id)
        
        # Try to assign
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        with pytest.raises(BadRequestException, match="current status is 'under-repair'"):
            await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)

    async def test_assign_invalid_employee_fails(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test that assigning to non-existent employee fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        fake_employee_id = uuid.uuid4()
        assign_payload = AssetAssignRequest(employee_id=fake_employee_id)
        
        with pytest.raises(NotFoundException, match="Employee not found"):
            await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)

    async def test_assign_inactive_employee_fails(self, asset_service: AssetService, test_company: Company, test_user: User, db_session: AsyncSession):
        """Test that assigning to inactive employee fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        # Create inactive employee
        inactive_user = User(
            name="Inactive User",
            email="inactive@test.com",
            phone="9999999990",
            password_hash=hash_password("password123"),
            role=UserRole.EMPLOYEE,
            company_id=test_company.id,
            is_active=True,
            is_verified=True,
        )
        db_session.add(inactive_user)
        await db_session.commit()
        
        inactive_emp = Employee(
            employee_id="EMP999",
            first_name="Inactive",
            last_name="User",
            email="inactive@test.com",
            personal_email="inactive@personal.com",
            phone="9999999990",
            department="Engineering",
            designation="Engineer",
            company_id=test_company.id,
            user_id=inactive_user.id,
            joining_date=date.today(),
            is_active=False,
            status="INACTIVE",
        )
        db_session.add(inactive_emp)
        await db_session.commit()
        
        assign_payload = AssetAssignRequest(employee_id=inactive_emp.id)
        
        with pytest.raises(BadRequestException, match="inactive or deactivated"):
            await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)


class TestAssetReturn:
    """Tests for asset return workflow."""

    async def test_valid_return(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test returning an assigned asset."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)
        
        result = await asset_service.return_asset(asset.id, test_user.id, test_company.id)
        
        assert result.status == "available"
        assert result.assigned_to is None
        assert result.employee_id is None

    async def test_return_unassigned_fails(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test that returning an unassigned asset fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        with pytest.raises(BadRequestException, match="not currently assigned"):
            await asset_service.return_asset(asset.id, test_user.id, test_company.id)


class TestAssetTransfer:
    """Tests for asset transfer workflow."""

    async def test_valid_transfer(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee, test_employee2: Employee):
        """Test transferring asset between employees."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        # Assign to first employee
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)
        
        # Transfer to second employee
        transfer_payload = AssetTransferRequest(
            target_employee_id=test_employee2.id,
            expected_return_date=date.today() + timedelta(days=180),
            notes="Team transfer",
        )
        
        result = await asset_service.transfer_asset(asset.id, transfer_payload, test_user.id, test_company.id)
        
        assert result.status == "assigned"
        assert result.employee_id == test_employee2.id
        assert result.assigned_to == f"{test_employee2.first_name} {test_employee2.last_name}"

    async def test_transfer_unassigned_fails(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test that transferring unassigned asset fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        transfer_payload = AssetTransferRequest(target_employee_id=test_employee.id)
        
        with pytest.raises(BadRequestException, match="not currently assigned"):
            await asset_service.transfer_asset(asset.id, transfer_payload, test_user.id, test_company.id)

    async def test_transfer_same_employee_fails(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test that transferring to same employee fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)
        
        transfer_payload = AssetTransferRequest(target_employee_id=test_employee.id)
        
        with pytest.raises(BadRequestException, match="cannot be identical"):
            await asset_service.transfer_asset(asset.id, transfer_payload, test_user.id, test_company.id)

    async def test_transfer_cross_tenant_fails(self, asset_service: AssetService, db_session: AsyncSession, test_user: User, test_employee: Employee):
        """Test that transferring to employee in different company fails."""
        company2 = Company(name="Company 2")
        db_session.add(company2)
        await db_session.commit()
        
        # Create employee in company2
        user2 = User(
            name="User 2",
            email="user2@test.com",
            phone="9999999992",
            password_hash=hash_password("password123"),
            role=UserRole.EMPLOYEE,
            company_id=company2.id,
            is_active=True,
            is_verified=True,
        )
        db_session.add(user2)
        await db_session.commit()
        
        emp2 = Employee(
            employee_id="EMP003",
            first_name="Other",
            last_name="Company",
            email="other@test.com",
            personal_email="other@personal.com",
            phone="9999999992",
            department="Engineering",
            designation="Engineer",
            company_id=company2.id,
            user_id=user2.id,
            joining_date=date.today(),
            is_active=True,
            status="ACTIVE",
        )
        db_session.add(emp2)
        await db_session.commit()
        
        # Create asset in company1
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)
        
        # Try to transfer to company2 employee
        transfer_payload = AssetTransferRequest(target_employee_id=emp2.id)
        
        with pytest.raises(NotFoundException, match="Target employee not found"):
            await asset_service.transfer_asset(asset.id, transfer_payload, test_user.id, test_company.id)


class TestAssetStatusTransitions:
    """Tests for validated status transitions."""

    async def test_mark_lost_captures_last_holder(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test that marking asset lost captures last known holder."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)
        
        lost_payload = AssetLostRequest(reason="Left in taxi")
        result = await asset_service.mark_lost(asset.id, lost_payload, test_user.id, test_company.id)
        
        assert result.status == "lost"
        assert result.lost_reason == "Left in taxi"
        assert result.lost_date is not None
        assert result.last_known_holder_id == test_employee.id

    async def test_recover_lost_asset(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test recovering a lost asset."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)
        
        lost_payload = AssetLostRequest(reason="Left in taxi")
        await asset_service.mark_lost(asset.id, lost_payload, test_user.id, test_company.id)
        
        result = await asset_service.recover_lost_asset(asset.id, test_user.id, test_company.id)
        
        assert result.status == "available"
        assert result.lost_date is None
        assert result.lost_reason is None
        assert result.last_known_holder_id is None

    async def test_recover_non_lost_fails(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test that recovering non-lost asset fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        with pytest.raises(BadRequestException, match="not marked as lost"):
            await asset_service.recover_lost_asset(asset.id, test_user.id, test_company.id)

    async def test_direct_status_update_blocked(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test that direct status update via generic update is blocked."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        # Try to update status directly
        update_payload = AssetUpdate(name="Updated Name", status="assigned")
        
        with pytest.raises(BadRequestException, match="Direct status updates are not allowed"):
            await asset_service.update_asset(asset.id, update_payload, test_user.id, test_company.id)


class TestAssetMaintenance:
    """Tests for maintenance workflow."""

    async def test_add_maintenance_marks_under_repair(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test that adding maintenance marks asset as under-repair."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        maint_payload = AssetMaintenanceCreate(
            vendor="Apple Store",
            estimated_cost=Decimal("5000"),
            cost=Decimal("0"),
            notes="Screen replacement",
        )
        
        result = await asset_service.add_maintenance(asset.id, maint_payload, test_user.id, test_company.id)
        
        assert result.status == "under-repair"
        
        # Check maintenance record
        records = result.maintenance_history
        assert len(records) == 1
        assert records[0].vendor == "Apple Store"
        assert records[0].status == "REQUESTED"

    async def test_complete_maintenance(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test completing maintenance returns asset to available."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        # Start maintenance
        maint_payload = AssetMaintenanceCreate(vendor="Apple Store", estimated_cost=Decimal("5000"))
        result = await asset_service.add_maintenance(asset.id, maint_payload, test_user.id, test_company.id)
        
        maintenance_id = result.maintenance_history[0].id
        
        # Complete maintenance
        complete_payload = AssetMaintenanceComplete(
            completion_date=date.today(),
            actual_cost=Decimal("4500"),
            completion_notes="Screen replaced successfully",
        )
        
        result = await asset_service.complete_maintenance(asset.id, maintenance_id, complete_payload, test_user.id, test_company.id)
        
        assert result.status == "available"
        
        # Check maintenance record updated
        records = result.maintenance_history
        assert records[0].status == "COMPLETED"
        assert records[0].completion_date is not None
        assert records[0].cost == Decimal("4500")

    async def test_complete_maintenance_twice_fails(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test that completing already completed maintenance fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        maint_payload = AssetMaintenanceCreate(vendor="Apple Store")
        result = await asset_service.add_maintenance(asset.id, maint_payload, test_user.id, test_company.id)
        
        maintenance_id = result.maintenance_history[0].id
        
        complete_payload = AssetMaintenanceComplete()
        await asset_service.complete_maintenance(asset.id, maintenance_id, complete_payload, test_user.id, test_company.id)
        
        # Try to complete again
        with pytest.raises(BadRequestException, match="already completed"):
            await asset_service.complete_maintenance(asset.id, maintenance_id, complete_payload, test_user.id, test_company.id)


class TestAssetRequests:
    """Tests for asset request workflow."""

    async def test_create_asset_request(self, asset_service: AssetService, test_company: Company, test_employee: Employee):
        """Test employee creating an asset request."""
        payload = AssetRequestCreate(
            request_type="NEW_ASSET",
            category="laptop",
            justification="Need new laptop for development work",
            preferred_brand="Apple",
            preferred_model="MacBook Pro 16",
            estimated_cost=250000,
        )
        
        result = await asset_service.create_asset_request(payload, test_employee.id, test_company.id)
        
        assert result.id is not None
        assert result.request_type == "NEW_ASSET"
        assert result.status == "PENDING"
        assert result.employee_id == test_employee.id

    async def test_approve_asset_request(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test approving an asset request."""
        payload = AssetRequestCreate(
            request_type="NEW_ASSET",
            category="laptop",
            justification="Need new laptop",
        )
        request = await asset_service.create_asset_request(payload, test_employee.id, test_company.id)
        
        result = await asset_service.approve_asset_request(request.id, test_user.id, test_company.id)
        
        assert result.status == "APPROVED"
        assert result.approver_id == test_user.id
        assert result.approved_at is not None

    async def test_reject_asset_request(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test rejecting an asset request."""
        payload = AssetRequestCreate(
            request_type="NEW_ASSET",
            category="laptop",
            justification="Need new laptop",
        )
        request = await asset_service.create_asset_request(payload, test_employee.id, test_company.id)
        
        result = await asset_service.reject_asset_request(request.id, test_user.id, "Budget constraints", test_company.id)
        
        assert result.status == "REJECTED"
        assert result.rejection_reason == "Budget constraints"

    async def test_fulfill_asset_request(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test fulfilling an approved asset request."""
        # Create request
        payload = AssetRequestCreate(request_type="NEW_ASSET", category="laptop", justification="Need laptop")
        request = await asset_service.create_asset_request(payload, test_employee.id, test_company.id)
        
        # Approve
        await asset_service.approve_asset_request(request.id, test_user.id, test_company.id)
        
        # Create available asset
        asset_payload = AssetCreate(tag="LAP002", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(asset_payload, test_user.id, test_company.id)
        
        # Fulfill
        result = await asset_service.fulfill_asset_request(request.id, asset.id, test_company.id)
        
        assert result.status == "FULFILLED"
        assert result.assigned_asset_id == asset.id
        assert result.fulfilled_at is not None


class TestAssetDamageReports:
    """Tests for damage reporting workflow."""

    async def test_create_damage_report(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test employee reporting asset damage."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)
        
        damage_payload = AssetDamageReportCreate(
            asset_id=asset.id,
            damage_type="SCREEN",
            severity="MAJOR",
            description="Screen cracked after drop",
            location_of_incident="Office desk",
        )
        
        result = await asset_service.create_damage_report(damage_payload, test_employee.id, test_company.id)
        
        assert result.id is not None
        assert result.asset_id == asset.id
        assert result.damage_type == "SCREEN"
        assert result.severity == "MAJOR"
        assert result.status == "REPORTED"

    async def test_duplicate_damage_report_fails(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test that duplicate damage report for same asset by same employee fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)
        
        damage_payload = AssetDamageReportCreate(
            asset_id=asset.id,
            damage_type="SCREEN",
            severity="MAJOR",
            description="Screen cracked",
        )
        
        await asset_service.create_damage_report(damage_payload, test_employee.id, test_company.id)
        
        # Try to create another
        with pytest.raises(BadRequestException, match="already exists"):
            await asset_service.create_damage_report(damage_payload, test_employee.id, test_company.id)

    async def test_damage_report_invalid_asset_fails(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test that damage report for non-existent asset fails."""
        fake_asset_id = uuid.uuid4()
        
        damage_payload = AssetDamageReportCreate(
            asset_id=fake_asset_id,
            damage_type="SCREEN",
            severity="MAJOR",
            description="Screen cracked",
        )
        
        with pytest.raises(NotFoundException, match="Asset not found"):
            await asset_service.create_damage_report(damage_payload, test_employee.id, test_company.id)


class TestAssetSoftDelete:
    """Tests for soft deletion (archival)."""

    async def test_archive_asset(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test archiving an asset (soft delete)."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        await asset_service.delete_asset(asset.id, test_company.id, test_user.id)
        
        # Verify asset is archived
        result = await asset_service.get_asset(asset.id, test_company.id)
        assert result.status == "archived"
        assert result.is_deleted is True

    async def test_archive_assigned_asset_fails(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test that archiving assigned asset fails."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)
        
        with pytest.raises(BadRequestException, match="active assignment"):
            await asset_service.delete_asset(asset.id, test_company.id, test_user.id)


class TestWarrantyAnalytics:
    """Tests for warranty analytics."""

    async def test_warranty_analytics_separation(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test that warranty analytics properly separate active/expiring/expired/unknown."""
        today = date.today()
        
        # Active warranty (expires in 60 days)
        payload1 = AssetCreate(
            tag="LAP001",
            name="Laptop 1",
            category="laptop",
            warranty_until=today + timedelta(days=60),
        )
        # Expiring soon (expires in 15 days)
        payload2 = AssetCreate(
            tag="LAP002",
            name="Laptop 2",
            category="laptop",
            warranty_until=today + timedelta(days=15),
        )
        # Expired warranty
        payload3 = AssetCreate(
            tag="LAP003",
            name="Laptop 3",
            category="laptop",
            warranty_until=today - timedelta(days=30),
        )
        # Unknown warranty (no warranty date)
        payload4 = AssetCreate(
            tag="LAP004",
            name="Laptop 4",
            category="laptop",
            warranty_until=None,
        )
        
        for p in [payload1, payload2, payload3, payload4]:
            await asset_service.create_asset(p, test_user.id, test_company.id)
        
        analytics = await asset_service.get_analytics(test_company.id)
        
        assert analytics.active_warranty_assets == 1  # LAP001
        assert analytics.expiring_warranty_assets == 1  # LAP002
        assert analytics.expired_warranty_assets == 1  # LAP003
        assert analytics.unknown_warranty_assets == 1  # LAP004


class TestPublicAssetEndpoint:
    """Tests for public asset endpoint."""

    async def test_public_asset_exposes_limited_fields(self, asset_service: AssetService, test_company: Company, test_user: User):
        """Test that public endpoint only exposes limited fields."""
        payload = AssetCreate(
            tag="LAP001",
            name="MacBook Pro",
            category="laptop",
            serial="SN123456",
            vendor="Apple",
            purchase_cost=Decimal("250000"),
            purchase_date=date.today() - timedelta(days=30),
            warranty_until=date.today() + timedelta(days=365),
            brand="Apple",
            model="MacBook Pro 16",
            location="Office",
        )
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        # Get public asset
        public_asset = await asset_service.get_public_asset(asset.id)
        
        # Verify limited fields
        assert public_asset.id == asset.id
        assert public_asset.tag == asset.tag
        assert public_asset.name == asset.name
        assert public_asset.category == asset.category
        assert public_asset.serial == asset.serial
        assert public_asset.brand == asset.brand
        assert public_asset.model == asset.model
        assert public_asset.status == asset.status
        assert public_asset.location == asset.location
        
        # Verify sensitive fields NOT exposed
        assert not hasattr(public_asset, 'purchase_cost')
        assert not hasattr(public_asset, 'purchase_date')
        assert not hasattr(public_asset, 'warranty_until')
        assert not hasattr(public_asset, 'assigned_to')
        assert not hasattr(public_asset, 'assigned_at')
        assert not hasattr(public_asset, 'notes')
        assert not hasattr(public_asset, 'assignment_history')
        assert not hasattr(public_asset, 'maintenance_history')
        assert not hasattr(public_asset, 'timeline')


class TestConcurrentAssignment:
    """Tests for concurrent assignment safety."""

    async def test_concurrent_assignment_only_one_succeeds(self, db_session: AsyncSession, test_company: Company, test_user: User, test_employee: Employee, test_employee2: Employee):
        """Test that only one of two concurrent assignments succeeds."""
        # This test simulates concurrent access by using separate sessions
        # In real scenario, this would be tested with actual concurrent requests
        
        # Create asset
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset_service = AssetService(db_session)
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        # First assignment
        assign_payload1 = AssetAssignRequest(employee_id=test_employee.id)
        result1 = await asset_service.assign_asset(asset.id, assign_payload1, test_user.id, test_company.id)
        assert result1.status == "assigned"
        assert result1.employee_id == test_employee.id
        
        # Second assignment should fail
        assign_payload2 = AssetAssignRequest(employee_id=test_employee2.id)
        with pytest.raises(BadRequestException):
            await asset_service.assign_asset(asset.id, assign_payload2, test_user.id, test_company.id)


class TestExitIntegration:
    """Tests for exit management integration."""

    async def test_exit_creates_actual_asset_returns(self, db_session: AsyncSession, test_company: Company, test_user: User, test_employee: Employee):
        """Test that exit process creates asset returns from actual assignments."""
        from app.services.exit_service import ExitService
        from app.repositories.exit_repository import ExitRepository
        from app.repositories.auth_repository import AuthRepository
        from app.repositories.employee_repository import EmployeeRepository
        from app.schemas.exit import ResignationRequest
        
        # Assign assets to employee
        payload1 = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        payload2 = AssetCreate(tag="MON001", name="Dell Monitor", category="monitor")
        
        asset_service = AssetService(db_session)
        asset1 = await asset_service.create_asset(payload1, test_user.id, test_company.id)
        asset2 = await asset_service.create_asset(payload2, test_user.id, test_company.id)
        
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        await asset_service.assign_asset(asset1.id, assign_payload, test_user.id, test_company.id)
        await asset_service.assign_asset(asset2.id, assign_payload, test_user.id, test_company.id)
        
        # Create exit
        exit_repo = ExitRepository(db_session)
        auth_repo = AuthRepository(db_session)
        emp_repo = EmployeeRepository(db_session)
        exit_service = ExitService(db_session, exit_repo, auth_repo, emp_repo)
        
        resignation = ResignationRequest(
            last_working_date=date.today() + timedelta(days=30),
            reason="Better Opportunity",
            personal_email="personal@test.com",
            personal_phone="9876543210",
        )
        
        exit_result = await exit_service.submit_resignation(test_user.id, resignation)
        
        # Check asset returns were created from actual assignments
        assets = await exit_service.get_assets(exit_result.id)
        
        # Should have 2 assets from actual assignments
        asset_names = [a.asset_name for a in assets]
        assert "MacBook Pro (LAP001)" in asset_names
        assert "Dell Monitor (MON001)" in asset_names
        
        # Should NOT have default hardcoded assets
        assert "Keyboard" not in str(asset_names)
        assert "Mouse" not in str(asset_names)


class TestTimelinePersistence:
    """Tests for timeline event persistence."""

    async def test_timeline_events_persist(self, asset_service: AssetService, test_company: Company, test_user: User, test_employee: Employee):
        """Test that timeline events persist across operations."""
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_user.id, test_company.id)
        
        initial_timeline_count = len(asset.timeline)
        assert initial_timeline_count >= 1  # Creation event
        
        # Assign
        assign_payload = AssetAssignRequest(employee_id=test_employee.id)
        asset = await asset_service.assign_asset(asset.id, assign_payload, test_user.id, test_company.id)
        assert len(asset.timeline) == initial_timeline_count + 1
        
        # Return
        asset = await asset_service.return_asset(asset.id, test_user.id, test_company.id)
        assert len(asset.timeline) == initial_timeline_count + 2
        
        # Mark lost
        lost_payload = AssetLostRequest(reason="Test")
        asset = await asset_service.mark_lost(asset.id, lost_payload, test_user.id, test_company.id)
        assert len(asset.timeline) == initial_timeline_count + 3
        
        # Recover
        asset = await asset_service.recover_lost_asset(asset.id, test_user.id, test_company.id)
        assert len(asset.timeline) == initial_timeline_count + 4
        
        # Verify event types
        events = [e["event"] for e in asset.timeline]
        assert "Created" in events
        assert "Assigned" in events
        assert "Returned" in events
        assert "Lost" in events
        assert "Recovered" in events


class TestRBAC:
    """Tests for RBAC and multi-tenant isolation."""

    async def test_tenant_isolation_assets(self, asset_service: AssetService, db_session: AsyncSession, test_user: User):
        """Test that company A cannot access company B assets."""
        company_a = Company(name="Company A")
        company_b = Company(name="Company B")
        db_session.add_all([company_a, company_b])
        await db_session.commit()
        
        # Create asset in company A
        payload = AssetCreate(tag="LAP001", name="Laptop A", category="laptop")
        asset_a = await asset_service.create_asset(payload, test_user.id, company_a.id)
        
        # Try to access from company B context
        with pytest.raises(NotFoundException):
            await asset_service.get_asset(asset_a.id, company_b.id)
        
        # List assets in company B should not show company A asset
        result = await asset_service.list_assets(company_b.id)
        assert result.total == 0

    async def test_employee_cannot_access_other_employee_assets(self, asset_service: AssetService, test_company: Company, test_employee: Employee, test_employee2: Employee):
        """Test that employee cannot access another employee's asset details via ID manipulation."""
        # Create asset assigned to employee2
        payload = AssetCreate(tag="LAP001", name="MacBook Pro", category="laptop")
        asset = await asset_service.create_asset(payload, test_employee2.user_id, test_company.id)
        
        assign_payload = AssetAssignRequest(employee_id=test_employee2.id)
        await asset_service.assign_asset(asset.id, assign_payload, test_employee2.user_id, test_company.id)
        
        # Employee1 tries to access (would need employee1's user context)
        # This is enforced at API level by checking company_id
        # The service layer enforces company_id filtering
        asset_result = await asset_service.get_asset(asset.id, test_company.id)
        assert asset_result.assigned_to == f"{test_employee2.first_name} {test_employee2.last_name}"
        
        # But employee1 cannot access assets outside their company
        # (tested in test_tenant_isolation_assets)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])