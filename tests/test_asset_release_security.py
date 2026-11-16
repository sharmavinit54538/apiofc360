"""PostgreSQL API authorization and transactional lifecycle release gates."""
import asyncio
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from tests.test_asset_management_comprehensive import (
    db_session, test_company, test_user, test_employee, test_employee2, asset_service,
)
from app.api.assets import router
from app.core.exceptions import install_exception_handlers, BadRequestException, NotFoundException
from app.db.database import AsyncSessionLocal
from app.middleware.auth import get_current_user_claims
from app.models.asset import AssetRequest, Asset
from app.models.company import Company
from app.schemas.asset import AssetCreate, AssetAssignRequest, AssetRequestCreate
from app.services.asset_service import AssetService


@pytest_asyncio.fixture
async def api_client(test_company, test_user):
    app = FastAPI()
    app.include_router(router)
    install_exception_handlers(app)
    claims = {"sub": str(test_user.id), "company_id": str(test_company.id), "role": "hr_admin"}
    app.dependency_overrides[get_current_user_claims] = lambda: claims
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, claims


@pytest.mark.parametrize('role', ['employee', 'manager', 'executive'])
async def test_inventory_mutations_require_administrator(api_client, role):
    client, claims = api_client
    claims['role'] = role
    asset_id = uuid.uuid4()
    for method, path, body in [
        ('GET', '/assets', None), ('GET', f'/assets/{asset_id}', None),
        ('POST', '/assets', {'tag': 'DENIED', 'name': 'Denied', 'category': 'laptop'}),
        ('DELETE', f'/assets/{asset_id}', None),
        ('POST', f'/assets/{asset_id}/return', None),
        ('POST', f'/assets/requests/{uuid.uuid4()}/approve', None),
    ]:
        response = await client.request(method, path, json=body)
        assert response.status_code == 403, response.text


@pytest.mark.parametrize('role', ['hr_admin', 'it_admin', 'super_admin'])
async def test_inventory_admin_roles_can_create(api_client, role):
    client, claims = api_client
    claims['role'] = role
    response = await client.post('/assets', json={'tag': 'ALLOWED', 'name': 'Allowed', 'category': 'laptop'})
    assert response.status_code == 201, response.text


async def test_request_api_resolves_user_and_scopes_employee(api_client, test_employee, test_employee2):
    client, claims = api_client
    claims.update(role='employee', sub=str(test_employee.user_id))
    response = await client.post('/assets/requests', json={
        'request_type': 'NEW_ASSET', 'category': 'laptop', 'justification': 'Work laptop',
    })
    assert response.status_code == 201, response.text
    assert response.json()['data']['employee_id'] == str(test_employee.id)
    own = await client.get('/assets/requests')
    assert own.status_code == 200, own.text
    assert len(own.json()['data']) == 1
    # Managers do not gain visibility of every employee's requests.
    claims.update(role='manager', sub=str(test_employee2.user_id))
    other = await client.get('/assets/requests')
    assert other.status_code == 200, other.text
    assert other.json()['data'] == []
    claims.update(role='hr_admin', sub=str(test_employee.user_id))
    approved = await client.post(f"/assets/requests/{response.json()['data']['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()['data']['approver_id'] == str(test_employee.id)


async def test_damage_api_rejects_other_holder(api_client, asset_service, test_company, test_user, test_employee, test_employee2):
    asset = await asset_service.create_asset(AssetCreate(tag='OWNERSHIP', name='Laptop', category='laptop'), test_user.id, test_company.id)
    await asset_service.assign_asset(asset.id, AssetAssignRequest(employee_id=test_employee2.id), test_user.id, test_company.id)
    client, claims = api_client
    claims.update(role='employee', sub=str(test_employee.user_id))
    payload = {'asset_id': str(asset.id), 'damage_type': 'SCREEN', 'severity': 'MINOR', 'description': 'Scratch'}
    denied = await client.post('/assets/damage-reports', json=payload)
    assert denied.status_code == 403, denied.text
    claims['sub'] = str(test_employee2.user_id)
    allowed = await client.post('/assets/damage-reports', json=payload)
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()['data']['reported_by_id'] == str(test_employee2.id)


async def test_cross_tenant_api_read_and_mutation_denied(api_client, db_session, asset_service, test_company, test_user, test_employee):
    asset = await asset_service.create_asset(AssetCreate(tag='TENANT', name='Laptop', category='laptop'), test_user.id, test_company.id)
    request = await asset_service.create_asset_request(AssetRequestCreate(request_type='NEW_ASSET', category='laptop', justification='Work'), test_employee.id, test_company.id)
    other = Company(name='Other tenant')
    db_session.add(other)
    await db_session.commit()
    client, claims = api_client
    claims['company_id'] = str(other.id)
    assert (await client.get(f'/assets/{asset.id}')).status_code == 404
    assert (await client.delete(f'/assets/{asset.id}')).status_code == 404
    assert (await client.post(f'/assets/requests/{request.id}/approve')).status_code == 404
    assert (await client.get('/assets/requests')).json()['data'] == []
    with pytest.raises(NotFoundException):
        await asset_service.create_asset_request(AssetRequestCreate(request_type='NEW_ASSET', category='laptop', justification='Work'), test_employee.id, other.id)


async def test_archived_asset_cannot_be_assigned(asset_service, test_company, test_user, test_employee):
    asset = await asset_service.create_asset(AssetCreate(tag='ARCHIVED', name='Laptop', category='laptop'), test_user.id, test_company.id)
    await asset_service.delete_asset(asset.id, test_company.id, test_user.id)
    with pytest.raises(BadRequestException):
        await asset_service.assign_asset(asset.id, AssetAssignRequest(employee_id=test_employee.id), test_user.id, test_company.id)


async def test_fulfillment_competition_assigns_only_one_asset(asset_service, test_company, test_user, test_employee):
    request = await asset_service.create_asset_request(AssetRequestCreate(request_type='NEW_ASSET', category='laptop', justification='Work'), test_employee.id, test_company.id)
    await asset_service.approve_asset_request(request.id, test_user.id, test_company.id)
    assets = [await asset_service.create_asset(AssetCreate(tag=f'FULFILL-{i}', name='Laptop', category='laptop'), test_user.id, test_company.id) for i in range(2)]

    async def fulfill(asset):
        async with AsyncSessionLocal() as session:
            try:
                return await AssetService(session).fulfill_asset_request(request.id, asset.id, test_company.id)
            except BadRequestException as exc:
                await session.rollback()
                return exc

    results = await asyncio.wait_for(asyncio.gather(*(fulfill(a) for a in assets)), timeout=10)
    assert sum(isinstance(r, BadRequestException) for r in results) == 1
    async with AsyncSessionLocal() as session:
        states = list((await session.scalars(select(Asset.status).where(Asset.id.in_([a.id for a in assets])))).all())
        assert sorted(states) == ['assigned', 'available']


async def test_fulfillment_rolls_back_assignment_on_failure(asset_service, test_company, test_user, test_employee, monkeypatch):
    request = await asset_service.create_asset_request(AssetRequestCreate(request_type='NEW_ASSET', category='laptop', justification='Work'), test_employee.id, test_company.id)
    await asset_service.approve_asset_request(request.id, test_user.id, test_company.id)
    asset = await asset_service.create_asset(AssetCreate(tag='ATOMIC', name='Laptop', category='laptop'), test_user.id, test_company.id)
    async with AsyncSessionLocal() as session:
        service = AssetService(session)
        async def fail(*args, **kwargs):
            raise RuntimeError('Injected failure after assignment flush')
        monkeypatch.setattr(service.repo, 'update_asset_request', fail)
        with pytest.raises(RuntimeError, match='Injected'):
            await service.fulfill_asset_request(request.id, asset.id, test_company.id)
        await session.rollback()
    async with AsyncSessionLocal() as session:
        stored = await AssetService(session).get_asset(asset.id, test_company.id)
        pending = await session.get(AssetRequest, request.id)
        assert stored.status == 'available' and stored.employee_id is None
        assert stored.assignmentHistory == []
        assert pending.status == 'APPROVED' and pending.assigned_asset_id is None
